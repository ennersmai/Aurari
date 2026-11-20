"""
Integration test for the real OpenCode binary (W3-31b).

This test requires AURA_OPENCODE_REAL_COMMAND to be set to the path of the
real opencode binary (e.g., "opencode" or "/path/to/opencode").

It verifies that OpenCodeProcess.start() works with the real v2.3.2 binary,
correctly extracting the URL and password from the actual output lines.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from aura.config import settings
from aura.connections.opencode_process import OpenCodeConnection, OpenCodeProcess


@pytest.fixture
def real_opencode_command():
    """Get the real opencode command from environment variable.

    Accepts either a JSON list (e.g., '["opencode", "serve"]') or a plain path
    (e.g., 'opencode' or '/path/to/opencode'). If it's a plain path, it's
    converted to a single-element list.
    """
    import json
    cmd_str = os.environ.get("AURA_OPENCODE_REAL_COMMAND")
    if not cmd_str:
        pytest.skip("AURA_OPENCODE_REAL_COMMAND not set; skipping real binary test")
    try:
        if cmd_str.strip().startswith("["):
            return json.loads(cmd_str)
        else:
            return [cmd_str]
    except json.JSONDecodeError:
        # If it's not valid JSON, treat as plain path
        return [cmd_str]


@pytest.fixture
def free_port() -> int:
    """Get a free port for testing."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory for the test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


async def test_opencode_real_binary_starts(
    real_opencode_command: str,
    free_port: int,
    temp_config_dir: Path,
) -> None:
    """
    Test that the real OpenCode binary starts successfully and
    OpenCodeProcess correctly extracts the URL and password.
    
    This test requires:
    - AURA_OPENCODE_REAL_COMMAND set to the opencode binary path
    - The binary must be v2.3.2 (or compatible major version)
    """
    # Write the config file
    from aura.connections.opencode_agents import write_config
    config_path = write_config(temp_config_dir)
    print(f"Wrote config to {config_path}")
    
    # Configure settings to use the real binary
    settings.opencode_command = real_opencode_command
    settings.opencode_version_pin = "2.3.2"
    settings.opencode_host = "127.0.0.1"
    settings.opencode_port = free_port
    settings.opencode_start_timeout_secs = 60  # Real binary may take longer
    settings.opencode_agent_model = "sluice/coder"
    settings.opencode_config_dir = str(temp_config_dir)
    
    process = OpenCodeProcess()
    
    try:
        connection = await process.start()
        
        # Verify connection details
        assert isinstance(connection, OpenCodeConnection)
        assert connection.base_url == f"http://127.0.0.1:{free_port}"
        assert isinstance(connection.auth, httpx.BasicAuth)
        # httpx.BasicAuth stores credentials in the auth header; verify by decoding
        auth_header = connection.auth._auth_header
        assert auth_header is not None
        assert auth_header.startswith("Basic ")
        import base64
        encoded = auth_header.split(" ")[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        # Should be "opencode:<password>"
        assert decoded.startswith("opencode:")
        password = decoded.split(":", 1)[1]
        assert len(password) > 0
        assert connection.version.startswith("2.3.")
        
        # Verify agents are accessible
        async with httpx.AsyncClient(timeout=10.0) as client:
            for agent_id in ["aura-explore", "aura-build", "aura-review"]:
                response = await client.get(
                    f"{connection.base_url}/api/agent/{agent_id}",
                    auth=connection.auth,
                )
                assert response.status_code == 200, f"Agent {agent_id} not found: {response.text}"
                data = response.json()
                # Real server returns {location, data: {id, name, model, ...}}
                agent_data = data.get("data", {})
                assert agent_data.get("id") == agent_id, f"Agent ID mismatch: {agent_data}"
        
        # Extract password from auth header for logging
        auth_header = connection.auth._auth_header
        import base64
        encoded = auth_header.split(" ")[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        password = decoded.split(":", 1)[1]
        
        print(f"Real OpenCode server started successfully at {connection.base_url}")
        print(f"Version: {connection.version}")
        print(f"Password: {password}")
        
    finally:
        await process.stop()


# Need to import httpx for the test
import httpx


if __name__ == "__main__":
    # Allow running directly for quick manual testing
    import asyncio
    
    # Check for the environment variable
    if not os.environ.get("AURA_OPENCODE_REAL_COMMAND"):
        print("Set AURA_OPENCODE_REAL_COMMAND to the opencode binary path to run this test")
        print("Example: AURA_OPENCODE_REAL_COMMAND=opencode python -m pytest tests/integration/test_opencode_real.py -v")
        sys.exit(0)
    
    async def main():
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            await test_opencode_real_binary_starts(
                os.environ["AURA_OPENCODE_REAL_COMMAND"],
                port,
                Path(tmpdir),
            )
    
    asyncio.run(main())