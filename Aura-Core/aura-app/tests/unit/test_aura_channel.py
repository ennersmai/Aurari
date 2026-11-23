"""B1-04: /ws/aura channel, event hub and catch-up route."""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from aura.api.routes import aura_events
from aura.api.websocket import aura_channel_endpoint, aura_manager
from aura.autonomy import channel
from aura.clock import FakeClock, get_clock, set_clock
from aura.config import settings


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", True)
    monkeypatch.setattr(settings, "aura_channel_buffer", 5)
    monkeypatch.setattr(settings, "aura_channel_ping_seconds", 30.0)
    old = get_clock()
    set_clock(FakeClock(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)))
    channel.reset()
    aura_manager.active_connections.clear()
    yield
    set_clock(old)
    channel.reset()
    aura_manager.active_connections.clear()


def _client() -> TestClient:
    app = FastAPI()

    @app.websocket("/ws/aura")
    async def ws(websocket: WebSocket) -> None:
        await aura_channel_endpoint(websocket)

    app.include_router(aura_events.router)
    return TestClient(app)


def _pub(t, p=None, **kw):
    return asyncio.run(channel.publish(t, p, **kw))


def test_ordering_seq_and_envelope():
    a = _pub("agenda_update", {"x": 1})
    b = _pub("drive_state", {"y": 2})
    assert (a["seq"], b["seq"]) == (1, 2)
    assert a["v"] == 1 and a["type"] == "agenda_update" and a["payload"] == {"x": 1}
    assert a["at"] == "2026-01-02T03:04:05+00:00"
    assert [e["seq"] for e in channel.events_since(0)] == [1, 2]


def test_unknown_type_rejected():
    with pytest.raises(ValueError):
        _pub("bogus")


def test_catch_up_after_last_seq_then_live():
    for i in range(3):
        _pub("aura_message", {"i": i})
    c = _client()
    with c.websocket_connect("/ws/aura") as ws:
        ws.send_json({"type": "hello", "last_seq": 1})
        assert [ws.receive_json()["seq"], ws.receive_json()["seq"]] == [2, 3]
        ws.send_json({"type": "presence", "typing": True})  # barrier: processed in order
        ws.send_json({"type": "hello", "last_seq": 3})
        # TestClient runs the app in another loop, so verify via catch-up
        live = _pub("autonomy_state", {"level": "open"})
        ws.send_json({"type": "hello", "last_seq": 3})
        got = ws.receive_json()
        assert got["seq"] == live["seq"] == 4 and got["type"] == "autonomy_state"


def test_buffer_bound():
    for i in range(8):
        _pub("aura_message", {"i": i})
    seqs = [e["seq"] for e in channel.events_since(0)]
    assert seqs == [4, 5, 6, 7, 8]


def test_persist_false_not_buffered():
    e = _pub("drive_state", {}, persist=False)
    assert e["seq"] == 1 and channel.events_since(0) == []


def test_failing_client_dropped_others_receive():
    class Bad:
        async def send_json(self, m):
            raise RuntimeError("boom")

    class Good:
        def __init__(self):
            self.got = []

        async def send_json(self, m):
            self.got.append(m)

    bad, good = Bad(), Good()
    aura_manager.active_connections.extend([bad, good])
    env = _pub("aura_message", {"t": "hi"})
    assert good.got == [env]
    assert bad not in aura_manager.active_connections
    assert good in aura_manager.active_connections


def test_flag_off_publishes_nothing(monkeypatch):
    class Good:
        got: list = []

        async def send_json(self, m):
            self.got.append(m)

    g = Good()
    aura_manager.active_connections.append(g)
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", False)
    env = _pub("aura_message", {"a": 1})
    assert env["type"] == "aura_message" and env["payload"] == {"a": 1}
    assert g.got == [] and channel.events_since(0) == []
    with pytest.raises(WebSocketDisconnect) as ei:
        with _client().websocket_connect("/ws/aura"):
            pass
    assert ei.value.code == 1008


def test_chat_message_shape_matches_task_reports():
    import inspect
    from aura.api.routes import chat

    src = inspect.getsource(chat.get_task_reports)
    keys = ["id", "conversationId", "content", "role", "timestamp", "meta"]
    for k in keys:
        assert f'"{k}"' in src
    msg = dict.fromkeys(keys)
    assert _pub("chat_message", msg)["payload"].keys() == set(keys)


def test_presence_stored():
    with _client().websocket_connect("/ws/aura") as ws:
        ws.send_json({"type": "presence", "typing": True, "active_view": "chat", "junk": 1})
        ws.send_json({"type": "hello", "last_seq": 0})
        _pub("drive_state", {})
        ws.send_json({"type": "hello", "last_seq": 0})
        assert ws.receive_json()["type"] == "drive_state"
    assert channel.presence.typing is True
    assert channel.presence.active_view == "chat"
    assert channel.presence.last_interaction_at == get_clock().now()


def test_ping_on_idle(monkeypatch):
    monkeypatch.setattr(settings, "aura_channel_ping_seconds", 0.05)
    with _client().websocket_connect("/ws/aura") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "ping" and msg["v"] == 1


def test_events_route():
    for i in range(3):
        _pub("aura_message", {"i": i})
    r = _client().get("/aura/events", params={"since_seq": 1}).json()
    assert [e["seq"] for e in r["events"]] == [2, 3] and r["last_seq"] == 3
