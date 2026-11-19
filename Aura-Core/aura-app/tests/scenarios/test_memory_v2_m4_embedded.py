"""Memory M4 gate scenarios (card W3-18).

These tests drive the real in-memory embedded SurrealDB (``mem://``) through
the scenario runner's adapter, deterministic embedding stub and manager
wiring, with every memory v2 flag and the three M3 recall flags on.  Each turn
is stored through the real ``store_episode`` and its facts are written through
the real ``run_extraction`` path; the extraction client is a script returning
one fixed :class:`Extraction` per turn, so no model is called.

The probes are the M4 gate from the memory PRD:

* an updated fact is recalled and the old one is not;
* the ``supersedes`` chain from the new fact reaches the old one;
* a guest DM fact stays out of the app and guilds, and a guild fact stays out
  of other guilds;
* a guest's claim about the owner never replaces the owner's own fact;
* over a 40-turn script with 10 updates, the share of recalled facts that are
  superseded stays under 2%.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from aura.engines.memory.v2.episodes import ensure_person, store_episode
from aura.engines.memory.v2.extraction import Extraction, run_extraction
from aura.engines.recall import RecallEngine, RecallRequest
from tests.conftest import write_baseline
from tests.scenarios.runner import (
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    StubLatentEngine,
    _build_manager,
)

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_M4_METRICS_PATH = Path(__file__).resolve().parents[2] / "docs" / "metrics" / "m4.md"


# ---------------------------------------------------------------------------
# Scripted extraction and scenario driver
# ---------------------------------------------------------------------------


class ScriptedExtractionClient:
    """Return one fixed :class:`Extraction` per extraction call.

    ``run_extraction`` expects the client's reply to be JSON text, so the
    scripted extraction is serialised.  No model or network is involved.
    """

    def __init__(self, extractions: list[Extraction]) -> None:
        self._pending = list(extractions)
        self.calls = 0

    async def complete(self, messages: Any, model: str, temperature: float = 0.7, **kwargs: Any) -> str:
        self.calls += 1
        if not self._pending:
            raise AssertionError("scripted extraction client ran out of turns")
        return json.dumps(self._pending.pop(0).model_dump())


@dataclass
class _Turn:
    """One scripted turn: what was said, where, and what to extract."""

    at_day: float
    text: str
    extraction: Extraction
    speaker: str = "owner"
    venue: str = "app"
    conversation_id: str = "c1"


def _fact(**overrides: Any) -> dict[str, Any]:
    fact = {
        "content": "I live in Lisbon.",
        "kind": "fact",
        "subject": "I",
        "predicate": "live in",
        "object": "Lisbon",
        "about": ["Lisbon"],
        "asserted_by": "user",
        "implied": False,
        "negates": False,
    }
    fact.update(overrides)
    return fact


def _extraction(entities: list[dict], facts: list[dict]) -> Extraction:
    return Extraction.model_validate(
        {
            "entities": entities,
            "facts": facts,
            "questions": [],
            "predictions": [],
        }
    )


def _enable_all_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch on every memory v2 flag and the three M3 recall flags."""
    monkeypatch.setattr(settings, "memory_v2_write_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_gate_enabled", True)
    monkeypatch.setattr(settings, "recall_abstain_enabled", True)


