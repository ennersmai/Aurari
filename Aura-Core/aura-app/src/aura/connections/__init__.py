"""
External connection clients (MCP, etc.).
"""

from aura.connections.opencode_client import (
    OPENCODE_CLIENT_ENDPOINTS,
    OpenCodeClient,
    OpenCodeError,
    OpenCodeUnavailable,
)

__all__ = [
    "OpenCodeClient",
    "OpenCodeError",
    "OpenCodeUnavailable",
    "OPENCODE_CLIENT_ENDPOINTS",
]


