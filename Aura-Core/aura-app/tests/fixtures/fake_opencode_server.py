#!/usr/bin/env python3
"""
Fake OpenCode server for testing.

This is a standalone script (standard library only: http.server and threading)
that prints the two lines (URL and password) and serves /api/info behind
Basic auth, with the version taken from a command-line argument.

Extended for W3-31 to also support:
- PATCH /api/experimental/config for agent configuration
- GET /api/agent for agent listing

Usage:
    python tests/fixtures/fake_opencode_server.py --version 2.3.2
    python tests/fixtures/fake_opencode_server.py --version 3.0.0 --exit-immediately
    python tests/fixtures/fake_opencode_server.py --version 2.3.2 --agents '{"aura-explore": {...}}'
    python tests/fixtures/fake_opencode_server.py --version 2.3.2 --reject-patch
"""

import argparse
import base64
import http.server
import json
import sys
import threading
import time
from http import HTTPStatus
from typing import Any, ClassVar


# Track request paths for verification in tests
_request_paths: list[str] = []


def record_request(path: str) -> None:
    """Record a request path for test verification."""
    _request_paths.append(path)


# Global agent store (configured via PATCH /api/experimental/config)
_configured_agents: dict[str, dict[str, Any]] = {}
# Flag to reject PATCH requests
_reject_patch: bool = False


def set_configured_agents(agents: dict[str, dict[str, Any]]) -> None:
    """Set the configured agents for testing."""
    global _configured_agents
    _configured_agents = agents


def get_configured_agents() -> dict[str, dict[str, Any]]:
    """Get the currently configured agents."""
    return _configured_agents


def set_reject_patch(reject: bool) -> None:
    """Set whether to reject PATCH requests."""
    global _reject_patch
    _reject_patch = reject


class FakeOpenCodeHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for the fake OpenCode server."""

    version: ClassVar[str] = "2.3.2"

    def do_GET(self) -> None:
        """Handle GET requests."""
        record_request(self.path)

        # Check Basic auth
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="opencode"')
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        # Verify credentials (username "opencode", password from stdout)
        try:
            encoded = auth_header[6:]  # Remove "Basic "
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":", 1)
            if username != "opencode" or password != self.server.password:  # type: ignore[attr-defined]
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.end_headers()
                self.wfile.write(b"Invalid credentials")
                return
        except Exception:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.end_headers()
            self.wfile.write(b"Invalid auth format")
            return

        # Handle /api/info
        if self.path == "/api/info":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "version": self.version,
                "name": "opencode",
            }
            self.wfile.write(json.dumps(response).encode("utf-8"))
        # Handle GET /api/agent
        elif self.path == "/api/agent":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            agents = get_configured_agents()
            # Format as Agent.Info objects
            agent_list = []
            for agent_id, agent_def in agents.items():
                agent_list.append({
                    "id": agent_id,
                    "name": agent_def.get("description", agent_id),
                    "model": agent_def.get("model", ""),
                    "system": agent_def.get("system", ""),
                    "description": agent_def.get("description", ""),
                    "mode": agent_def.get("mode", "primary"),
                    "hidden": False,
                    "color": "#000000",
                    "steps": 0,
                    "permissions": agent_def.get("permissions", []),
                })
            response = {
                "location": {"directory": "/fake/workspace"},
                "data": agent_list,
            }
            self.wfile.write(json.dumps(response).encode("utf-8"))
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_PATCH(self) -> None:
        """Handle PATCH requests."""
        record_request(self.path)

        # Check Basic auth
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="opencode"')
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        # Verify credentials
        try:
            encoded = auth_header[6:]
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":", 1)
            if username != "opencode" or password != self.server.password:  # type: ignore[attr-defined]
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.end_headers()
                self.wfile.write(b"Invalid credentials")
                return
        except Exception:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.end_headers()
            self.wfile.write(b"Invalid auth format")
            return

        # Handle PATCH /api/experimental/config
        if self.path == "/api/experimental/config":
            if _reject_patch:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.end_headers()
                self.wfile.write(b"PATCH rejected for testing")
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(body)
                # Accept agents field in the patch
                if "agents" in payload:
                    set_configured_agents(payload["agents"])
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            except Exception:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.end_headers()
                self.wfile.write(b"Invalid JSON")
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            self.wfile.write(b"Not found")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default log messages."""
        pass


def run_server(
    host: str,
    port: int,
    version: str,
    password: str,
    exit_immediately: bool = False,
    exit_before_output: bool = False,
    agents_json: str | None = None,
    reject_patch: bool = False,
) -> None:
    """Run the fake OpenCode server."""
    FakeOpenCodeHandler.version = version

    # Pre-configure agents if provided
    if agents_json:
        try:
            set_configured_agents(json.loads(agents_json))
        except Exception:
            pass

    # Set reject patch flag
    set_reject_patch(reject_patch)

    server = http.server.HTTPServer((host, port), FakeOpenCodeHandler)
    server.password = password  # type: ignore[attr-defined]

    if exit_before_output:
        # Exit immediately before printing the lines (simulates a crash before output)
        sys.exit(0)

    # Print the two lines that OpenCodeProcess expects
    print(f"Listening on http://{host}:{port}")
    print(f"Password: {password}")
    sys.stdout.flush()

    if exit_immediately:
        # Exit immediately after printing the lines (simulates a crash)
        sys.exit(0)

    # Run the server in a thread
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake OpenCode server for testing")
    parser.add_argument(
        "--version",
        default="2.3.2",
        help="Version to report in /api/info (default: 2.3.2)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to bind to (0 = random free port, default: 0)",
    )
    parser.add_argument(
        "--password",
        default="test-password-123",
        help="Password to use for Basic auth (default: test-password-123)",
    )
    parser.add_argument(
        "--exit-immediately",
        action="store_true",
        help="Exit immediately after printing URL and password (simulates crash)",
    )
    parser.add_argument(
        "--exit-before-output",
        action="store_true",
        help="Exit immediately before printing URL and password (simulates crash before output)",
    )
    parser.add_argument(
        "--agents",
        type=str,
        default=None,
        help="JSON string of initial agents to configure",
    )
    parser.add_argument(
        "--reject-patch",
        action="store_true",
        help="Reject PATCH /api/experimental/config requests (for testing missing agents)",
    )
    # Ignore unknown arguments (like 'serve', '--hostname', etc. from OpenCodeProcess)
    args, _ = parser.parse_known_args()

    run_server(
        args.host,
        args.port,
        args.version,
        args.password,
        args.exit_immediately,
        args.exit_before_output,
        args.agents,
        args.reject_patch,
    )


if __name__ == "__main__":
    main()