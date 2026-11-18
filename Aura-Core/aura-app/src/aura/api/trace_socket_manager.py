"""
Lightweight WebSocket manager for cognitive trace streaming.

Provides a pub/sub mechanism so the Orchestrator can push
lightweight L1/L2/L3 trace events to all connected telemetry clients
without coupling to any specific WebSocket implementation.
"""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("aura.trace_socket_manager")


class TraceSocketManager:
    """Manages active WebSocket connections for /v1/stream/traces."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new client."""
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        logger.debug("Trace client connected (%d total)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a client."""
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        logger.debug("Trace client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """
        Push a trace event to all connected clients (fire-and-forget).

        Dead sockets are silently pruned on failure.
        """
        if not self._connections:
            return

        async with self._lock:
            sockets = list(self._connections)

        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    if ws in self._connections:
                        self._connections.remove(ws)


# ---------------------------------------------------------------------------
# Module-level singleton — safe to import anywhere in the process
# ---------------------------------------------------------------------------

_manager: TraceSocketManager | None = None


def get_trace_manager() -> TraceSocketManager:
    """Return the process-wide TraceSocketManager instance."""
    global _manager
    if _manager is None:
        _manager = TraceSocketManager()
    return _manager
