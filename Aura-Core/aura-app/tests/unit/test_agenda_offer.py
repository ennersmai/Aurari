"""B5-04: working-set offer inside the reply (embedded SurrealDB, real schema)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.autonomy import agenda as agenda_mod
from aura.autonomy import channel, learning, offer, trace
from aura.autonomy.agenda import AgendaService
from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.engines.memory.manager import MemoryManager
from aura.engines.recall.engine import RecallEngine
from aura.engines.recall.models import RecallRequest
from aura.models.memory import ColdStartContext
from tests.scenarios.runner import EmbeddedSurrealDB

_NOON = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _restore_clock():
    yield
    set_clock(Clock())


class CountingDB:
    """Wraps the embedded db and counts queries."""

    def __init__(self, inner):
        self.inner = inner
        self.queries: list[str] = []

    async def query(self, sql, vars=None):
        self.queries.append(sql)
        return await self.inner.query(sql, vars)


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_NOON))
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "interruptibility_model_enabled", True)
    monkeypatch.setattr(settings, "dismissal_learning_enabled", True)
    for mod in (agenda_mod, trace, learning):
        monkeypatch.setattr(mod, "get_db_client", lambda d=d: d)
    learning.reset_cache()
    channel.reset()
    offer.reset()
    yield d
    offer.reset()
    learning.reset_cache()
    channel.reset()
    await d.close()


async def _mk(svc, content, refs=("proj",), kind="finding", priority=0.6):
    return await svc.create(kind, content, list(refs), priority, source="aura")


async def _settle():
    if offer._bg:
        await asyncio.gather(*list(offer._bg))


async def test_matching_item_offered_unrelated_not(env):
    svc = AgendaService(env)
    hit = await _mk(svc, "The tax spreadsheet has a mismatch in March", refs=("spreadsheet",))
    miss = await _mk(svc, "Garden watering schedule is ready", refs=("garden",))
    got = await offer.working_set_for_turn("u1", "can we look at the tax numbers again?", "owner")
    ids = [i for i, _ in got]
    assert hit.id in ids
    assert miss.id not in ids
    # entity/ref overlap alone also matches
    got = await offer.working_set_for_turn("u1", "How is the Spreadsheet doing", "owner")
    assert hit.id in [i for i, _ in got]


async def test_block_absent_for_guest_and_flag_off(env, monkeypatch):
    svc = AgendaService(env)
    await _mk(svc, "The tax spreadsheet has a mismatch in March")
    assert await offer.working_set_for_turn("u1", "tax spreadsheet", "guest") == []
    assert await offer.working_set_for_turn("u1", "tax spreadsheet", "owner", venue="dm:1") == []
    for flag in ("interruptibility_model_enabled", "autonomy_enabled"):
        monkeypatch.setattr(settings, flag, False)
        assert await offer.working_set_for_turn("u1", "tax spreadsheet", "owner") == []
        monkeypatch.setattr(settings, flag, True)
    assert await offer.working_set_for_turn("u1", "tax spreadsheet", "owner") != []


async def test_orchestrator_hook_ablation(env, monkeypatch):
    from aura.orchestrator.coordinator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = MagicMock()
    await _mk(AgendaService(env), "The tax spreadsheet has a mismatch in March")
    assert await orch._working_set_offer("u1", "tax spreadsheet", "owner", "app")
    assert await orch._working_set_offer("u1", "tax spreadsheet", "guest", "app") == []
    monkeypatch.setattr(settings, "interruptibility_model_enabled", False)
    monkeypatch.setattr(offer, "relevant_items", AsyncMock(side_effect=AssertionError("called")))
    assert await orch._working_set_offer("u1", "tax spreadsheet", "owner", "app") == []


async def test_hot_path_one_indexed_query_bounded(env, monkeypatch):
    counting = CountingDB(env)
    svc = AgendaService(counting)
    for n in range(5):
        await _mk(AgendaService(env), f"tax spreadsheet note number {n}")
    got = await offer.relevant_items("tax spreadsheet", [], get_clock().now(), 3, service=svc)
    assert len(got) == 3
    assert len(counting.queries) == 1
    assert "state = 'pending'" in counting.queries[0] and "LIMIT $scan" in counting.queries[0]

    class Slow:
        db = None

    class SlowDB:
        async def query(self, sql, vars=None):
            await asyncio.sleep(1)

    monkeypatch.setattr(settings, "agenda_offer_timeout_ms", 20)
    slow = AgendaService(SlowDB())
    t0 = asyncio.get_running_loop().time()
    assert await offer.relevant_items("tax spreadsheet", [], get_clock().now(), 3, service=slow) == []
    assert asyncio.get_running_loop().time() - t0 < 0.5


async def test_expired_and_future_due_items_not_offered(env):
    svc = AgendaService(env)
    now = get_clock().now()
    await svc.create("reminder", "tax spreadsheet later", ["x"], 0.5, source="aura",
                     due_at=now + timedelta(hours=2))
    got = await offer.relevant_items("tax spreadsheet", [], now, 3, service=svc)
    assert got == []


async def test_offered_item_moves_to_delivered_on_next_message(env):
    svc = AgendaService(env)
    item = await _mk(svc, "The tax spreadsheet has a mismatch in March")
    got = await offer.working_set_for_turn("u1", "what about the tax spreadsheet", "owner")
    assert [i for i, _ in got] == [item.id]
    # still pending until the owner reacts
    assert (await svc.get(item.id)).state == "pending"
    await offer.working_set_for_turn("u1", "ok the tax mismatch is March, thanks", "owner")
    await _settle()
    after = await svc.get(item.id)
    assert after.state == "acknowledged"
    assert after.delivered_at is not None
    stats = await learning.get_stats("finding", env)
    assert stats.acknowledged == 1 and stats.delivered == 1


async def test_unrelated_next_message_leaves_item_pending(env):
    svc = AgendaService(env)
    item = await _mk(svc, "The tax spreadsheet has a mismatch in March")
    await offer.working_set_for_turn("u1", "tax spreadsheet please", "owner")
    await offer.working_set_for_turn("u1", "what is the weather like", "owner")
    await _settle()
    assert (await svc.get(item.id)).state == "pending"


async def test_recall_packet_carries_labelled_block():
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = AsyncMock()
    mm.embeddings = None
    mm.retrieve_for_l3_parts = AsyncMock(return_value=([], {}))
    mm.get_cold_start_context = AsyncMock(return_value=ColdStartContext())
    latent = MagicMock()
    latent.get_intuition_context.return_value = ""
    engine = RecallEngine(memory_manager=mm, latent_engine=latent)
    packet = await engine.recall(RecallRequest(
        user_id="u1", user_input="tax", working_set=[("agenda_item:a", "[finding] tax mismatch")],
    ))
    text = packet.block_text("working_set")
    assert text and "holding for the owner" in text and "[finding] tax mismatch" in text
    off = await engine.recall(RecallRequest(user_id="u1", user_input="tax"))
    assert off.block_text("working_set") is None
