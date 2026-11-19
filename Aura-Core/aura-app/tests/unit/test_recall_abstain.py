"""W3-07: abstention on the channels path (flagged).

With ``recall_channels_enabled`` and ``recall_abstain_enabled`` on, the
memories block abstains when the lexical channel returned no hits and the
best dense similarity is below ``recall_abstain_min_similarity`` (or the
dense channel returned nothing). The block text is then the single abstention
note and ``packet.abstain`` is ``True``.

The tests drive the real ``_build_memories`` channel wiring with the dense and
lexical channels monkeypatched to fixed hit lists, so the relevance decision is
the only thing under test. The memory manager is built with
``MemoryManager.__new__`` (no database connection, no model load) and its
``db.query`` returns rows from a small in-memory table.
"""

from unittest.mock import AsyncMock

import pytest

import aura.engines.recall.engine as engine_module
from aura.config import settings
from aura.engines.memory.manager import MemoryManager
from aura.engines.recall.channels import ChannelHit
from aura.engines.recall.engine import RecallEngine
from aura.engines.recall.models import RecallRequest

ABSTAIN_LINE = (
    '<memories abstain="true">Nothing relevant to this message is stored in '
    "memory. Do not claim to remember anything about it.</memories>"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeEmbeddings:
    """Deterministic embeddings client: the tests never inspect the vector."""

    async def embed(self, text: str) -> list[float]:
        return [0.0, 0.0, 0.0]


def _row(memory_id: str, content: str) -> dict:
    return {"id": memory_id, "content": content, "importance": 0.5}


def _make_manager(rows: list[dict]) -> MemoryManager:
    """Build a manager whose ``db.query`` serves the given rows by record id."""
    manager = MemoryManager.__new__(MemoryManager)
    manager.embeddings = _FakeEmbeddings()
    by_id = {str(row["id"]): row for row in rows}

    async def _query(sql: str, params: dict) -> list[dict]:
        return [by_id[str(rid)] for rid in params["ids"] if str(rid) in by_id]

    manager.db = AsyncMock()
    manager.db.query = AsyncMock(side_effect=_query)
    return manager


def _patch_channels(
    monkeypatch, dense: list[ChannelHit], lexical: list[ChannelHit]
) -> None:
    async def _dense(*args, **kwargs):
        return dense

    async def _lexical(*args, **kwargs):
        return lexical

    monkeypatch.setattr(engine_module, "dense_channel", _dense)
    monkeypatch.setattr(engine_module, "lexical_channel", _lexical)


def _request(user_input: str) -> RecallRequest:
    return RecallRequest(
        user_id="u1",
        user_input=user_input,
        include_cold_start=False,
        include_latent=False,
        limit=5,
    )


def _engine(rows: list[dict]) -> RecallEngine:
    return RecallEngine(memory_manager=_make_manager(rows), latent_engine=None)


# ---------------------------------------------------------------------------
# The four card cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_query_abstains_with_exactly_the_note_line(monkeypatch):
    """Seeded memories, but neither channel finds anything relevant."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_abstain_enabled", True)
    _patch_channels(monkeypatch, dense=[], lexical=[])

    engine = _engine(
        [_row("memory:dog", "the user's dog is called Biscuit")]
    )
    packet = await engine.recall(_request("what is my favourite mountain?"))

    assert packet.abstain is True
    assert packet.block_text("memories") == ABSTAIN_LINE


@pytest.mark.asyncio
async def test_lexical_hit_does_not_abstain_even_with_low_dense_similarity(
    monkeypatch,
):
    """Any lexical (content-word) hit is enough to keep the memories block."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_abstain_enabled", True)
    _patch_channels(
        monkeypatch,
        dense=[ChannelHit(memory_id="memory:dog", rank=0, score=0.10)],
        lexical=[ChannelHit(memory_id="memory:dog", rank=0, score=2.5)],
    )

    engine = _engine([_row("memory:dog", "the user's dog is called Biscuit")])
    packet = await engine.recall(_request("what is my dog called?"))

    assert packet.abstain is False
    memories = packet.block_text("memories")
    assert memories is not None
    assert "Biscuit" in memories
    assert memories != ABSTAIN_LINE


@pytest.mark.asyncio
async def test_dense_similarity_above_threshold_does_not_abstain(monkeypatch):
    """No lexical hit, but the best dense score clears the threshold."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_abstain_enabled", True)
    monkeypatch.setattr(settings, "recall_abstain_min_similarity", 0.55)
    _patch_channels(
        monkeypatch,
        dense=[ChannelHit(memory_id="memory:dog", rank=0, score=0.90)],
        lexical=[],
    )

    engine = _engine([_row("memory:dog", "the user's dog is called Biscuit")])
    packet = await engine.recall(_request("tell me about my pet"))

    assert packet.abstain is False
    memories = packet.block_text("memories")
    assert memories is not None
    assert "Biscuit" in memories


@pytest.mark.asyncio
async def test_flag_off_never_abstains(monkeypatch):
    """Ablation: without the abstain flag, empty channels give no note."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_abstain_enabled", False)
    _patch_channels(monkeypatch, dense=[], lexical=[])

    engine = _engine(
        [_row("memory:dog", "the user's dog is called Biscuit")]
    )
    packet = await engine.recall(_request("what is my favourite mountain?"))

    assert packet.abstain is False
    assert packet.block_text("memories") is None


@pytest.mark.asyncio
async def test_gate_skipped_turn_never_abstains(monkeypatch):
    """A skipped turn reusing a cached abstention does not abstain again."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_abstain_enabled", True)
    monkeypatch.setattr(settings, "recall_gate_enabled", True)
    _patch_channels(monkeypatch, dense=[], lexical=[])

    engine = _engine(
        [_row("memory:dog", "the user's dog is called Biscuit")]
    )

    first = await engine.recall(_request("what is my favourite mountain?"))
    assert first.trace.gate == "ran"
    assert first.abstain is True

    second = await engine.recall(_request("hello"))
    assert second.trace.gate == "skipped"
    assert second.abstain is False
    assert second.block_text("memories") is None