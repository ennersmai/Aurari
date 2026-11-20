#!/usr/bin/env python3
"""
Fake OpenCode server for testing.

This is a standalone script (standard library only: http.server and threading)
that prints the two lines (URL and password) and serves /api/info behind
Basic auth, with the version taken from a command-line argument.

Extended for W3-31a to read agents from XDG_CONFIG_HOME/opencode/opencode.jsonc
and serve GET /api/agent and GET /api/agent/{id}.

Usage:
    python tests/fixtures/fake_opencode_server.py --version 2.3.2
    python tests/fixtures/fake_opencode_server.py --version 3.0.0 --exit-immediately
    XDG_CONFIG_HOME=/path/to/config python tests/fixtures/fake_opencode_server.py --version 2.3.2
"""

import argparse
import base64
import http.server
import json
import os
import sys
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any, ClassVar


# Track request paths for verification in tests
_request_paths: list[str] = []


def record_request(path: str) -> None:
    """Record a request path for test verification."""
    _request_paths.append(path)


# Track request counts per agent for delayed readiness simulation
_agent_request_counts: dict[str, int] = {}


def record_agent_request(agent_id: str) -> int:
    """Record a request for a specific agent and return the count."""
    _agent_request_counts[agent_id] = _agent_request_counts.get(agent_id, 0) + 1
    return _agent_request_counts[agent_id]


def reset_agent_request_counts() -> None:
    """Reset the agent request counts."""
    _agent_request_counts.clear()


# Delay configuration: number of 404s to return before 200 for each agent
_agent_delay_ready: int = 0


def set_agent_delay_ready(delay: int) -> None:
    """Set the number of 404 responses before agents become ready."""
    global _agent_delay_ready
    _agent_delay_ready = delay


def get_agent_delay_ready() -> int:
    """Get the current agent delay ready setting."""
    return _agent_delay_ready


# Global agent store (loaded from XDG_CONFIG_HOME/opencode/opencode.jsonc)
_configured_agents: dict[str, dict[str, Any]] = {}


def load_agents_from_config_dir(config_dir: str | None) -> dict[str, dict[str, Any]]:
    """Load agents from <config_dir>/opencode/opencode.jsonc."""
    if not config_dir:
        return {}
    config_path = Path(config_dir) / "opencode" / "opencode.jsonc"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("agents", {})
    except Exception:
        return {}


def get_configured_agents() -> dict[str, dict[str, Any]]:
    """Get the currently configured agents."""
    return _configured_agents


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
        # Handle GET /api/agent/{id}
        elif self.path.startswith("/api/agent/"):
            agent_id = self.path.split("/api/agent/")[1]
            agents = get_configured_agents()
            if agent_id in agents:
                # Check if we should delay readiness for this agent
                delay = get_agent_delay_ready()
                if delay > 0:
                    count = record_agent_request(agent_id)
                    if count <= delay:
                        self.send_response(HTTPStatus.NOT_FOUND)
                        self.end_headers()
                        self.wfile.write(b"Agent not found")
                        return

                agent_def = agents[agent_id]
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {
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
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))
            else:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                self.wfile.write(b"Agent not found")
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
    delay_agent_ready: int = 0,
) -> None:
    """Run the fake OpenCode server."""
    FakeOpenCodeHandler.version = version

    # Set delay for agent readiness
    set_agent_delay_ready(delay_agent_ready)
    reset_agent_request_counts()

    # Load agents from XDG_CONFIG_HOME
    config_dir = os.environ.get("XDG_CONFIG_HOME")
    global _configured_agents
    _configured_agents = load_agents_from_config_dir(config_dir)

    server = http.server.HTTPServer((host, port), FakeOpenCodeHandler)
    server.password = password  # type: ignore[attr-defined]

    if exit_before_output:
        # Exit immediately before printing the lines (simulates a crash before output)
        sys.exit(0)

    # Print the two lines that OpenCodeProcess expects (matching real OpenCode v2.3.2 output)
    print(f"server listening on http://{host}:{port}")
    print(f"server password {password}")
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
        "--delay-agent-ready",
        type=int,
        default=0,
        help="Number of 404 responses to return for each agent before returning 200 (simulates async config loading)",
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
        args.delay_agent_ready,
    )


if __name__ == "__main__":
    main()