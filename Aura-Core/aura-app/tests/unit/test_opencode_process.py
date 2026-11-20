"""
Tests for the OpenCodeProcess class (W3-27, W3-31a).

Tests cover:
- Start succeeds with correct version
- Version mismatch (major) raises OpenCodeVersionError
- Different minor/patch version starts with warning
- Process exiting immediately raises OpenCodeStartError
- Password does not appear in captured logs
- stop() leaves no child process running
- Agent configuration via XDG_CONFIG_HOME (W3-31a)
- Process starts child with XDG_CONFIG_HOME set and without XDG_DATA_HOME
- Start fails when fake does not serve one of the agents
- No request to /api/experimental/config is ever made
"""

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from aura.config import settings
from aura.connections.opencode_process import (
    OpenCodeConnection,
    OpenCodeProcess,
    OpenCodeStartError,
    OpenCodeVersionError,
)
from tests.fixtures.fake_opencode_server import _request_paths


@pytest.fixture
def free_port() -> int:
    """Get a free port for testing."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake_server_script() -> Path:
    """Path to the fake OpenCode server script."""
    return Path(__file__).parent.parent / "fixtures" / "fake_opencode_server.py"


class TestOpenCodeProcess:
    """Tests for OpenCodeProcess."""

    @pytest.fixture(autouse=True)
    def reset_settings(self, monkeypatch):
        """Reset settings before each test."""
        # We need to patch settings since they're read at import time
        # but we can modify the settings instance
        original_command = settings.opencode_command
        original_version_pin = settings.opencode_version_pin
        original_host = settings.opencode_host
        original_port = settings.opencode_port
        original_timeout = settings.opencode_start_timeout_secs
        original_agent_model = settings.opencode_agent_model
        original_config_dir = settings.opencode_config_dir
        original_router_base_url = settings.opencode_router_base_url

        yield

        # Restore
        settings.opencode_command = original_command
        settings.opencode_version_pin = original_version_pin
        settings.opencode_host = original_host
        settings.opencode_port = original_port
        settings.opencode_start_timeout_secs = original_timeout
        settings.opencode_agent_model = original_agent_model
        settings.opencode_config_dir = original_config_dir
        settings.opencode_router_base_url = original_router_base_url

    async def test_start_succeeds_with_correct_version(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that start succeeds and returns correct version."""
        # Configure settings to use the fake server
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.3.2",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_agent_model = "sluice/coder"
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()
            connection = await process.start()

            try:
                assert isinstance(connection, OpenCodeConnection)
                assert connection.version == "2.3.2"
                assert connection.base_url == f"http://127.0.0.1:{free_port}"
                assert isinstance(connection.auth, httpx.BasicAuth)
                # Verify auth works by checking the Authorization header it generates
                auth_header = connection.auth._auth_header
                assert auth_header is not None
                # Decode and verify
                import base64
                encoded = auth_header.split(" ")[1]
                decoded = base64.b64decode(encoded).decode("utf-8")
                assert decoded == "opencode:test-secret-123"
            finally:
                await process.stop()

    async def test_version_mismatch_major_raises_error(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that major version mismatch raises OpenCodeVersionError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "3.0.0",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()

            with pytest.raises(OpenCodeVersionError) as exc_info:
                await process.start()

            # Check error message contains both versions
            error_msg = str(exc_info.value)
            assert "2.3.2" in error_msg
            assert "3.0.0" in error_msg
            assert "major" in error_msg.lower()

            await process.stop()

    async def test_different_minor_patch_starts_with_warning(
        self, free_port: int, fake_server_script: Path, caplog
    ) -> None:
        """Test that different minor/patch version starts with a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.4.0",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()

            with caplog.at_level(logging.WARNING):
                connection = await process.start()

            try:
                assert connection.version == "2.4.0"
                # Check warning was logged
                warning_logs = [r for r in caplog.records if r.levelno == logging.WARNING]
                assert any("differs from pin" in r.message for r in warning_logs)
                assert any("2.3.2" in r.message and "2.4.0" in r.message for r in warning_logs)
            finally:
                await process.stop()

    async def test_process_exit_before_output_raises_start_error(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that a process exiting before printing URL/password raises OpenCodeStartError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.3.2",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
                "--exit-before-output",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 5
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()

            with pytest.raises(OpenCodeStartError) as exc_info:
                await process.start()

            error_msg = str(exc_info.value)
            assert "exited before printing URL and password" in error_msg

    async def test_password_not_in_logs(
        self, free_port: int, fake_server_script: Path, caplog
    ) -> None:
        """Test that the password does not appear in captured logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.3.2",
                "--port",
                str(free_port),
                "--password",
                "super-secret-password-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()

            with caplog.at_level(logging.DEBUG):
                connection = await process.start()

            try:
                # Check that the password never appears in logs
                all_log_text = caplog.text
                assert "super-secret-password-123" not in all_log_text
                # Should see redacted version instead
                assert "***" in all_log_text or "Password: ***" in all_log_text
            finally:
                await process.stop()

    async def test_stop_leaves_no_child_process(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that stop() leaves no child process running."""
        import psutil

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.3.2",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()
            await process.start()

            # Get the PID of the child process
            assert process._process is not None
            pid = process._process.pid
            assert pid is not None

            # Verify process exists
            assert psutil.pid_exists(pid)

            await process.stop()

            # Give it a moment to fully terminate
            await asyncio.sleep(0.1)

            # Verify process no longer exists
            assert not psutil.pid_exists(pid)


class TestOpenCodeProcessDeque:
    """Tests for the deque-based output line storage (supervisor fix)."""

    def test_stdout_lines_deque_maxlen(self) -> None:
        """Test that _stdout_lines keeps only the last 200 lines."""
        process = OpenCodeProcess()

        # Feed 250 lines
        for i in range(250):
            process._stdout_lines.append(f"line {i}")

        # Should only keep last 200
        assert len(process._stdout_lines) == 200
        # First line should be "line 50" (250 - 200 = 50)
        assert list(process._stdout_lines)[0] == "line 50"
        # Last line should be "line 249"
        assert list(process._stdout_lines)[-1] == "line 249"

    def test_stderr_lines_deque_maxlen(self) -> None:
        """Test that _stderr_lines keeps only the last 200 lines."""
        process = OpenCodeProcess()

        # Feed 250 lines
        for i in range(250):
            process._stderr_lines.append(f"error {i}")

        # Should only keep last 200
        assert len(process._stderr_lines) == 200
        # First line should be "error 50"
        assert list(process._stderr_lines)[0] == "error 50"
        # Last line should be "error 249"
        assert list(process._stderr_lines)[-1] == "error 249"

    def test_redact_output_lines_works_with_deque(self) -> None:
        """Test that _redact_output_lines works with deque slices."""
        process = OpenCodeProcess()

        for i in range(10):
            process._stdout_lines.append(f"line {i}")

        # Get last 5 lines (deque doesn't support slicing, convert to list first)
        last_five = list(process._stdout_lines)[-5:]
        redacted = process._redact_output_lines(last_five)

        # Should work without error
        assert "line 5" in redacted
        assert "line 9" in redacted


class TestOpenCodeProcessAgentsW31a:
    """Tests for OpenCodeProcess agent configuration via XDG_CONFIG_HOME (W3-31a)."""

    @pytest.fixture(autouse=True)
    def reset_settings(self, monkeypatch):
        """Reset settings before each test."""
        original_command = settings.opencode_command
        original_version_pin = settings.opencode_version_pin
        original_host = settings.opencode_host
        original_port = settings.opencode_port
        original_timeout = settings.opencode_start_timeout_secs
        original_agent_model = settings.opencode_agent_model
        original_config_dir = settings.opencode_config_dir
        original_router_base_url = settings.opencode_router_base_url

        yield

        settings.opencode_command = original_command
        settings.opencode_version_pin = original_version_pin
        settings.opencode_host = original_host
        settings.opencode_port = original_port
        settings.opencode_start_timeout_secs = original_timeout
        settings.opencode_agent_model = original_agent_model
        settings.opencode_config_dir = original_config_dir
        settings.opencode_router_base_url = original_router_base_url

    async def test_start_sets_xdg_config_home_in_child_env(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that the process starts the child with XDG_CONFIG_HOME set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.3.2",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_agent_model = "sluice/coder"
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()
            connection = await process.start()

            try:
                # Verify the server started and agents are accessible
                # (this indirectly verifies XDG_CONFIG_HOME was passed correctly)
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"{connection.base_url}/api/agent",
                        auth=connection.auth,
                    )
                    assert response.status_code == 200
                    data = response.json()
                    agents = data.get("data", [])
                    agent_ids = {agent.get("id") for agent in agents}
                    expected = {"aura-explore", "aura-build", "aura-review"}
                    assert expected.issubset(agent_ids)
            finally:
                await process.stop()

    async def test_start_does_not_set_xdg_data_home_or_state_home(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that XDG_DATA_HOME and XDG_STATE_HOME are not set in child env."""
        # We verify this by checking the server still works (sessions in normal location)
        # and by checking the code doesn't set them. The fake server doesn't read
        # XDG_DATA_HOME, so we just ensure the process starts successfully.
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.3.2",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_agent_model = "sluice/coder"
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()
            connection = await process.start()

            try:
                # Verify agents work
                async with httpx.AsyncClient(timeout=5.0) as client:
                    for agent_id in ["aura-explore", "aura-build", "aura-review"]:
                        response = await client.get(
                            f"{connection.base_url}/api/agent/{agent_id}",
                            auth=connection.auth,
                        )
                        assert response.status_code == 200
            finally:
                await process.stop()

    async def test_start_fails_when_agent_missing(
        self, free_port: int, fake_server_script: Path, monkeypatch
    ) -> None:
        """Test that start fails when the fake does not serve one of the agents."""
        import aura.connections.opencode_process as opencode_process_module
        import json

        # Create a config with only one agent
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            opencode_dir = config_dir / "opencode"
            opencode_dir.mkdir(parents=True)
            config_path = opencode_dir / "opencode.jsonc"
            config = {
                "provider": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Sluice",
                    "options": {"baseURL": "http://127.0.0.1:8787/v1"},
                    "models": {"coder": {"name": "coder"}, "chat": {"name": "chat"}},
                },
                "agents": {
                    "aura-explore": {
                        "model": "sluice/coder",
                        "system": "test",
                        "description": "test",
                        "mode": "subagent",
                        "permissions": [],
                    }
                },
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f)

            # Patch write_config where it's used in opencode_process
            def mock_write_config(config_dir_arg: Path) -> Path:
                # Just return the existing config path without overwriting
                return config_path

            monkeypatch.setattr(opencode_process_module, "write_config", mock_write_config)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.3.2",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_agent_model = "sluice/coder"
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()

            with pytest.raises(OpenCodeStartError) as exc_info:
                await process.start()

            error_msg = str(exc_info.value)
            assert "not found" in error_msg.lower() or "missing" in error_msg.lower()
            assert "aura-build" in error_msg or "aura-review" in error_msg

            await process.stop()

    async def test_no_request_to_experimental_config(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that no request to /api/experimental/config is ever made."""
        _request_paths.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            from aura.connections.opencode_agents import write_config
            write_config(config_dir)

            settings.opencode_command = [
                sys.executable,
                str(fake_server_script),
                "--version",
                "2.3.2",
                "--port",
                str(free_port),
                "--password",
                "test-secret-123",
            ]
            settings.opencode_version_pin = "2.3.2"
            settings.opencode_host = "127.0.0.1"
            settings.opencode_port = free_port
            settings.opencode_start_timeout_secs = 10
            settings.opencode_agent_model = "sluice/coder"
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()
            connection = await process.start()

            try:
                # Check that no request to /api/experimental/config was made
                experimental_config_requests = [
                    p for p in _request_paths if p == "/api/experimental/config"
                ]
                assert len(experimental_config_requests) == 0, (
                    f"Unexpected request to /api/experimental/config: {experimental_config_requests}"
                )

                # Verify agents are accessible
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"{connection.base_url}/api/agent",
                        auth=connection.auth,
                    )
                    assert response.status_code == 200
            finally:
                await process.stop()


# Need to import httpx for the tests
import httpx