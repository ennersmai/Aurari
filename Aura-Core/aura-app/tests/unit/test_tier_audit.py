"""P2-01: tier audit. Measures which model every LLM caller uses per stack.

The stack is set with the real ``POST /system/inference-config`` route function
(``set_inference_config``, called directly). Outgoing chat requests are caught
at ``httpx.AsyncClient.post``, the lowest point of ``OpenRouterClient``
(``llm/provider.py:226``); nothing is sent. The observed ``model`` must equal
``settings.active_lX_model`` for the stack. Cases that fail because of a
finding in AURA_PHASE2_PLAN.md are strict xfails so that P2-02 must remove
them. This card only measures; it fixes nothing.
"""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from aura.config import settings

STACKS = (0, 1, 2)
_SUFFIX = {0: "", 1: "1", 2: "2"}

# Attributes set by set_inference_config; snapshotted so teardown restores them.
_ROUTE_ATTRS = (
    "inference_temperature", "inference_top_p", "inference_min_p",
    "inference_frequency_penalty", "inference_presence_penalty",
    "inference_context_length", "inference_max_tokens",
    "layer_l1_enabled", "layer_l2_enabled", "layer_l3_enabled",
    "layer_l4_enabled", "layer_l5_enabled",
    "local_llm_enabled", "sglang_enabled", "model_stack_index",
)

_FAKE_REPLY = json.dumps(
    {"intent": "CHAT", "confidence": 0.9, "needs_agentic_rag": False,
     "detected_tool": None, "analysis": "ok", "patterns": [],
     "facts": [], "summary": "ok"}
)


def _audit_name(stack: int, layer: int) -> str:
    return f"audit/s{stack}-l{layer}"


@pytest.fixture
def audit_env(monkeypatch):
    """Distinct model per layer x stack, no fallbacks, cloud only, calls recorded."""
    for stack in STACKS:
        for layer in range(1, 6):
            monkeypatch.setattr(
                settings, f"l{layer}_model{_SUFFIX[stack]}", _audit_name(stack, layer)
            )
    for layer in range(1, 6):
        monkeypatch.setattr(settings, f"l{layer}_model_fallback", None)
    monkeypatch.setattr(settings, "memory_extraction_model", "")
    for attr in _ROUTE_ATTRS:
        monkeypatch.setattr(settings, attr, getattr(settings, attr))
    monkeypatch.setattr(settings, "local_llm_enabled", False)
    monkeypatch.setattr(settings, "sglang_enabled", False)
    for layer in range(1, 6):
        monkeypatch.setattr(settings, f"layer_l{layer}_enabled", True)

    seen: list[str] = []

    async def fake_post(self, url, *args, **kwargs):
        body = kwargs.get("json") or {}
        seen.append(body.get("model"))
        data = {"choices": [{"message": {"role": "assistant", "content": _FAKE_REPLY}}]}
        return httpx.Response(200, json=data, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    # L1 tries a vector lookup before the LLM; keep it offline.
    emb = MagicMock()
    emb.embed = AsyncMock(return_value=None)
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: emb)
    monkeypatch.setattr("aura.db.client.get_db_client", lambda: MagicMock())
    return seen


async def _switch_stack(stack: int) -> None:
    """Same path as the navbar: POST /system/inference-config (route called directly)."""
    from aura.api.routes.inference_config import get_inference_config, set_inference_config

    current = await get_inference_config()
    result = await set_inference_config(current.model_copy(update={"model_stack_index": stack}))
    assert settings.model_stack_index == stack
    assert result["active_models"]["l3"] == _audit_name(stack, 3)


def _layers():
    from aura.llm.layers import LLMLayers
    from aura.llm.provider import OpenRouterClient

    return LLMLayers(client=OpenRouterClient(api_key="audit-key"))


async def _l1(layers):
    await layers.l1_classify_intent("hello there")


async def _l2(layers):
    await layers.l2_reasoning({"user_input": "hi", "aura_response": "hello"})


