"""P2-42: reasoning controls move to the tier slider.

Old clients may still send reasoning_enabled, l2_reasoning_enabled,
deep_analysis_enabled and enable_l2; they are ignored (one log line per
process). The profile and the L1 route decide alone. No real model calls.
"""
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aura import tiers
from aura.api.routes import chat as chat_routes
from aura.config import settings


@pytest.fixture(autouse=True)
def _latch():
    tiers.reset_deprecation_latch()
    yield
    tiers.reset_deprecation_latch()


class _Orch:
    """Stub orchestrator for the chat route."""

    def __init__(self, meta):
        self.meta = meta
        self.process_kwargs: dict = {}
        self.emotion_engine = SimpleNamespace(
            get_current_state=AsyncMock(
                return_value=SimpleNamespace(dominant=("joy", 0.5), description="ok")
            )
        )

    async def process_query(self, **kwargs):
        self.process_kwargs = kwargs
        kwargs["turn_meta"].update(self.meta)
        return "hello"

    async def stream_query(self, **kwargs):
        self.process_kwargs = kwargs
        kwargs["turn_meta"].update(self.meta)
        yield "hel"
        yield "lo"


@pytest.fixture
def client(monkeypatch):
    orch = _Orch({"deep_reasoning": True, "tier": "core", "route": "think"})
    monkeypatch.setattr(chat_routes, "_orchestrator", orch)
    app = FastAPI()
    app.include_router(chat_routes.router, prefix="/chat")
    return TestClient(app), orch


def test_request_without_the_fields_works(client):
    c, orch = client
    r = c.post("/chat/message", json={"message": "hi"})
    assert r.status_code == 200
    for name in tiers.DEPRECATED_REASONING_FIELDS:
        assert name not in orch.process_kwargs


def test_old_fields_are_ignored_with_one_log_line(client, caplog):
    c, orch = client
    body = {
        "message": "hi",
        "reasoning_enabled": True,
        "l2_reasoning_enabled": True,
        "deep_analysis_enabled": False,
        "enable_l2": False,
    }
    with caplog.at_level(logging.WARNING, logger="aura.tiers"):
        assert c.post("/chat/message", json=body).status_code == 200
        assert c.post("/chat/message", json=body).status_code == 200
        assert c.post("/chat/stream", json=body).status_code == 200
    lines = [r for r in caplog.records if "Deprecated reasoning controls" in r.getMessage()]
    assert len(lines) == 1
    for name in tiers.DEPRECATED_REASONING_FIELDS:
        assert name not in orch.process_kwargs


def test_response_carries_deep_reasoning_tier_route(client):
    c, _ = client
    data = c.post("/chat/message", json={"message": "hi"}).json()
    assert data["deep_reasoning"] is True
    assert data["tier"] == "core"
    assert data["route"] == "think"


def test_stream_sends_turn_meta_before_done(client):
    c, _ = client
    text = c.post("/chat/stream", json={"message": "hi"}).text
    lines = [ln for ln in text.split("\n") if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    assert '"type": "turn_meta"' in lines[-2]
    assert '"deep_reasoning": true' in lines[-2] and '"tier": "core"' in lines[-2]


# ---------------------------------------------------------------------------
# Coordinator: effective values
# ---------------------------------------------------------------------------


@pytest.fixture
def orch(turn_orchestrator, monkeypatch):
    o = turn_orchestrator
    monkeypatch.setattr(settings, "l1_routes_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "recall_feedback_enabled", False)
    o.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    o.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    o._log_interaction_experience = AsyncMock()
    o._fake_tool_registry.select_tools = AsyncMock(return_value=[])
    return o


async def _run(o, monkeypatch, *, index, profiles, route="think", stakes=0.0, **kw):
    monkeypatch.setattr(settings, "model_stack_index", index)
    monkeypatch.setattr(settings, "tier_profiles_enabled", profiles)
    o.llm_layers.l1_classify_intent = AsyncMock(
        return_value={"intent": "CHAT", "route": route, "stakes": stakes, "confidence": 0.9}
    )
    meta: dict = {}
    await o.process_query("hello", user_id="u1", conversation_id="c1", turn_meta=meta, **kw)
    for _ in range(5):
        await __import__("asyncio").sleep(0)
    return meta


def _l3(o):
    return o.llm_layers.l3_synthesis.call_args.kwargs["reasoning_enabled"]


@pytest.mark.parametrize("index,want", [(0, False), (1, True), (2, True)])
async def test_reasoning_follows_the_profile_when_on(orch, monkeypatch, index, want):
    # Whatever the client sends is ignored.
    meta = await _run(
        orch, monkeypatch, index=index, profiles=True, reasoning_enabled=False,
        l2_reasoning_enabled=False, deep_analysis_enabled=False,
    )
    assert _l3(orch) is want
    assert meta["deep_reasoning"] is want
    assert meta["tier"] == ["lean", "core", "titan"][index]
    assert meta["route"] == "think"
    post = orch._post_response_chain.call_args.kwargs
    prof = tiers.DEFAULT_PROFILES[index]
    assert post["enable_l2"] is tiers.l2_analysis_allowed(prof)
    assert post["l2_reasoning_enabled"] is tiers.l2_reasoning_allowed(prof)


async def test_old_defaults_apply_when_off(orch, monkeypatch):
    # Client asks for everything; the flag-off values are the old frontend defaults.
    meta = await _run(
        orch, monkeypatch, index=2, profiles=False, reasoning_enabled=True,
        l2_reasoning_enabled=True, deep_analysis_enabled=False,
    )
    assert _l3(orch) is False
    post = orch._post_response_chain.call_args.kwargs
    assert post["enable_l2"] is True and post["l2_reasoning_enabled"] is False
    assert meta["deep_reasoning"] is False and meta["tier"] == "titan"


async def test_request_without_fields_equals_old_default_request(orch, monkeypatch):
    await _run(orch, monkeypatch, index=1, profiles=False)
    bare = (_l3(orch), orch._post_response_chain.call_args.kwargs["enable_l2"],
            orch._post_response_chain.call_args.kwargs["l2_reasoning_enabled"])
    assert bare == (False, True, False)


async def test_null_route_when_routes_are_off(orch, monkeypatch):
    monkeypatch.setattr(settings, "l1_routes_enabled", False)
    meta = await _run(orch, monkeypatch, index=1, profiles=True)
    assert meta["route"] is None and meta["deep_reasoning"] is False


async def test_coordinator_kwargs_log_once(orch, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="aura.tiers"):
        await _run(orch, monkeypatch, index=1, profiles=True, reasoning_enabled=True)
        await _run(orch, monkeypatch, index=1, profiles=True, reasoning_enabled=True)
    assert len([r for r in caplog.records if "Deprecated reasoning" in r.getMessage()]) == 1
