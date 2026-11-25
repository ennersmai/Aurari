"""P2-28: Diverge. Offline: a fake plain-call client and the embedded SurrealDB with the real schema."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.creativity import dedupe as dd
from aura.engines.creativity import lineage
from aura.engines.creativity.lenses import LENSES, choose_lenses
from aura.engines.creativity.lineage import LineageStore
from aura.engines.learning.skill_store import SkillStore
from aura.executor.tool_registry import (
    get_tool_registry,
    load_builtin_tools,
    reset_tool_registry,
)
from aura.tiers import reset_tier_cache
from aura.tools import consult, diverge, record_final_ideas, record_seed_ideas
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
TOOL_NAMES = {"record_seed_ideas", "diverge", "record_final_ideas"}
POOL = ["a/one", "b/two", "c/three"]


class FakeLayers:
    """Three ideas per call, built from the lens named in the prompt. The first idea of
    every call is the same sentence, so cross-lens duplicates exist."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def plain_call(self, model, system, user, max_tokens, temperature):
        self.calls.append({"model": model, "user": user})
        key = next(k for k, text in LENSES.items() if text in user)
        word = key.split("_")[0]
        return (
            "1. a shared obvious notion about gardens\n"
            f"- {word}1 {word}2 {word}3 {word}4 wild plan alpha with {model.split('/')[0]}\n"
            f"* {word}5 {word}6 {word}7 {word}8 odd plan beta for {model.split('/')[0]}\n"
            "4. a fourth idea that must be cut"
        )


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    set_clock(FakeClock(_START))
    reset_tier_cache()
    reset_tool_registry()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "tier_overrides.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "consult_enabled", True)
    monkeypatch.setattr(settings, "diverge_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 2)  # Titan: 8 swift per turn
    monkeypatch.setattr(settings, "swift_pool2", list(POOL))
    consult.begin_turn()
    diverge._rng = random.Random(7)
    yield
    set_clock(Clock())
    reset_tier_cache()
    reset_tool_registry()


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    monkeypatch.setattr(lineage, "get_db_client", lambda: d)
    yield d
    await d.close()


@pytest.fixture
def layers(monkeypatch):
    fake = FakeLayers()
    monkeypatch.setattr(consult, "_get_layers", lambda: fake)
    return fake


OWNER = {"_requester_role": "owner"}
SEEDS = ["write a poem about gardens", "make a garden app", "plant more trees"]


async def seed_run(ideas=None):
    out = await record_seed_ideas.run(
        {"question": "ideas for a garden project", "ideas": ideas or SEEDS, **OWNER}
    )
    assert out["success"], out
    return out


# ----------------------------------------------------------------------------- dedupe


def test_dedupe_word_set_jaccard_above_threshold():
    assert dd.jaccard("a b c d e", "a b c d e") == 1.0
    assert dd.same_idea("plant a tree in the park today", "plant a tree in the park now")  # 6/8
    assert not dd.same_idea("plant a tree", "build a robot")
    # exactly at the threshold is not the same idea: 3 shared of 5 words = 0.6
    assert dd.jaccard("a b c d", "a b c e") == 0.6
    assert not dd.same_idea("a b c d", "a b c e")
    assert dd.dedupe(["a b c d e f", "a b c d e f g", "x y z", "A B C D E F"]) == [None, 0, None, 0]


def test_dedupe_threshold_is_a_setting(monkeypatch):
    monkeypatch.setattr(settings, "diverge_jaccard", 0.4)
    assert dd.same_idea("a b c d", "a b c e")


# ------------------------------------------------------------------- lineage and flow


async def test_flow_records_lineage_and_hides_seeds(db, layers):
    run_id = (await seed_run())["run_id"]
    out = await diverge.run({"run_id": run_id, **OWNER})
    assert out["success"], out
    assert out["calls"] == 5 and len(layers.calls) == 5
    assert len({c["model"] for c in layers.calls}) == 3  # diverse pool
    # the seeds never reach the helpers or the tool result
    for seed in SEEDS:
        assert seed not in out["message"]
        assert all(seed not in c["user"] for c in layers.calls)
    # 5 lenses x 3 kept ideas = 15; the shared sentence is deduped to one
    assert out["candidates"] == 11 and out["duplicates_removed"] == 4
    assert "a fourth idea that must be cut" not in out["message"]

    store = LineageStore(db)
    cands = [c for c in await store.ideas(run_id, "candidate") if c.get("duplicate_of") is None]
    keep = {c["lens"]: c for c in cands if "plan alpha" in c["text"]}
    assert set(keep) == set(list(LENSES)[:5])
    pick = [cands[0]["id"], cands[1]["id"]]
    seed_ids = [s["id"] for s in await store.ideas(run_id, "seed")]
    fin = await record_final_ideas.run({
        "run_id": run_id, **OWNER,
        "ideas": [{"text": "a sharpened mix of two", "sources": pick + [seed_ids[0]]}],
    })
    assert fin["success"], fin
    tree = await store.tree(run_id)
    final = tree["finals"][0]
    assert [s["id"] for s in final["sources"]] == pick + [seed_ids[0]]
    first = final["sources"][0]
    assert first["model"] in POOL and first["lens"] in LENSES and first["role"] == "candidate"
    assert final["sources"][2]["role"] == "seed"
    assert final["overlaps_seed"] is False
    assert len(tree["seeds"]) == 3 and tree["novelty"] == 1.0
    # the run is exhausted: no second explore, no second final
    assert not (await diverge.run({"run_id": run_id, **OWNER}))["success"]
    assert not (await record_final_ideas.run({"run_id": run_id, "ideas": [], **OWNER}))["success"]
    # consult trace records carry the lens
    assert {r["lens"] for r in consult.turn_records() if r["tool"] == "diverge"} == set(keep)


async def test_novelty_is_share_of_finals_not_overlapping_seeds(db, layers):
    run_id = (await seed_run())["run_id"]
    await diverge.run({"run_id": run_id, **OWNER})
    store = LineageStore(db)
    src = [(await store.ideas(run_id, "candidate"))[1]["id"]]
    out = await record_final_ideas.run({
        "run_id": run_id, **OWNER,
        "ideas": [
            {"text": "write a poem about gardens today", "sources": src},  # 5/6 of seed 0
            {"text": "an orbiting mushroom library", "sources": src},
            {"text": "a seed bank run by pigeons", "sources": src},
            {"text": "make a garden app", "sources": []},
        ],
    })
    assert out["overlaps_seed"] == [True, False, False, True]
    assert out["novelty"] == pytest.approx(0.5)
    assert (await store.get_run(run_id))["novelty"] == pytest.approx(0.5)


async def test_candidate_overlapping_a_seed_is_flagged(db, layers):
    run_id = (await seed_run(["a shared obvious notion about gardens", "x y", "z w"]))["run_id"]
    await diverge.run({"run_id": run_id, **OWNER})
    cands = await LineageStore(db).ideas(run_id, "candidate")
    assert any(c["overlaps_seed"] for c in cands)
    assert not all(c["overlaps_seed"] for c in cands)


async def test_yield_updates_per_model_and_lens(db, layers):
    store = LineageStore(db)
    run_id = (await seed_run())["run_id"]
    await diverge.run({"run_id": run_id, **OWNER})
    cands = [c for c in await store.ideas(run_id, "candidate") if c.get("duplicate_of") is None]
    winner = next(c for c in cands if "plan alpha" in c["text"])
    await record_final_ideas.run({
        "run_id": run_id, **OWNER, "ideas": [{"text": "unique final", "sources": [winner["id"]]}],
    })
    yields = await store.lens_yields()
    # offered counts every candidate of the (model, lens), duplicates included
    assert sum(o for o, _ in yields.values()) == 15
    assert yields[(winner["model"], winner["lens"])] == (3, 1)
    assert sum(s for _, s in yields.values()) == 1
    # a second run accumulates on the same rows
    consult.begin_turn()
    run2 = (await seed_run())["run_id"]
    await diverge.run({"run_id": run2, **OWNER})
    c2 = next(c for c in await store.ideas(run2, "candidate") if "plan alpha" in c["text"])
    await record_final_ideas.run({
        "run_id": run2, **OWNER, "ideas": [{"text": "second final", "sources": [c2["id"]]}],
    })
    after = await store.lens_yields()
    assert sum(o for o, _ in after.values()) == 30
    assert sum(s for _, s in after.values()) == 2
    assert all(o >= s for o, s in after.values())


def test_lens_choice_default_weighted_and_exploring(monkeypatch):
    rng = random.Random(1)
    assert choose_lenses({}, 5, rng) == list(LENSES)[:5]
    # lens "invert" has a very high yield, "worst_idea" a very low one
    yields = {("m", k): (50, 0) for k in LENSES}
    yields[("m", "invert")] = (50, 50)
    top = sum("invert" in choose_lenses(yields, 1, rng, exploration_rate=0.0) for _ in range(300))
    low = sum("worst_idea" in choose_lenses(yields, 1, rng, exploration_rate=0.0) for _ in range(300))
    assert top > 150 and low < 20
    # with exploration 1.0 a lens with no data and low yield still gets drawn, and extras appear
    seen = {k for _ in range(200) for k in choose_lenses(yields, 5, rng, exploration_rate=1.0)}
    assert seen == set(LENSES)
    assert len(set(choose_lenses(yields, 5, rng))) == 5  # distinct


async def test_next_run_uses_yield_weighted_lenses(db, layers, monkeypatch):
    store = LineageStore(db)
    await store._bump_yield("a/one", "invert", 100, 100)
    for key in LENSES:
        if key != "invert":
            await store._bump_yield("a/one", key, 100, 0)
    monkeypatch.setattr(settings, "diverge_exploration_rate", 0.0)
    run_id = (await seed_run())["run_id"]
    out = await diverge.run({"run_id": run_id, **OWNER})
    assert out["lenses"][0] == "invert"


# ---------------------------------------------------------------------------- guards


async def test_guards(db, layers):
    assert not (await record_seed_ideas.run({"question": "q", "ideas": SEEDS}))["success"]  # not owner
    bad = await record_seed_ideas.run({"question": "q", "ideas": SEEDS[:2], **OWNER})
    assert not bad["success"] and "exactly 3" in bad["message"]
    assert not (await diverge.run({"run_id": "creative_run:nope", **OWNER}))["success"]
    assert not (await diverge.run({"run_id": 5, **OWNER}))["success"]
    run_id = (await seed_run())["run_id"]
    assert not (await diverge.run({"run_id": run_id}))["success"]
    assert layers.calls == []
    assert not (await record_final_ideas.run({"run_id": run_id, "ideas": [
        {"text": "x", "sources": ["creative_idea:forged"]}], **OWNER}))["success"]
    assert not (await record_final_ideas.run({"run_id": run_id, "ideas": [
        {"text": "x", "sources": []}] * 9, **OWNER}))["success"]


async def test_swift_turn_limit_caps_lenses(db, layers, monkeypatch):
    run_id = (await seed_run())["run_id"]
    consult._state().swift_used = 6  # Titan allows 8: two left
    out = await diverge.run({"run_id": run_id, **OWNER})
    assert out["success"] and out["calls"] == 2 and len(layers.calls) == 2
    consult.begin_turn()
    run2 = (await seed_run())["run_id"]
    consult._state().swift_used = 8
    assert not (await diverge.run({"run_id": run2, **OWNER}))["success"]


async def test_failed_helpers_store_nothing(db, monkeypatch):
    class Boom:
        async def plain_call(self, *a, **k):
            raise RuntimeError("down")

    monkeypatch.setattr(consult, "_get_layers", lambda: Boom())
    run_id = (await seed_run())["run_id"]
    out = await diverge.run({"run_id": run_id, **OWNER})
    assert not out["success"]
    assert await LineageStore(db).ideas(run_id, "candidate") == []


# --------------------------------------------------------------------------- ablation


async def test_flag_off_hides_tools_and_makes_no_calls(db, layers, monkeypatch):
    monkeypatch.setattr(settings, "diverge_enabled", False)
    for tool, args in (
        (record_seed_ideas, {"question": "q", "ideas": SEEDS}),
        (diverge, {"run_id": "creative_run:x"}),
        (record_final_ideas, {"run_id": "creative_run:x", "ideas": []}),
    ):
        out = await tool.run({**args, **OWNER})
        assert not out["success"] and "turned off" in out["message"]
    assert layers.calls == []
    assert await db.query("SELECT * FROM creative_run", {}) == []
    reg = get_tool_registry()
    reg._records = {r.name: r for r in load_builtin_tools()}
    assert TOOL_NAMES.isdisjoint({r.name for r in reg.all()})
    monkeypatch.setattr(settings, "diverge_enabled", True)
    assert TOOL_NAMES <= {r.name for r in reg.all()}
    monkeypatch.setattr(settings, "consult_enabled", False)  # rides on consult
    assert TOOL_NAMES.isdisjoint({r.name for r in reg.all()})


# ------------------------------------------------------------------------ skill file


async def test_seed_diverge_skill_once(db):
    store = SkillStore(db)
    doc = await diverge.seed_diverge_skill(store)
    assert doc.name == "diverge" and doc.state == "trusted" and doc.active_version == 1
    version = await store.get_version(doc.id, 1)
    assert version.approved_at == _START and set(version.tools) == TOOL_NAMES
    assert "—" not in version.body and "—" not in doc.when_to_use
    assert "never show them" in version.body
    assert (await diverge.seed_diverge_skill(store)).id == doc.id
    assert len(await store.list_versions(doc.id)) == 1


def test_prompts_have_no_em_dash():
    texts = list(LENSES.values()) + [diverge.helper_task("q"), diverge.TOOL_DEFINITION["description"],
                                     record_seed_ideas.TOOL_DEFINITION["description"],
                                     record_final_ideas.TOOL_DEFINITION["description"]]
    assert all("—" not in t for t in texts)
