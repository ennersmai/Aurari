#!/usr/bin/env python3
"""
Fake OpenCode server for testing.

This is a standalone script (standard library only: http.server and threading)
that prints the two lines (URL and password) and serves /api/info behind
Basic auth, with the version taken from a command-line argument.

Usage:
    python tests/fixtures/fake_opencode_server.py --version 2.3.2
    python tests/fixtures/fake_opencode_server.py --version 3.0.0 --exit-immediately
"""

import argparse
import base64
import http.server
import json
import sys
import threading
import time
from http import HTTPStatus
from typing import ClassVar

# Track request paths for verification in tests
_request_paths: list[str] = []


def record_request(path: str) -> None:
    """Record a request path for test verification."""
    _request_paths.append(path)


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
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            self.wfile.write(b"Not found")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default log messages."""
        pass


def run_server(host: str, port: int, version: str, password: str, exit_immediately: bool = False, exit_before_output: bool = False) -> None:
    """Run the fake OpenCode server."""
    FakeOpenCodeHandler.version = version

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
    # Ignore unknown arguments (like 'serve', '--hostname', etc. from OpenCodeProcess)
    args, _ = parser.parse_known_args()

    run_server(args.host, args.port, args.version, args.password, args.exit_immediately, args.exit_before_output)


if __name__ == "__main__":
    main()