async def _open(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[EmbeddedSurrealDB, HashedBagOfWordsEmbeddings]:
    """Open the embedded DB and wire the deterministic embedding stub."""
    _enable_all_flags(monkeypatch)
    db = EmbeddedSurrealDB()
    await db.connect()
    embeddings = HashedBagOfWordsEmbeddings()
    # ``run_extraction`` writes facts with the process-wide embeddings client;
    # point it at the runner's offline stub so no model is called.
    monkeypatch.setattr(
        "aura.llm.embeddings.get_embeddings_client", lambda: embeddings
    )
    return db, embeddings


async def _run_turns(
    db: EmbeddedSurrealDB,
    embeddings: HashedBagOfWordsEmbeddings,
    turns: list[_Turn],
) -> FakeClock:
    """Store each turn, run its scripted extraction, and return the clock."""
    ordered = sorted(turns, key=lambda turn: turn.at_day)
    client = ScriptedExtractionClient([turn.extraction for turn in ordered])

    clock = FakeClock(_START)
    set_clock(clock)
    for turn in ordered:
        clock.set(_START + timedelta(days=turn.at_day))
        episode_id = await store_episode(
            db,
            embeddings,
            user_text=turn.text,
            aura_text="Aura replies.",
            speaker=turn.speaker,
            venue=turn.venue,
            conversation_id=turn.conversation_id,
            emotional_signature={"joy": 0.2},
            salience=0.4,
        )
        result = await run_extraction(db, client, episode_id)
        assert result is not None, f"extraction failed for {turn.text!r}"

    assert client.calls == len(ordered)
    return clock


def _request(venue: str, question: str, user_id: str = "owner") -> RecallRequest:
    return RecallRequest(
        user_id=user_id,
        user_input=question,
        limit=5,
        include_cold_start=False,
        include_latent=False,
        token_budget=100_000,
        venue=venue,
    )


async def _recall(
    db: EmbeddedSurrealDB,
    venue: str,
    question: str,
    *,
    user_id: str = "owner",
) -> Any:
    engine = RecallEngine(
        memory_manager=_build_manager(db), latent_engine=StubLatentEngine()
    )
    return await engine.recall(_request(venue, question, user_id))


def _memories(packet: Any) -> str:
    """The memories block text, treating an abstention as empty for checks."""
    return packet.block_text("memories") or ""


# ---------------------------------------------------------------------------
# Updated fact and history
# ---------------------------------------------------------------------------


def _lisbon_extraction() -> Extraction:
    return _extraction(
        [{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
        [
            _fact(
                content="I live in Lisbon.",
                subject="I",
                predicate="live in",
                object="Lisbon",
                about=["Lisbon"],
            )
        ],
    )


def _porto_extraction() -> Extraction:
    return _extraction(
        [{"name": "Porto", "type": "place", "surface": "Porto"}],
        [
            _fact(
                # The turn said "I moved to Porto."; the extracted fact is
                # one self-contained sentence, as the extraction prompt asks.
                content="I live in Porto now.",
                subject="I",
                predicate="live in",
                object="Porto",
                about=["Porto"],
            )
        ],
    )


async def _lisbon_then_porto(
    db: EmbeddedSurrealDB,
    embeddings: HashedBagOfWordsEmbeddings,
) -> FakeClock:
    return await _run_turns(
        db,
        embeddings,
        [
            _Turn(0, "I live in Lisbon.", _lisbon_extraction()),
            _Turn(10, "I moved to Porto.", _porto_extraction()),
        ],
    )


@pytest.mark.asyncio
async def test_updated_fact_recalls_porto_and_not_lisbon(monkeypatch):
    db, embeddings = await _open(monkeypatch)
    try:
        clock = await _lisbon_then_porto(db, embeddings)

        clock.set(_START + timedelta(days=11))
        memories = _memories(await _recall(db, "app", "where do I live?"))

        assert "Porto" in memories
        assert "Lisbon" not in memories
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_history_supersedes_chain_leads_from_porto_to_lisbon(monkeypatch):
    db, embeddings = await _open(monkeypatch)
    try:
        await _lisbon_then_porto(db, embeddings)

        facts = await db.query(
            "SELECT * FROM fact ORDER BY recorded_at ASC"
        )
        lisbon = next(fact for fact in facts if fact["object"] == "Lisbon")
        porto = next(fact for fact in facts if fact["object"] == "Porto")

        edges = await db.query(
            "SELECT * FROM supersedes WHERE in = $porto",
            {"porto": porto["id"]},
        )
        assert len(edges) == 1
        assert edges[0]["out"] == lisbon["id"]

        # The chain closes the old fact and leaves only the new one current.
        assert lisbon.get("valid_to") is not None
        assert porto.get("valid_to") is None
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guest_dm_fact_stays_out_of_the_app_and_guilds(monkeypatch):
    db, embeddings = await _open(monkeypatch)
    try:
        await _run_turns(
            db,
            embeddings,
            [
                _Turn(
                    0,
                    "My bicycle is blue.",
                    _extraction(
                        [
                            {
                                "name": "bicycle",
                                "type": "other",
                                "surface": "my bicycle",
                            }
                        ],
                        [
                            _fact(
                                content="My bicycle is blue.",
                                subject="my bicycle",
                                predicate="is",
                                object="blue",
                                about=["bicycle"],
                            )
                        ],
                    ),
                    speaker="discord_42",
                    venue="dm:discord_42",
                    conversation_id="dm-42",
                )
            ],
        )

        own_venue = _memories(
            await _recall(
                db,
                "dm:discord_42",
                "What colour is my bicycle?",
                user_id="discord_42",
            )
        )
        assert "bicycle" in own_venue

        for venue in ("app", "guild:99/channel:1"):
            other_venue = _memories(
                await _recall(db, venue, "What colour is my bicycle?")
            )
            assert "bicycle" not in other_venue
            assert "blue" not in other_venue
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_guild_fact_stays_out_of_another_guild(monkeypatch):
    db, embeddings = await _open(monkeypatch)
    try:
        await _run_turns(
            db,
            embeddings,
            [
                _Turn(
                    0,
                    "Guild Alpha's mascot is a fox.",
                    _extraction(
                        [{"name": "fox", "type": "other", "surface": "fox"}],
                        [
                            _fact(
                                content="Guild Alpha's mascot is a fox.",
                                subject="Guild Alpha's mascot",
                                predicate="is",
                                object="fox",
                                about=["fox"],
                            )
                        ],
                    ),
                    venue="guild:99/channel:7",
                    conversation_id="guild-99",
                )
            ],
        )

        own_guild = _memories(
            await _recall(db, "guild:99/channel:8", "What is the mascot?")
        )
        assert "mascot" in own_guild

        other_guild = _memories(
            await _recall(db, "guild:100/channel:8", "What is the mascot?")
        )
        assert "mascot" not in other_guild
        assert "fox" not in other_guild
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# Hearsay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guest_hearsay_never_replaces_the_owner_fact(monkeypatch):
    monkeypatch.setattr(settings, "owner_display_name", "Mai")
    monkeypatch.setattr(settings, "owner_aliases", [])

    db, embeddings = await _open(monkeypatch)
    try:
        await ensure_person(db, "owner", "Mai")
        venue = "guild:99/channel:7"

        await _run_turns(
            db,
            embeddings,
            [
                _Turn(
                    0,
                    "I live in Lisbon.",
                    _lisbon_extraction(),
                    venue=venue,
                    conversation_id="guild-99",
                ),
                _Turn(
                    timedelta(hours=1).total_seconds() / 86400,
                    "Mai lives in Berlin.",
                    _extraction(
                        [
                            {"name": "Mai", "type": "person", "surface": "Mai"},
                            {
                                "name": "Berlin",
                                "type": "place",
                                "surface": "Berlin",
                            },
                        ],
                        [
                            _fact(
                                content="Mai lives in Berlin.",
                                subject="Mai",
                                predicate="live in",
                                object="Berlin",
                                about=["Berlin"],
                            )
                        ],
                    ),
                    speaker="discord_42",
                    venue=venue,
                    conversation_id="guild-99",
                ),
            ],
        )

        facts = await db.query(
            "SELECT * FROM fact ORDER BY recorded_at ASC"
        )
        observed = next(fact for fact in facts if fact["object"] == "Lisbon")
        hearsay = next(fact for fact in facts if fact["object"] == "Berlin")

        assert observed["provenance"] == "observed"
        assert observed.get("valid_to") is None
        assert hearsay["provenance"] == "hearsay"
        assert hearsay.get("valid_to") is None

        # The guest's claim is a conflict, never a replacement.
        assert await db.query("SELECT * FROM supersedes") == []
        contradicts = await db.query("SELECT * FROM contradicts")
        assert len(contradicts) == 1
        assert contradicts[0]["in"] == hearsay["id"]
        assert contradicts[0]["out"] == observed["id"]

        # The owner's fact is still what the guild recalls.
        memories = _memories(
            await _recall(db, venue, "Where does Mai live?")
        )
        assert "Lisbon" in memories
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# Stale-fact rate
# ---------------------------------------------------------------------------


def _setting_extraction(index: int, suffix: str) -> Extraction:
    entity = f"setting {index}"
    option = f"option {index}{suffix}"
    return _extraction(
        [{"name": entity, "type": "concept", "surface": entity}],
        [
            _fact(
                content=f"My {entity} is {option}.",
                subject="I",
                predicate=entity,
                object=option,
                about=[entity],
            )
        ],
    )


@pytest.mark.asyncio
async def test_stale_fact_rate_stays_under_two_percent(monkeypatch):
    measured_on = get_clock().now().date().isoformat()

    db, embeddings = await _open(monkeypatch)
    try:
        # 30 facts are stated (hours 0..29), then 10 of them are updated
        # (hours 30..39): 40 turns with 10 updates.
        turns = [
            _Turn(
                hour / 24,
                f"My setting {index} is option {index}a.",
                _setting_extraction(index, "a"),
                conversation_id="settings",
            )
            for hour, index in enumerate(range(1, 31))
        ]
        turns += [
            _Turn(
                (30 + offset) / 24,
                f"My setting {index} is option {index}b.",
                _setting_extraction(index, "b"),
                conversation_id="settings",
            )
            for offset, index in enumerate(range(1, 11))
        ]

        clock = await _run_turns(db, embeddings, turns)

        facts = await db.query(
            "SELECT * FROM fact ORDER BY recorded_at ASC"
        )
        assert len(facts) == 40
        assert len([fact for fact in facts if fact.get("valid_to") is None]) == 30
        assert len([fact for fact in facts if fact.get("valid_to") is not None]) == 10

        # Recall once per scripted turn and collect every fact that reaches
        # the memories block.
        engine = RecallEngine(
            memory_manager=_build_manager(db), latent_engine=StubLatentEngine()
        )
        recalled_ids: list[str] = []
        for turn in turns:
            clock.set(_START + timedelta(days=turn.at_day))
            packet = await engine.recall(
                _request("app", turn.text)
            )
            for item in packet.trace.items:
                if (
                    item.block == "memories"
                    and item.source == "recall.facts"
                    and item.fate == "kept"
                ):
                    recalled_ids.append(
                        item.key.replace("⟨", "").replace("⟩", "")
                    )

        total_recalled = len(recalled_ids)
        assert total_recalled > 0

        valid_to_by_id = {
            str(fact["id"]).replace("⟨", "").replace("⟩", ""): fact.get(
                "valid_to"
            )
            for fact in facts
        }
        superseded_recalled = sum(
            1
            for fact_id in recalled_ids
            if valid_to_by_id.get(fact_id) is not None
        )
        stale_fact_rate = superseded_recalled / total_recalled
        assert stale_fact_rate < 0.02

        data = {
            "card": "W3-18",
            "date": measured_on,
            "turns": len(turns),
            "updates": 10,
            "recalled_facts": total_recalled,
            "superseded_recalled_facts": superseded_recalled,
            "stale_fact_rate": round(stale_fact_rate, 4),
            "flags": {
                "memory_v2_write_enabled": True,
                "memory_v2_recall_enabled": True,
                "recall_channels_enabled": True,
                "recall_gate_enabled": True,
                "recall_abstain_enabled": True,
            },
        }
        written = write_baseline(_M4_METRICS_PATH, data)
        if written:
            assert _M4_METRICS_PATH.exists()
    finally:
        await db.close()
        set_clock(Clock())