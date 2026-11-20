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
    """Get the real opencode command from environment variable."""
    cmd = os.environ.get("AURA_OPENCODE_REAL_COMMAND")
    if not cmd:
        pytest.skip("AURA_OPENCODE_REAL_COMMAND not set; skipping real binary test")
    return cmd


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
    settings.opencode_command = [real_opencode_command]
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
        assert connection.auth.username == "opencode"
        assert connection.auth.password is not None
        assert len(connection.auth.password) > 0
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
                assert data.get("id") == agent_id
        
        print(f"Real OpenCode server started successfully at {connection.base_url}")
        print(f"Version: {connection.version}")
        print(f"Password: {connection.auth.password}")
        
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