async def _l3(layers):
    from aura.llm.layers import SynthesisContext

    await layers.l3_synthesis(SynthesisContext(user_input="hi"))


async def _l4(layers):
    try:
        await layers.l4_appraise_message("hi", [], "owner")
    except ValueError:
        pass  # the fake reply is not an appraisal; the request was still recorded


async def _l5(layers):
    await layers.l5_structure_analysis("extract something")


async def _extraction(layers):
    from aura.engines.memory.v2.extraction import extract

    try:
        await extract(layers.client, {"user_text": "hi", "aura_text": "hello"}, [])
    except Exception:  # noqa: BLE001 - fake reply is not an Extraction
        pass


async def _themes(layers):
    from aura.engines.dreaming.themes import _summarise

    await _summarise(layers.client, "Summarise.", ["a fact"])


async def _latent(layers):
    from aura.engines.latent.engine import LatentEngine, LatentStateCache

    engine = object.__new__(LatentEngine)
    engine.logger = logging.getLogger("tier_audit.latent")
    engine.llm_layers = layers
    engine._state_cache = {"u": LatentStateCache(user_id="u", state_vector=[], momentum_vector=[])}
    await engine._regenerate_summary("u")


# caller id -> (callable, expected layer, finding for xfail or None)
CALLERS: dict[str, tuple[Any, int, str | None]] = {
    "l1_classify_intent": (_l1, 1, None),
    "l2_reasoning": (_l2, 2, None),
    "l3_synthesis": (_l3, 3, None),
    "l4_appraise_message": (_l4, 4, None),
    "l5_structure_analysis": (_l5, 5, None),
    "memory_extraction": (_extraction, 2, "engines/memory/v2/extraction.py:156"),
    "dreaming_themes": (_themes, 2, "engines/dreaming/themes.py:125"),
    "latent_summary": (_latent, 5, "engines/latent/engine.py:715"),
}


def _params():
    out = []
    for name, (_fn, _layer, finding) in CALLERS.items():
        for stack in STACKS:
            marks = []
            # Stack 0 reads the stack 0 field, so the finding only bites on 1 and 2.
            if finding and stack != 0:
                marks.append(pytest.mark.xfail(strict=True, reason=finding))
            out.append(pytest.param(name, stack, id=f"{name}-stack{stack}", marks=marks))
    return out


@pytest.mark.parametrize("caller,stack", _params())
async def test_caller_uses_active_stack_model(audit_env, caller, stack):
    fn, layer, _finding = CALLERS[caller]
    await _switch_stack(stack)
    await fn(_layers())

    expected = getattr(settings, f"active_l{layer}_model")
    assert expected == _audit_name(stack, layer)
    assert audit_env, f"{caller} made no outgoing request"
    assert audit_env[-1] == expected


@pytest.mark.parametrize("stack", STACKS)
async def test_system_state_reports_active_models(audit_env, stack):
    """GET /system/model-stack: ``models`` is the active stack; ``available_stacks`` lists all three."""
    from aura.api.routes.system_state import get_model_stack

    await _switch_stack(stack)
    report = await get_model_stack()
    assert report["stack_index"] == stack
    for layer in range(1, 6):
        assert report["models"][f"l{layer}"] == _audit_name(stack, layer)
        for s in STACKS:
            assert report["available_stacks"][s][f"l{layer}"] == _audit_name(s, layer)


@pytest.mark.parametrize(
    "stack",
    [
        0,
        pytest.param(1, marks=pytest.mark.xfail(strict=True, reason="llm/unified_provider.py:261")),
        pytest.param(2, marks=pytest.mark.xfail(strict=True, reason="llm/unified_provider.py:261")),
    ],
)
async def test_cloud_fallback_map_follows_active_stack(audit_env, stack):
    from aura.llm.unified_provider import UnifiedLLMClient

    await _switch_stack(stack)
    client = UnifiedLLMClient(openrouter_client=MagicMock(), ollama_client=MagicMock())
    assert client._get_cloud_fallback(settings.active_l1_model) is not None
