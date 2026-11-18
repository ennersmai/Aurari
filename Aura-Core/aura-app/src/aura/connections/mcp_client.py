"""
MCP Client integration for Aura.

Supports connecting to MCP servers over:
- stdio (local subprocess)
- streamable HTTP (remote)

Uses the official `mcp` Python SDK when available.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

MCPTransport = Literal["stdio", "streamable_http", "sse"]


class MCPClientError(RuntimeError):
    pass


class MCPServerOfflineError(MCPClientError):
    pass


class MCPConnectionTimeoutError(MCPClientError):
    pass


def _require_mcp_sdk() -> None:
    try:
        import mcp  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise MCPClientError(
            "MCP Python SDK not installed. Install with `pip install mcp`."
        ) from e


def _default_timeout_s(config: dict[str, Any]) -> float:
    try:
        return float(config.get("timeout_s", 15))
    except Exception:
        return 15.0


def _format_call_tool_result(call_result: Any) -> tuple[bool, str]:
    """
    Convert an MCP CallToolResult to a dense string response for Aura.
    Returns (success, text).
    """
    # The SDK provides `CallToolResult` with:
    # - isError: bool
    # - content: list[ContentBlock] (TextContent, ImageContent, EmbeddedResource...)
    # - structuredContent: dict | None
    is_error = bool(getattr(call_result, "isError", False))

    structured = getattr(call_result, "structuredContent", None)

    content = getattr(call_result, "content", None) or []
    parts: list[str] = []
    for block in content:
        # Most servers return TextContent blocks.
        if hasattr(block, "text"):
            parts.append(str(getattr(block, "text")))
            continue

        # ImageContent: include metadata only (avoid huge base64 blobs).
        if hasattr(block, "mimeType") and hasattr(block, "data"):
            mime = getattr(block, "mimeType", None)
            data = getattr(block, "data", None)
            data_len = len(data) if isinstance(data, (bytes, str)) else None
            parts.append(f"[image mimeType={mime or 'unknown'} bytes={data_len if data_len is not None else 'unknown'}]")
            continue

        # EmbeddedResource: try to surface URI + text preview if present.
        if hasattr(block, "resource"):
            try:
                res = getattr(block, "resource", None)
                uri = getattr(res, "uri", None)
                if hasattr(res, "text"):
                    txt = str(getattr(res, "text") or "")
                    parts.append(f"[resource {uri}]")
                    if txt:
                        parts.append(txt)
                elif hasattr(res, "blob"):
                    blob = getattr(res, "blob", None)
                    blob_len = len(blob) if isinstance(blob, (bytes, str)) else None
                    parts.append(f"[resource {uri} blob bytes={blob_len if blob_len is not None else 'unknown'}]")
                else:
                    parts.append(f"[resource {uri}]")
                continue
            except Exception:
                pass

        # Fallback: include type tag if present.
        if hasattr(block, "type"):
            parts.append(f"[{getattr(block, 'type')}]")
        else:
            parts.append(str(block))

    text = "\n".join([p for p in parts if p])

    # If structured content exists, include it in a compact, L3-consumable way.
    if structured is not None:
        try:
            import json

            payload: dict[str, Any] = {"structured": structured}
            if text:
                payload["content_text"] = text
            return (not is_error), json.dumps(payload, ensure_ascii=False)
        except Exception:
            # If JSON serialization fails, fall back to text.
            if text:
                return (not is_error), text

    if not text:
        text = "" if not is_error else "MCP tool returned an error with no content."
    return (not is_error), text


@dataclass(frozen=True)
class MCPConnectionConfig:
    transport: MCPTransport
    # stdio fields
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    # http fields
    url: str | None = None
    # common
    timeout_s: float = 15.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPConnectionConfig":
        transport = str(data.get("transport") or data.get("type") or "").strip()
        if not transport:
            transport = "stdio"
        if transport not in ("stdio", "streamable_http", "sse"):
            raise ValueError(f"Unsupported MCP transport: {transport}")

        timeout_s = _default_timeout_s(data)
        return cls(
            transport=transport,  # type: ignore[arg-type]
            command=data.get("command"),
            args=list(data.get("args") or []) if data.get("args") is not None else None,
            env=dict(data.get("env") or {}) if data.get("env") is not None else None,
            url=data.get("url"),
            timeout_s=timeout_s,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args or []),
            "env": dict(self.env or {}),
            "url": self.url,
            "timeout_s": self.timeout_s,
        }


class MCPClient:
    """
    Thin wrapper over `mcp.ClientSession` with persistent connection lifecycle.
    """

    def __init__(self, server_name: str, config: MCPConnectionConfig):
        self.server_name = server_name
        self.config = config
        self._stack: AsyncExitStack | None = None
        self._session: Any | None = None
        self._connected: bool = False
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def connect(self) -> None:
        async with self._lock:
            if self.is_connected:
                return

            _require_mcp_sdk()

            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
                from mcp.client.streamable_http import streamable_http_client

                stack = AsyncExitStack()
                self._stack = stack

                if self.config.transport == "stdio":
                    if not self.config.command:
                        raise MCPClientError("Missing `command` for stdio MCP transport.")
                    params = StdioServerParameters(
                        command=self.config.command,
                        args=list(self.config.args or []),
                        env=self.config.env,
                    )
                    read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
                else:
                    if not self.config.url:
                        raise MCPClientError("Missing `url` for HTTP MCP transport.")
                    # SSE transport is supported by the SDK but is being superseded.
                    # For Aura, prefer streamable HTTP; SSE will be treated as HTTP unless
                    # a dedicated sse client is available.
                    if self.config.transport == "sse":
                        try:
                            from mcp.client.sse import sse_client  # type: ignore

                            read_stream, write_stream = await stack.enter_async_context(
                                sse_client(self.config.url)
                            )
                        except Exception:
                            read_stream, write_stream, _ = await stack.enter_async_context(
                                streamable_http_client(self.config.url)
                            )
                    else:
                        read_stream, write_stream, _ = await stack.enter_async_context(
                            streamable_http_client(self.config.url)
                        )

                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await asyncio.wait_for(session.initialize(), timeout=self.config.timeout_s)

                self._session = session
                self._connected = True
                self._last_error = None
                logger.info("✅ MCP connected: server=%s transport=%s", self.server_name, self.config.transport)

            except asyncio.TimeoutError as e:
                self._last_error = "Connection timed out"
                await self.close()
                raise MCPConnectionTimeoutError(
                    f"MCP connection timed out (server={self.server_name})"
                ) from e
            except Exception as e:
                self._last_error = str(e)
                await self.close()
                raise MCPClientError(f"Failed to connect to MCP server '{self.server_name}': {e}") from e

    async def close(self) -> None:
        async with self._lock:
            self._connected = False
            self._session = None
            if self._stack:
                try:
                    await self._stack.aclose()
                finally:
                    self._stack = None

    async def discover_tools(self) -> list[dict[str, Any]]:
        await self.connect()
        assert self._session is not None
        try:
            result = await asyncio.wait_for(self._session.list_tools(), timeout=self.config.timeout_s)
            tools = getattr(result, "tools", None) or []
            out: list[dict[str, Any]] = []
            for t in tools:
                out.append(
                    {
                        "name": getattr(t, "name", ""),
                        "description": getattr(t, "description", "") or "",
                        "inputSchema": getattr(t, "inputSchema", None) or {},
                        "raw": t,
                    }
                )
            return out
        except asyncio.TimeoutError as e:
            raise MCPConnectionTimeoutError(
                f"MCP tools discovery timed out (server={self.server_name})"
            ) from e
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            raise MCPServerOfflineError(
                f"MCP tools discovery failed (server={self.server_name}): {e}"
            ) from e

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        await self.connect()
        assert self._session is not None
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments=arguments),
                timeout=self.config.timeout_s,
            )
            return _format_call_tool_result(result)
        except asyncio.TimeoutError as e:
            raise MCPConnectionTimeoutError(
                f"MCP tool call timed out (server={self.server_name}, tool={tool_name})"
            ) from e
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            raise MCPServerOfflineError(
                f"MCP tool call failed (server={self.server_name}, tool={tool_name}): {e}"
            ) from e


class MCPConnectionManager:
    """
    Process-wide registry of active MCP connections.
    """

    def __init__(self) -> None:
        self._connections: dict[str, MCPClient] = {}
        self._configs: dict[str, MCPConnectionConfig] = {}
        self._lock = asyncio.Lock()

    async def connect(self, server_name: str, config_dict: dict[str, Any]) -> MCPClient:
        config = MCPConnectionConfig.from_dict(config_dict)
        async with self._lock:
            existing = self._connections.get(server_name)
            if existing and existing.is_connected:
                return existing

            client = existing or MCPClient(server_name=server_name, config=config)
            # Store config for reconnects (even if connect fails).
            self._configs[server_name] = config
            self._connections[server_name] = client

        await client.connect()
        return client

    def get(self, server_name: str) -> MCPClient | None:
        return self._connections.get(server_name)

    def get_config(self, server_name: str) -> MCPConnectionConfig | None:
        return self._configs.get(server_name)

    async def disconnect(self, server_name: str) -> None:
        async with self._lock:
            client = self._connections.get(server_name)
        if client:
            await client.close()

    def list_servers(self) -> list[str]:
        return sorted(self._connections.keys())


_GLOBAL_MCP_MANAGER: MCPConnectionManager | None = None
_GLOBAL_MCP_MANAGER_LOCK = asyncio.Lock()


async def get_mcp_connection_manager() -> MCPConnectionManager:
    global _GLOBAL_MCP_MANAGER
    async with _GLOBAL_MCP_MANAGER_LOCK:
        if _GLOBAL_MCP_MANAGER is None:
            _GLOBAL_MCP_MANAGER = MCPConnectionManager()
        return _GLOBAL_MCP_MANAGER


