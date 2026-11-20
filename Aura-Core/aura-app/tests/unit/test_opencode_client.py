"""
Tests for OpenCodeClient (W3-28).

Tests use httpx.MockTransport to simulate the OpenCode server.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import MagicMock

import httpx
import pytest

from aura.connections.opencode_client import (
    OPENCODE_CLIENT_ENDPOINTS,
    OpenCodeClient,
    OpenCodeError,
    OpenCodeUnavailable,
)
from aura.connections.opencode_process import OpenCodeConnection, OpenCodeProcess
from aura.models.work import PermissionRequest, WorkEvent, WorkResult


# Helper to create SSE content as bytes
def create_sse_content(events: list[dict]) -> bytes:
    """Create SSE-formatted content as bytes.

    The OpenCode server sends V2EventEncoded which is a JSON string containing
    the event. The client expects the SSE data field to be a JSON string that
    decodes to another JSON string (double-encoded).
    """
    lines = []
    for event in events:
        lines.append(f"event: {event['type']}")
        # The data field must be a JSON string that decodes to the event JSON
        inner_json = json.dumps(event, separators=(",", ":"))
        outer_json = json.dumps(inner_json)
        lines.append(f"data: {outer_json}")
        lines.append("")  # Empty line between events
    return "\n".join(lines).encode("utf-8")


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that records requests and returns predefined responses."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: dict[tuple[str, str], httpx.Response] = {}
        self.should_fail_connect = False
        self.fail_after_requests = 0
        self.request_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.request_count += 1

        if self.should_fail_connect:
            raise httpx.ConnectError("Connection failed")

        if self.fail_after_requests and self.request_count > self.fail_after_requests:
            raise httpx.ConnectError("Connection failed after N requests")

        key = (request.method, request.url.path)
        if key in self.responses:
            return self.responses[key]

        # Default 404
        return httpx.Response(404, json={"_tag": "NotFound", "message": "Not found"})

    async def aclose(self) -> None:
        pass


class MockStreamTransport(httpx.AsyncBaseTransport):
    """Mock transport for streaming responses."""

    def __init__(self, events: list[dict]) -> None:
        self.events = events
        self.request_count = 0

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        self.request_count += 1

        # Handle /api/info for ensure_running
        if request.url.path == "/api/info":
            return httpx.Response(200, json={"version": "2.3.2", "name": "opencode"})

        # Handle /api/event for streaming
        if request.url.path == "/api/event":
            content = create_sse_content(self.events)
            return httpx.Response(200, content=content)

        return httpx.Response(404, json={"_tag": "NotFound", "message": "Not found"})

    async def aclose(self) -> None:
        pass


def create_sse_lines(events: list[dict]) -> list[str]:
    """Create SSE-formatted lines from event dicts."""
    lines = []
    for event in events:
        lines.append(f"event: {event['type']}")
        # The data field is a JSON-encoded string per V2EventEncoded
        data_json = json.dumps(json.dumps(event))
        lines.append(f"data: {data_json}")
        lines.append("")  # Empty line between events
    return lines


class TestOpenCodeClient:
    """Tests for OpenCodeClient."""

    @pytest.fixture
    def mock_transport(self) -> MockTransport:
        return MockTransport()

    @pytest.fixture
    def client(self, mock_transport: MockTransport) -> OpenCodeClient:
        # Create client with external base URL
        return OpenCodeClient(
            "http://localhost:1234",
            httpx.BasicAuth("opencode", "test-password"),
        )

    @pytest.fixture
    def mock_client(self, client: OpenCodeClient, mock_transport: MockTransport) -> OpenCodeClient:
        # Replace the internal client with one using our mock transport
        client._client = httpx.AsyncClient(
            transport=mock_transport,
            base_url="http://localhost:1234",
            auth=httpx.BasicAuth("opencode", "test-password"),
        )
        return client

    @pytest.mark.asyncio
    async def test_ensure_running_external_success(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test ensure_running succeeds for external client."""
        mock_transport.responses[("GET", "/api/info")] = httpx.Response(
            200, json={"version": "2.3.2", "name": "opencode"}
        )

        conn = await mock_client.ensure_running()

        assert conn.base_url == "http://localhost:1234"
        assert isinstance(conn.auth, httpx.BasicAuth)

    @pytest.mark.asyncio
    async def test_ensure_running_external_failure(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test ensure_running raises OpenCodeUnavailable on connection failure."""
        mock_transport.should_fail_connect = True

        with pytest.raises(OpenCodeUnavailable):
            await mock_client.ensure_running()

    @pytest.mark.asyncio
    async def test_create_session_sends_correct_request(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test create_session sends correct method, path, and body."""
        mock_transport.responses[("POST", "/api/session")] = httpx.Response(
            200, json={"data": {"id": "ses_abc123", "title": "Test Session"}}
        )

        workspace = Path("/tmp/workspace")
        session_id = await mock_client.create_session(
            workspace, "agent-1", "Test Session"
        )

        assert session_id == "ses_abc123"

        # Verify request
        req = mock_transport.requests[-1]
        assert req.method == "POST"
        assert req.url.path == "/api/session"

        body = json.loads(req.content)
        assert body["agent"] == "agent-1"
        assert body["title"] == "Test Session"
        # Path.absolute() returns platform-specific path
        assert body["location"]["directory"] == str(workspace.absolute())

    @pytest.mark.asyncio
    async def test_create_session_error(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test create_session raises OpenCodeError on API error."""
        mock_transport.responses[("POST", "/api/session")] = httpx.Response(
            400, json={"_tag": "InvalidRequestError", "message": "Invalid agent"}
        )

        with pytest.raises(OpenCodeError) as exc_info:
            await mock_client.create_session(Path("/tmp/workspace"), "agent-1", "Test")

        assert exc_info.value.status == 400
        assert exc_info.value.tag == "InvalidRequestError"

    @pytest.mark.asyncio
    async def test_send_sends_correct_request(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test send sends correct method, path, and body."""
        mock_transport.responses[("POST", "/api/session/ses_123/prompt")] = httpx.Response(
            200, json={}
        )

        await mock_client.send("ses_123", "Hello, world!")

        req = mock_transport.requests[-1]
        assert req.method == "POST"
        assert req.url.path == "/api/session/ses_123/prompt"

        body = json.loads(req.content)
        assert body["text"] == "Hello, world!"

    @pytest.mark.asyncio
    async def test_events_filters_by_session(
        self, mock_client: OpenCodeClient
    ) -> None:
        """Test events() yields only events for the specified session."""
        # Create events for multiple sessions
        events = [
            {
                "type": "session.execution.started",
                "data": {"sessionID": "ses_123", "step": 1},
            },
            {
                "type": "session.step.started",
                "data": {"sessionID": "ses_456", "step": 1},
            },
            {
                "type": "session.tool.called",
                "data": {"sessionID": "ses_123", "tool": "write"},
            },
            {
                "type": "session.execution.succeeded",
                "data": {"sessionID": "ses_123"},
            },
        ]

        mock_transport = MockStreamTransport(events)
        mock_client._client = httpx.AsyncClient(
            transport=mock_transport,
            base_url="http://localhost:1234",
        )

        received = []
        async for event in mock_client.events("ses_123"):
            received.append(event)

        # Should only get events for ses_123
        assert len(received) == 3
        assert all(e.session_id == "ses_123" for e in received)
        assert received[0].kind == "started"
        assert received[1].kind == "tool"
        assert received[2].kind == "succeeded"

    @pytest.mark.asyncio
    async def test_events_maps_kinds_correctly(
        self, mock_client: OpenCodeClient
    ) -> None:
        """Test events are mapped to correct kinds."""
        events = [
            {"type": "session.execution.started", "data": {"sessionID": "ses_123"}},
            {"type": "session.step.started", "data": {"sessionID": "ses_123"}},
            {"type": "session.tool.called", "data": {"sessionID": "ses_123"}},
            {"type": "permission.asked", "data": {"sessionID": "ses_123"}},
            {"type": "session.execution.succeeded", "data": {"sessionID": "ses_123"}},
            {"type": "session.execution.failed", "data": {"sessionID": "ses_123"}},
            {"type": "session.execution.interrupted", "data": {"sessionID": "ses_123"}},
            {"type": "session.idle", "data": {"sessionID": "ses_123"}},
            {"type": "session.shell.started", "data": {"sessionID": "ses_123"}},
        ]

        mock_transport = MockStreamTransport(events)
        mock_client._client = httpx.AsyncClient(
            transport=mock_transport,
            base_url="http://localhost:1234",
        )

        received = []
        async for event in mock_client.events("ses_123"):
            received.append(event)

        kind_map = {e.type: e.kind for e in received}
        assert kind_map["session.execution.started"] == "started"
        assert kind_map["session.step.started"] == "step"
        assert kind_map["session.tool.called"] == "tool"
        assert kind_map["permission.asked"] == "permission"
        assert kind_map["session.execution.succeeded"] == "succeeded"
        assert kind_map["session.execution.failed"] == "failed"
        assert kind_map["session.execution.interrupted"] == "interrupted"
        assert kind_map["session.idle"] == "idle"
        assert kind_map["session.shell.started"] == "other"

    @pytest.mark.asyncio
    async def test_events_raises_unavailable_on_stream_break(
        self, mock_client: OpenCodeClient
    ) -> None:
        """Test events() raises OpenCodeUnavailable when stream breaks."""
        # Start with a working stream, then fail
        events = [
            {"type": "session.execution.started", "data": {"sessionID": "ses_123"}},
        ]
        sse_content = create_sse_content(events)

        class FailingTransport(httpx.AsyncBaseTransport):
            def __init__(self):
                self.count = 0

            async def handle_async_request(self, request):
                # Handle /api/info for ensure_running
                if request.url.path == "/api/info":
                    return httpx.Response(200, json={"version": "2.3.2", "name": "opencode"})

                self.count += 1
                if self.count == 1:
                    return httpx.Response(200, content=sse_content)
                else:
                    raise httpx.ConnectError("Stream broken")

            async def aclose(self) -> None:
                pass

        mock_client._client = httpx.AsyncClient(
            transport=FailingTransport(),
            base_url="http://localhost:1234",
        )

        # First call should work
        events_received = []
        async for event in mock_client.events("ses_123"):
            events_received.append(event)

        assert len(events_received) == 1

        # Second call should raise OpenCodeUnavailable
        with pytest.raises(OpenCodeUnavailable):
            async for _ in mock_client.events("ses_123"):
                pass

    @pytest.mark.asyncio
    async def test_events_recovers_after_transport_recovers(
        self, mock_client: OpenCodeClient
    ) -> None:
        """Test new events() call works after transport recovers (T6)."""
        events = [
            {"type": "session.execution.started", "data": {"sessionID": "ses_123"}},
        ]
        sse_content = create_sse_content(events)

        class RecoveringTransport(httpx.AsyncBaseTransport):
            def __init__(self):
                self.fail = True

            async def handle_async_request(self, request):
                # Handle /api/info for ensure_running
                if request.url.path == "/api/info":
                    return httpx.Response(200, json={"version": "2.3.2", "name": "opencode"})

                if self.fail:
                    self.fail = False
                    raise httpx.ConnectError("Temporary failure")

                return httpx.Response(200, content=sse_content)

            async def aclose(self) -> None:
                pass

        transport = RecoveringTransport()
        mock_client._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://localhost:1234",
        )

        # First call fails
        with pytest.raises(OpenCodeUnavailable):
            async for _ in mock_client.events("ses_123"):
                pass

        # Second call should work after recovery
        events_received = []
        async for event in mock_client.events("ses_123"):
            events_received.append(event)

        assert len(events_received) == 1
        assert events_received[0].kind == "started"

    @pytest.mark.asyncio
    async def test_pending_permissions(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test pending_permissions returns correct data."""
        mock_transport.responses[("GET", "/api/session/ses_123/permission")] = httpx.Response(
            200,
            json={
                "data": [
                    {
                        "data": {
                            "id": "per_123",
                            "sessionID": "ses_123",
                            "action": "write",
                            "resources": ["/tmp/file.txt"],
                            "message": "Allow writing?",
                        }
                    }
                ]
            },
        )

        perms = await mock_client.pending_permissions("ses_123")

        assert len(perms) == 1
        assert isinstance(perms[0], PermissionRequest)
        assert perms[0].id == "per_123"
        assert perms[0].session_id == "ses_123"
        assert perms[0].action == "write"
        assert perms[0].resources == ["/tmp/file.txt"]
        assert perms[0].message == "Allow writing?"

    @pytest.mark.asyncio
    async def test_answer_permission_allow(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test answer_permission with allow=True."""
        mock_transport.responses[
            ("POST", "/api/session/ses_123/permission/per_123/reply")
        ] = httpx.Response(204)

        await mock_client.answer_permission("ses_123", "per_123", True)

        req = mock_transport.requests[-1]
        assert req.method == "POST"
        assert req.url.path == "/api/session/ses_123/permission/per_123/reply"

        body = json.loads(req.content)
        assert body["decision"] == "always"

    @pytest.mark.asyncio
    async def test_answer_permission_reject(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test answer_permission with allow=False."""
        mock_transport.responses[
            ("POST", "/api/session/ses_123/permission/per_123/reply")
        ] = httpx.Response(204)

        await mock_client.answer_permission("ses_123", "per_123", False)

        req = mock_transport.requests[-1]
        body = json.loads(req.content)
        assert body["decision"] == "reject"

    @pytest.mark.asyncio
    async def test_abort_sends_interrupt(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test abort sends interrupt request."""
        mock_transport.responses[
            ("POST", "/api/session/ses_123/interrupt")
        ] = httpx.Response(200, json={"interrupted": True})

        await mock_client.abort("ses_123")

        req = mock_transport.requests[-1]
        assert req.method == "POST"
        assert req.url.path == "/api/session/ses_123/interrupt"

    @pytest.mark.asyncio
    async def test_result_sums_diff(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test result() computes files, additions, deletions from diff."""
        mock_transport.responses[
            ("GET", "/api/session/ses_123/diff")
        ] = httpx.Response(
            200,
            json={
                "data": [
                    {
                        "path": "/tmp/file1.py",
                        "hunks": [
                            {
                                "lines": [
                                    {"type": "add", "content": "new line 1"},
                                    {"type": "add", "content": "new line 2"},
                                    {"type": "remove", "content": "old line"},
                                ]
                            }
                        ]
                    },
                    {
                        "path": "/tmp/file2.py",
                        "hunks": [
                            {
                                "lines": [
                                    {"type": "add", "content": "another addition"},
                                ]
                            }
                        ]
                    },
                ]
            },
        )

        mock_transport.responses[
            ("GET", "/api/session/ses_123/message")
        ] = httpx.Response(
            200,
            json={
                "data": [
                    {
                        "content": "I've created two files with the changes you requested.",
                    }
                ]
            },
        )

        result = await mock_client.result("ses_123")

        assert isinstance(result, WorkResult)
        assert result.session_id == "ses_123"
        assert result.files_changed == ["/tmp/file1.py", "/tmp/file2.py"]
        assert result.additions == 3
        assert result.deletions == 1
        assert "I've created two files" in result.summary

    @pytest.mark.asyncio
    async def test_result_empty_diff(
        self, mock_client: OpenCodeClient, mock_transport: MockTransport
    ) -> None:
        """Test result() with empty diff."""
        mock_transport.responses[
            ("GET", "/api/session/ses_123/diff")
        ] = httpx.Response(200, json={"data": []})

        mock_transport.responses[
            ("GET", "/api/session/ses_123/message")
        ] = httpx.Response(200, json={"data": []})

        result = await mock_client.result("ses_123")

        assert result.files_changed == []
        assert result.additions == 0
        assert result.deletions == 0
        assert result.summary == ""

    @pytest.mark.asyncio
    async def test_managed_process_client(
        self, mock_transport: MockTransport
    ) -> None:
        """Test client works with managed OpenCodeProcess."""
        mock_process = MagicMock(spec=OpenCodeProcess)
        mock_process.is_running = True
        mock_process.connection = OpenCodeConnection(
            base_url="http://localhost:5678",
            auth=httpx.BasicAuth("opencode", "test-pass"),
            version="2.3.2",
        )

        client = OpenCodeClient(mock_process)
        client._client = httpx.AsyncClient(
            transport=mock_transport,
            base_url="http://localhost:5678",
            auth=httpx.BasicAuth("opencode", "test-pass"),
        )

        mock_transport.responses[("POST", "/api/session")] = httpx.Response(
            200, json={"data": {"id": "ses_managed"}}
        )

        session_id = await client.create_session(Path("/workspace"), "agent", "Test")
        assert session_id == "ses_managed"

    @pytest.mark.asyncio
    async def test_close_closes_client(
        self, mock_client: OpenCodeClient
    ) -> None:
        """Test close() closes the HTTP client."""
        await mock_client.close()
        assert mock_client._client is None


class TestOpenCodeClientEndpoints:
    """Test that OPENCODE_CLIENT_ENDPOINTS lists all used endpoints."""

    def test_endpoints_list_not_empty(self) -> None:
        """Test that the endpoints list is not empty."""
        assert len(OPENCODE_CLIENT_ENDPOINTS) > 0

    def test_endpoints_are_tuples(self) -> None:
        """Test that each endpoint is a (method, path) tuple."""
        for endpoint in OPENCODE_CLIENT_ENDPOINTS:
            assert isinstance(endpoint, tuple)
            assert len(endpoint) == 2
            assert isinstance(endpoint[0], str)
            assert isinstance(endpoint[1], str)

    def test_required_endpoints_present(self) -> None:
        """Test that all required endpoints are present."""
        required = {
            ("POST", "/api/session"),
            ("POST", "/api/session/{sessionID}/prompt"),
            ("GET", "/api/event"),
            ("GET", "/api/session/{sessionID}/permission"),
            ("POST", "/api/session/{sessionID}/permission/{requestID}/reply"),
            ("POST", "/api/session/{sessionID}/interrupt"),
            ("GET", "/api/session/{sessionID}/diff"),
            ("GET", "/api/session/{sessionID}/message"),
        }
        for req in required:
            assert req in OPENCODE_CLIENT_ENDPOINTS, f"Missing endpoint: {req}"