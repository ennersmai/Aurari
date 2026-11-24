"""Question scoring for curiosity (B4-01).

``score = learning_value * relevance * tractability``. Everything is rule
based and pure arithmetic on rows read once per call: no model call. Only
owner-visible questions are scored (guest questions are never scored or
investigated; PRD open item 4, confirm with Mai). Behind ``curiosity_enabled``.

Question rows carry no entity links, so a question's entities are the graph
entities (name or alias) that its text mentions.
"""

import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aura.config import settings
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows

ROUTES = ("search", "read", "ask_user", "park")
_OWNER_VISIBILITY = ("owner", "private:owner")
_PREFERENCE = re.compile(r"\b(prefer\w*|favou?rite|likes?|dislikes?|wants?)\b", re.I)
_EXTERNAL = re.compile(r"https?://|www\.|\b\w+\.(?:com|org|io|dev|net)\b", re.I)
_GOAL_WEIGHT, _RECENT_WEIGHT = 1.0, 0.5


@dataclass
class ScoredQuestion:
    id: Any
    content: str
    score: float
    relevance: float
    tractability: float
    route: str


def learning_value(question: dict[str, Any]) -> float:
    """Expected learning from answering ``question``.

    The constant 1.0 for now. B6 replaces this one function with prediction
    error based learning value; nothing else here should change.
    """
    return 1.0


def _mentions(text: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    low = text.lower()
    found = []
    for e in entities:
        for n in [e.get("name") or "", *(e.get("aliases") or [])]:
            n = n.strip().lower()
            if len(n) >= 3 and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", low):
                found.append(e)
                break
    return found


@dataclass
class Context:
    """Rows read once per scoring pass."""

    entities: list[dict[str, Any]]
    goal_entities: set[str]
    recent_entities: set[str]
    workspaces: dict[str, str]


async def load_context(db: Any) -> Context:
    entities = extract_rows(await db.query(
        "SELECT id, name, type, aliases FROM entity WHERE name != 'owner'"
    ))
    goals = extract_rows(await db.query(
        "SELECT name, description FROM goal WHERE status = 'active'"
    ))
    goal_ids: set[str] = set()
    for g in goals:
        text = f"{g.get('name') or ''} {g.get('description') or ''}"
        goal_ids.update(str(e["id"]) for e in _mentions(text, entities))
    recent_rows = extract_rows(await db.query(
        "SELECT ->mentions->entity AS ents FROM (SELECT id, recorded_at FROM episode "
        "ORDER BY recorded_at DESC LIMIT $n)",
        {"n": int(settings.curiosity_recent_episodes)},
    ))
    recent_ids = {str(x) for r in recent_rows for x in (r.get("ents") or [])}
    return Context(entities, goal_ids, recent_ids, dict(settings.workspaces or {}))


def relevance(question: dict[str, Any], ctx: Context) -> float:
    """Closeness to active goals and recent topics, in 0..1."""
    ents = _mentions(question.get("content") or "", ctx.entities)
    if not ents:
        return 0.0
    total = 0.0
    for e in ents:
        i = str(e["id"])
        total += max(_GOAL_WEIGHT if i in ctx.goal_entities else 0.0,
                     _RECENT_WEIGHT if i in ctx.recent_entities else 0.0)
    return min(1.0, total / len(ents))


def tractability(question: dict[str, Any], ctx: Context) -> tuple[float, str]:
    """Rule-based (tractability, route); no model call."""
    text = question.get("content") or ""
    ents = _mentions(text, ctx.entities)
    if _PREFERENCE.search(text) or any(e.get("type") == "person" for e in ents):
        return 1.0, "ask_user"
    low = text.lower()
    if any(n.lower() in low or p.lower() in low for n, p in ctx.workspaces.items()):
        return 1.0, "read"
    if _EXTERNAL.search(text) or any(e.get("type") == "tool" for e in ents):
        return 1.0, "search"
    return float(settings.curiosity_search_low_tractability), "search"


async def pick_questions(
    now: datetime,
    limit: int,
    db: Any = None,
    rng: random.Random | None = None,
) -> list[ScoredQuestion]:
    """Top scored open owner questions, with route; scores are written back."""
    if not settings.curiosity_enabled:
        return []
    db = db if db is not None else get_db_client()
    rows = extract_rows(await db.query(
        "SELECT * FROM question WHERE status = 'open' AND visibility IN $vis "
        "ORDER BY recorded_at, id",
        {"vis": list(_OWNER_VISIBILITY)},
    ))
    if not rows:
        return []
    ctx = await load_context(db)
    scored: list[ScoredQuestion] = []
    for q in rows:
        rel = relevance(q, ctx)
        trac, route = tractability(q, ctx)
        score = learning_value(q) * rel * trac
        parked = score < settings.curiosity_min_score
        scored.append(ScoredQuestion(q["id"], q.get("content") or "", score, rel, trac,
                                     "park" if parked else route))
        await db.query(
            "UPDATE $id SET score = $s, scored_at = $t, tractability = $tr, parked_reason = $pr",
            {"id": q["id"], "s": score, "t": now, "tr": trac,
             "pr": "below_minimum_score" if parked else None},
        )
    live = [s for s in scored if s.route != "park"]
    if settings.curiosity_random_choice:
        r = rng if rng is not None else random.Random(0)
        return r.sample(live, min(limit, len(live)))
    live.sort(key=lambda s: (-s.score, str(s.id)))
    return live[:limit]
