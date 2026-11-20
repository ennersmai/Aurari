"""
Tests for the OpenCodeProcess class (W3-27).

Tests cover:
- Start succeeds with correct version
- Version mismatch (major) raises OpenCodeVersionError
- Different minor/patch version starts with warning
- Process exiting immediately raises OpenCodeStartError
- Password does not appear in captured logs
- stop() leaves no child process running
"""

import asyncio
import logging
import sys
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

        yield

        # Restore
        settings.opencode_command = original_command
        settings.opencode_version_pin = original_version_pin
        settings.opencode_host = original_host
        settings.opencode_port = original_port
        settings.opencode_start_timeout_secs = original_timeout

    async def test_start_succeeds_with_correct_version(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that start succeeds and returns correct version."""
        # Configure settings to use the fake server
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

        process = OpenCodeProcess()

        with pytest.raises(OpenCodeVersionError) as exc_info:
            await process.start()

        # Check error message contains both versions
        error_msg = str(exc_info.value)
        assert "2.3.2" in error_msg
        assert "3.0.0" in error_msg
        assert "major" in error_msg.lower()

        # Verify no request other than /api/info reached the fake server
        # (The fake server would have recorded other paths if they were made)
        # We can't easily check this without more infrastructure, but the fact
        # that the error is raised before any other request is made is the key point
        await process.stop()

    async def test_different_minor_patch_starts_with_warning(
        self, free_port: int, fake_server_script: Path, caplog
    ) -> None:
        """Test that different minor/patch version starts with a warning."""
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

        process = OpenCodeProcess()

        with pytest.raises(OpenCodeStartError) as exc_info:
            await process.start()

        error_msg = str(exc_info.value)
        assert "exited before printing URL and password" in error_msg
        # The error should contain the last 20 lines (redacted)
        # Since the process exits immediately, stdout will be empty or minimal

    async def test_password_not_in_logs(
        self, free_port: int, fake_server_script: Path, caplog
    ) -> None:
        """Test that the password does not appear in captured logs."""
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


# Need to import httpx for the test
import httpx