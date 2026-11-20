"""
OpenCode Client - the only code that talks to OpenCode.

Implements the PRD 4.2 interface against the OpenCode HTTP API v2.3.2.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Union

import httpx

from aura.connections.opencode_process import OpenCodeConnection, OpenCodeProcess
from aura.models.work import PermissionRequest, WorkEvent, WorkResult

logger = logging.getLogger(__name__)


class OpenCodeUnavailable(RuntimeError):
    """Raised when OpenCode server is unavailable (connection failure or server exit)."""

    pass


class OpenCodeError(RuntimeError):
    """Raised when OpenCode returns an HTTP error."""

    def __init__(self, status: int, tag: str, message: str) -> None:
        self.status = status
        self.tag = tag
        self.message = message
        super().__init__(f"OpenCode error {status}: {tag} - {message}")


# Module-level list of all (method, path template) pairs the client uses.
# Used by test_opencode_spec_coverage.py to verify against the OpenAPI spec.
OPENCODE_CLIENT_ENDPOINTS: list[tuple[str, str]] = [
    ("POST", "/api/session"),
    ("POST", "/api/session/{sessionID}/prompt"),
    ("GET", "/api/event"),
    ("GET", "/api/session/{sessionID}/permission"),
    ("POST", "/api/session/{sessionID}/permission/{requestID}/reply"),
    ("POST", "/api/session/{sessionID}/interrupt"),
    ("GET", "/api/session/{sessionID}/diff"),
    ("GET", "/api/session/{sessionID}/message"),
]


@dataclass
class _SessionInfo:
    """Internal session info from the API."""

    id: str
    title: str | None = None


class OpenCodeClient:
    """
    Client for interacting with an OpenCode server.

    Can be initialized with either an OpenCodeProcess (managed) or a base URL + auth (external).
    """

    def __init__(
        self,
        process_or_base_url: Union[OpenCodeProcess, str],
        auth: Optional[httpx.BasicAuth] = None,
    ) -> None:
        """
        Initialize the client.

        Args:
            process_or_base_url: Either an OpenCodeProcess instance (managed) or a base URL string (external).
            auth: Basic auth for external server. Required if process_or_base_url is a string.
        """
        if isinstance(process_or_base_url, OpenCodeProcess):
            self._process: Optional[OpenCodeProcess] = process_or_base_url
            self._base_url: Optional[str] = None
            self._auth: Optional[httpx.BasicAuth] = None
            self._external = False
        else:
            self._process = None
            self._base_url = process_or_base_url.rstrip("/")
            self._auth = auth
            self._external = True

        self._client: Optional[httpx.AsyncClient] = None
        self._events_task: Optional[asyncio.Task] = None
        self._events_queue: asyncio.Queue[WorkEvent] = asyncio.Queue()
        _active_sessions: set[str] = set()

    @property
    def _connection(self) -> OpenCodeConnection:
        """Get the connection details, starting the process if needed."""
        if self._external:
            if self._base_url is None or self._auth is None:
                raise OpenCodeUnavailable("External client not configured with base_url and auth")
            return OpenCodeConnection(
                base_url=self._base_url,
                auth=self._auth,
                version="external",
            )
        else:
            if self._process is None:
                raise OpenCodeUnavailable("No managed process available")
            if self._process.connection is None:
                raise OpenCodeUnavailable("Managed process not started")
            return self._process.connection

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            conn = self._connection
            self._client = httpx.AsyncClient(
                base_url=conn.base_url,
                auth=conn.auth,
                timeout=30.0,
            )
        return self._client

    async def ensure_running(self) -> OpenCodeConnection:
        """
        Ensure the managed OpenCode process is running.

        Returns:
            The connection details.

        Raises:
            OpenCodeUnavailable: If the process cannot be started.
        """
        if self._external:
            # For external, just verify we can connect
            client = await self._get_client()
            try:
                await client.get("/api/info")
            except httpx.ConnectError as e:
                raise OpenCodeUnavailable(f"Cannot connect to OpenCode server: {e}") from e
            return self._connection

        if self._process is None:
            raise OpenCodeUnavailable("No managed process configured")

        if not self._process.is_running:
            try:
                return await self._process.start()
            except Exception as e:
                raise OpenCodeUnavailable(f"Failed to start OpenCode process: {e}") from e

        return self._process.connection

    async def create_session(
        self,
        workspace: Path,
        agent: str,
        title: str,
    ) -> str:
        """
        Create a new OpenCode session.

        Args:
            workspace: The workspace directory to bind the session to.
            agent: The agent ID to use.
            title: The session title.

        Returns:
            The session ID.

        Raises:
            OpenCodeUnavailable: If the server is unavailable.
            OpenCodeError: If the API returns an error.
        """
        await self.ensure_running()
        client = await self._get_client()

        # Build the location object with the workspace directory
        location = {"directory": str(workspace.absolute())}

        payload = {
            "agent": agent,
            "title": title,
            "location": location,
        }

        try:
            response = await client.post("/api/session", json=payload)
        except httpx.ConnectError as e:
            raise OpenCodeUnavailable(f"Connection failed: {e}") from e

        if response.status_code >= 400:
            await self._handle_error(response)

        data = response.json()
        session_data = data.get("data", {})
        session_id = session_data.get("id")
        if not session_id:
            raise OpenCodeError(response.status_code, "InvalidResponse", "No session ID in response")

        return session_id

    async def send(self, session_id: str, prompt: str) -> None:
        """
        Send a prompt to a session.

        Args:
            session_id: The session ID.
            prompt: The prompt text to send.

        Raises:
            OpenCodeUnavailable: If the server is unavailable.
            OpenCodeError: If the API returns an error.
        """
        await self.ensure_running()
        client = await self._get_client()

        payload = {"text": prompt}

        try:
            response = await client.post(f"/api/session/{session_id}/prompt", json=payload)
        except httpx.ConnectError as e:
            raise OpenCodeUnavailable(f"Connection failed: {e}") from e

        if response.status_code >= 400:
            await self._handle_error(response)

    async def events(self, session_id: str) -> AsyncIterator[WorkEvent]:
        """
        Stream events for a session.

        Args:
            session_id: The session ID to filter events for.

        Yields:
            WorkEvent objects for the specified session.

        Raises:
            OpenCodeUnavailable: If the stream breaks or server is unavailable.
        """
        await self.ensure_running()
        client = await self._get_client()

        # Request the SSE stream
        try:
            async with client.stream("GET", "/api/event", params={"follow": "true"}) as response:
                if response.status_code >= 400:
                    await self._handle_error(response)

                # Parse SSE format: event: <type>\ndata: <json>\n\n
                event_type = None
                event_data = None

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        event_data = line[5:].strip()

                        if event_type and event_data:
                            try:
                                # The data field is a JSON-encoded string per V2EventEncoded
                                event_json = json.loads(event_data)
                                # Parse the inner JSON string
                                if isinstance(event_json, str):
                                    inner_event = json.loads(event_json)
                                else:
                                    inner_event = event_json

                                # Filter by session_id
                                if self._event_matches_session(inner_event, session_id):
                                    work_event = self._parse_event(inner_event, session_id)
                                    if work_event:
                                        yield work_event
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse event data: {event_data}")

                            event_type = None
                            event_data = None

        except httpx.ConnectError as e:
            raise OpenCodeUnavailable(f"Event stream connection failed: {e}") from e
        except asyncio.CancelledError:
            raise
        except Exception as e:
            raise OpenCodeUnavailable(f"Event stream error: {e}") from e

    def _event_matches_session(self, event: dict, session_id: str) -> bool:
        """Check if an event matches the given session ID."""
        # Events have a sessionID field in their data
        data = event.get("data", {})
        return data.get("sessionID") == session_id

    def _parse_event(self, event: dict, session_id: str) -> WorkEvent | None:
        """Parse a raw event into a WorkEvent."""
        event_type = event.get("type", "")
        data = event.get("data", {})

        # Map OpenCode event types to our kind categories
        kind = self._map_event_kind(event_type)

        return WorkEvent(
            kind=kind,
            session_id=session_id,
            type=event_type,
            data=data,
        )

    def _map_event_kind(self, event_type: str) -> str:
        """Map OpenCode event type to WorkEvent kind."""
        if event_type.startswith("session.execution.started"):
            return "started"
        elif event_type.startswith("session.step."):
            return "step"
        elif event_type.startswith("session.tool."):
            return "tool"
        elif event_type.startswith("permission."):
            return "permission"
        elif event_type == "session.execution.succeeded":
            return "succeeded"
        elif event_type == "session.execution.failed":
            return "failed"
        elif event_type == "session.execution.interrupted":
            return "interrupted"
        elif event_type == "session.idle":
            return "idle"
        else:
            return "other"

    async def pending_permissions(self, session_id: str) -> list[PermissionRequest]:
        """
        Get pending permission requests for a session.

        Args:
            session_id: The session ID.

        Returns:
            List of pending permission requests.

        Raises:
            OpenCodeUnavailable: If the server is unavailable.
            OpenCodeError: If the API returns an error.
        """
        await self.ensure_running()
        client = await self._get_client()

        try:
            response = await client.get(f"/api/session/{session_id}/permission")
        except httpx.ConnectError as e:
            raise OpenCodeUnavailable(f"Connection failed: {e}") from e

        if response.status_code >= 400:
            await self._handle_error(response)

        data = response.json()
        permissions = data.get("data", [])

        result = []
        for perm in permissions:
            p_data = perm.get("data", {})
            result.append(
                PermissionRequest(
                    id=p_data.get("id", ""),
                    session_id=p_data.get("sessionID", session_id),
                    action=p_data.get("action", ""),
                    resources=p_data.get("resources", []),
                    message=p_data.get("message", ""),
                )
            )

        return result

    async def answer_permission(
        self,
        session_id: str,
        request_id: str,
        allow: bool,
    ) -> None:
        """
        Answer a permission request.

        Args:
            session_id: The session ID.
            request_id: The permission request ID.
            allow: Whether to allow the permission.

        Raises:
            OpenCodeUnavailable: If the server is unavailable.
            OpenCodeError: If the API returns an error.
        """
        await self.ensure_running()
        client = await self._get_client()

        decision = "always" if allow else "reject"
        payload = {"decision": decision}

        try:
            response = await client.post(
                f"/api/session/{session_id}/permission/{request_id}/reply",
                json=payload,
            )
        except httpx.ConnectError as e:
            raise OpenCodeUnavailable(f"Connection failed: {e}") from e

        if response.status_code >= 400:
            await self._handle_error(response)

    async def abort(self, session_id: str) -> None:
        """
        Interrupt a session.

        Args:
            session_id: The session ID.

        Raises:
            OpenCodeUnavailable: If the server is unavailable.
            OpenCodeError: If the API returns an error.
        """
        await self.ensure_running()
        client = await self._get_client()

        try:
            response = await client.post(f"/api/session/{session_id}/interrupt", json={})
        except httpx.ConnectError as e:
            raise OpenCodeUnavailable(f"Connection failed: {e}") from e

        if response.status_code >= 400:
            await self._handle_error(response)

    async def result(self, session_id: str) -> WorkResult:
        """
        Get the result of a completed session.

        Args:
            session_id: The session ID.

        Returns:
            WorkResult with summary, files changed, additions, and deletions.

        Raises:
            OpenCodeUnavailable: If the server is unavailable.
            OpenCodeError: If the API returns an error.
        """
        await self.ensure_running()
        client = await self._get_client()

        # Get the diff to compute file changes
        try:
            diff_response = await client.get(f"/api/session/{session_id}/diff")
        except httpx.ConnectError as e:
            raise OpenCodeUnavailable(f"Connection failed: {e}") from e

        if diff_response.status_code >= 400:
            await self._handle_error(diff_response)

        diff_data = diff_response.json()
        diffs = diff_data.get("data", [])

        files_changed = []
        additions = 0
        deletions = 0

        for diff in diffs:
            file_path = diff.get("path", "")
            if file_path:
                files_changed.append(file_path)

            for hunk in diff.get("hunks", []):
                for line in hunk.get("lines", []):
                    if line.get("type") == "add":
                        additions += 1
                    elif line.get("type") == "remove":
                        deletions += 1

        # Get the last assistant message for summary
        try:
            msg_response = await client.get(
                f"/api/session/{session_id}/message",
                params={"limit": "1", "order": "desc", "type": "assistant"},
            )
        except httpx.ConnectError as e:
            raise OpenCodeUnavailable(f"Connection failed: {e}") from e

        summary = ""
        if msg_response.status_code == 200:
            msg_data = msg_response.json()
            messages = msg_data.get("data", [])
            if messages:
                content = messages[0].get("content", "")
                # Truncate summary to reasonable length
                summary = content[:500] + ("..." if len(content) > 500 else "")

        return WorkResult(
            session_id=session_id,
            summary=summary,
            files_changed=files_changed,
            additions=additions,
            deletions=deletions,
        )

    async def _handle_error(self, response: httpx.Response) -> None:
        """Handle an error response from the API."""
        try:
            error_data = response.json()
            # OpenCode errors have _tag and message fields
            tag = error_data.get("_tag", "UnknownError")
            message = error_data.get("message", "Unknown error")
        except Exception:
            tag = "UnknownError"
            message = response.text or "Unknown error"

        raise OpenCodeError(response.status_code, tag, message)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> OpenCodeClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()