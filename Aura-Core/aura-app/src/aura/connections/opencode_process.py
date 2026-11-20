"""
Managed OpenCode server process.

Starts `opencode serve` as a child process, reads the listening URL and password
from stdout, polls /api/info with Basic auth, and performs a major version check.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from typing import Any

import httpx

from aura.config import settings

logger = logging.getLogger(__name__)


class OpenCodeStartError(RuntimeError):
    """Raised when the OpenCode process fails to start or produce the expected output."""


class OpenCodeVersionError(RuntimeError):
    """Raised when the major version of the running OpenCode differs from the pinned major version."""


@dataclass(frozen=True)
class OpenCodeConnection:
    """Connection details for a running OpenCode server."""
    base_url: str
    auth: httpx.BasicAuth
    version: str


class OpenCodeProcess:
    """
    Manages an OpenCode server process.

    The process is started with `opencode serve --hostname <host> --port <port>`.
    The class reads stdout until it finds the listening URL and the generated password,
    then polls GET /api/info with Basic auth until it responds or the timeout expires.
    """

    # Regex patterns to extract the listening URL and password from opencode output
    _URL_PATTERN = re.compile(r"^\s*Listening on\s+(https?://\S+)\s*$")
    _PASSWORD_PATTERN = re.compile(r"^\s*Password:\s+(\S+)\s*$")

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._connection: OpenCodeConnection | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._stdout_lines: list[str] = []
        self._stderr_lines: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def connection(self) -> OpenCodeConnection | None:
        return self._connection

    def _get_command(self) -> list[str]:
        """Build the command to start opencode serve."""
        cmd = list(settings.opencode_command) if settings.opencode_command else ["opencode"]
        cmd += [
            "serve",
            "--hostname",
            settings.opencode_host,
            "--port",
            str(settings.opencode_port),
        ]
        return cmd

    async def start(self) -> OpenCodeConnection:
        """
        Start the OpenCode server process.

        Returns:
            OpenCodeConnection with base_url, auth, and version.

        Raises:
            OpenCodeStartError: If the process exits before printing URL and password,
                or if /api/info doesn't respond within the timeout.
            OpenCodeVersionError: If the major version from /api/info differs from the pinned major version.
        """
        if self.is_running:
            return self._connection

        cmd = self._get_command()
        # Log command with password redacted if present
        log_cmd = []
        skip_next = False
        for i, arg in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            if arg == "--password" and i + 1 < len(cmd):
                log_cmd.append("--password")
                log_cmd.append("***")
                skip_next = True
            else:
                log_cmd.append(arg)
        logger.info("Starting OpenCode server: %s", " ".join(log_cmd))

        # Start the process
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Read stdout line by line to capture the URL and password
        assert self._process.stdout is not None
        url: str | None = None
        password: str | None = None

        try:
            while True:
                line_bytes = await self._process.stdout.readline()
                if not line_bytes:
                    # EOF - process closed stdout
                    break

                line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
                self._stdout_lines.append(line)

                # Log with password redacted
                log_line = self._redact_password(line)
                logger.debug("opencode: %s", log_line)

                # Try to extract URL
                if url is None:
                    match = self._URL_PATTERN.match(line)
                    if match:
                        url = match.group(1)

                # Try to extract password
                if password is None:
                    match = self._PASSWORD_PATTERN.match(line)
                    if match:
                        password = match.group(1)

                # If we have both, we can stop reading stdout for now
                if url is not None and password is not None:
                    break

            # Check if we got both URL and password
            if url is None or password is None:
                # Process may have exited - wait for it to confirm
                await self._process.wait()
                raise OpenCodeStartError(
                    f"OpenCode process exited before printing URL and password. "
                    f"Last 20 lines:\n{self._redact_output_lines(self._stdout_lines[-20:])}"
                )

            # Parse the URL to get the actual host and port (in case port was 0)
            from urllib.parse import urlparse
            parsed = urlparse(url)
            actual_host = parsed.hostname or settings.opencode_host
            actual_port = parsed.port or settings.opencode_port
            base_url = f"http://{actual_host}:{actual_port}"

            # Create auth with the password
            auth = httpx.BasicAuth("opencode", password)

            # Poll /api/info until it responds or timeout
            version = await self._poll_api_info(base_url, auth)

            # Major version check
            pinned_major = self._parse_major(settings.opencode_version_pin)
            actual_major = self._parse_major(version)
            if pinned_major != actual_major:
                await self.stop()
                raise OpenCodeVersionError(
                    f"OpenCode major version mismatch: pinned={settings.opencode_version_pin} "
                    f"(major {pinned_major}), actual={version} (major {actual_major})"
                )

            # Minor/patch version warning
            if version != settings.opencode_version_pin:
                logger.warning(
                    "OpenCode version differs from pin: pinned=%s, actual=%s",
                    settings.opencode_version_pin,
                    version,
                )

            self._connection = OpenCodeConnection(
                base_url=base_url,
                auth=auth,
                version=version,
            )

            # Start a task to read remaining stdout/stderr in background
            self._start_task = asyncio.create_task(self._read_streams())

            logger.info("OpenCode server started: %s (version %s)", base_url, version)
            return self._connection

        except (OpenCodeStartError, OpenCodeVersionError):
            await self.stop()
            raise
        except Exception as e:
            await self.stop()
            raise OpenCodeStartError(f"Failed to start OpenCode server: {e}") from e

    async def _poll_api_info(self, base_url: str, auth: httpx.BasicAuth) -> str:
        """Poll GET /api/info until it responds or timeout."""
        url = f"{base_url}/api/info"
        timeout = settings.opencode_start_timeout_secs
        start_time = asyncio.get_event_loop().time()

        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                try:
                    response = await client.get(url, auth=auth)
                    if response.status_code == 200:
                        data = response.json()
                        version = data.get("version")
                        if version:
                            return str(version)
                except Exception:
                    pass  # Keep polling

                # Check timeout
                if asyncio.get_event_loop().time() - start_time >= timeout:
                    raise OpenCodeStartError(
                        f"OpenCode /api/info did not respond within {timeout} seconds"
                    )

                await asyncio.sleep(0.5)

    async def _read_streams(self) -> None:
        """Read remaining stdout and stderr in background."""
        if not self._process:
            return

        async def read_stream(stream: asyncio.StreamReader | None, name: str) -> None:
            if stream is None:
                return
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
                if name == "stdout":
                    self._stdout_lines.append(line)
                else:
                    self._stderr_lines.append(line)
                log_line = self._redact_password(line)
                logger.debug("opencode %s: %s", name, log_line)

        await asyncio.gather(
            read_stream(self._process.stdout, "stdout"),
            read_stream(self._process.stderr, "stderr"),
        )

    def _redact_password(self, line: str) -> str:
        """Redact password in log lines."""
        return self._PASSWORD_PATTERN.sub("Password: ***", line)

    def _redact_output_lines(self, lines: list[str]) -> str:
        """Redact passwords in a list of output lines."""
        return "\n".join(self._redact_password(line) for line in lines)

    def _parse_major(self, version: str) -> int:
        """Extract major version number from a version string."""
        try:
            return int(version.split(".")[0])
        except (ValueError, IndexError):
            return 0

    async def stop(self) -> None:
        """Stop the OpenCode server process."""
        if self._process is None:
            return

        logger.info("Stopping OpenCode server")
        try:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("OpenCode server did not terminate in 5s, killing")
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            pass  # Already gone
        finally:
            self._process = None
            self._connection = None

            if self._start_task:
                self._start_task.cancel()
                try:
                    await self._start_task
                except asyncio.CancelledError:
                    pass
                self._start_task = None