"""Skill index, selection and default context (G5-05, agency PRD 6.1 and 6.3).

Only ``name`` and ``when_to_use`` of live skills go into the prompt by default
(``render_index``); the body of the one chosen skill is loaded on top
(``load_body``). Selection is pure and seedable: cosine against
``when_embedding``, a relevance floor, then Thompson sampling over the active
version and, while it is on trial, the previous one. No LLM call anywhere.

Live means: doc state ``candidate`` or ``trusted`` (not ``retired``), and the
version has ``approved_at`` and is not ``rejected``. Unapproved candidates and
rejected (or rolled back) versions never appear, neither in the index nor as an
arm.

Who sees skills (``select_for_turn``): owner turns only. A guest requester gets
no index and no body. Sub-sessions are allowed, but the caller passes
``tool_allowed`` (the session's allowlist and denylist plus the tier's gated
tools) and it is applied to each version's ``tools``: a skill needing a tool the
session or tier disallows is skipped, both as an arm and in the index. A skill
that came from a guest conversation is selectable only because the owner
approved it (it is live only with ``approved_at``).

P2-20 hooks: ``candidates``, ``SkillStub``, ``render_index`` and ``load_body``
are the pieces a shared presence budget can place at ``full``, ``stub`` or
``absent``; ``select_for_turn`` returns the stubs and the body separately.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import numpy as np

from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.engines.learning.skill_stats import beta_params, mastery
from aura.engines.learning.skill_store import SkillStore, _to_doc, _to_version
from aura.models.learning import SkillDoc, SkillVersion

logger = logging.getLogger(__name__)


def selection_enabled() -> bool:
    """Both flags are needed (G5-05 config)."""
    return bool(settings.skills_v2_enabled and settings.skill_selection_enabled)


@dataclass(frozen=True)
class SkillStub:
    name: str
    one_line: str
    tags: list[str]
    version: int
    mastery: float  # lower bound of the Beta posterior (G5-04)


@dataclass
class SkillCandidate:
    doc: SkillDoc
    similarity: float
    versions: dict[int, SkillVersion] = field(default_factory=dict)  # live versions only


@dataclass
class TurnSkills:
    """What a turn gets: index stubs, the chosen skill and its body."""

    stubs: list[SkillStub] = field(default_factory=list)
    chosen: tuple[str, int] | None = None  # (doc id, version)
    chosen_name: str | None = None
    body: str = ""

    @property
    def index_text(self) -> str:
        return render_index(self.stubs)


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


def render_index(stubs: list[SkillStub]) -> str:
    """One line per skill, ``name: when_to_use``; empty string for no stubs."""
    return "\n".join(f"{s.name}: {s.one_line}" for s in stubs)


async def candidates(
    request_embedding: list[float], store: SkillStore | None = None
) -> list[SkillCandidate]:
    """All live skills with their live versions, most similar first.

    No floor and no cap here: the index takes the top ``skill_index_max``, the
    sampler the floor and ``skill_candidates_max``. Ties break by name.
    """
    store = store or SkillStore()
    query = np.asarray(request_embedding, dtype=float)
    qn = float(np.linalg.norm(query))
    if qn == 0.0:
        return []
    doc_rows = extract_rows(
        await store.db.query(
            "SELECT * FROM skill_doc WHERE state != 'retired' AND when_embedding != NONE"
        )
    )
    version_rows = extract_rows(
        await store.db.query(
            "SELECT * FROM skill_version WHERE approved_at != NONE AND rejected = false"
        )
    )
    live: dict[str, dict[int, SkillVersion]] = {}
    for row in version_rows:
        v = _to_version(row)
        live.setdefault(v.skill, {})[v.version] = v
    out: list[SkillCandidate] = []
    for row in doc_rows:
        emb = row.get("when_embedding")
        if not emb or len(emb) != len(query):
            continue
        vec = np.asarray(emb, dtype=float)
        vn = float(np.linalg.norm(vec))
        if vn == 0.0:
            continue
        doc = _to_doc(row)
        versions = live.get(doc.id)
        if not versions:
            continue
        out.append(SkillCandidate(doc, float(np.dot(query, vec) / (qn * vn)), versions))
    out.sort(key=lambda c: (-c.similarity, c.doc.name))
    return out


async def load_body(name: str, version: int, store: SkillStore | None = None) -> str:
    """Body of a live version; empty string when the skill or version is not live."""
    store = store or SkillStore()
    doc = await store.get_doc(name)
    if doc is None or doc.state == "retired":
        return ""
    ver = await store.get_version(doc.id, version)
    if ver is None or ver.rejected or ver.approved_at is None:
        return ""
    return ver.body


def _arms(cand: SkillCandidate, tool_allowed: Callable[[str], bool] | None) -> list[SkillVersion]:
    """Active version, plus the previous one while the active one is on trial."""
    doc = cand.doc
    active = cand.versions.get(doc.active_version) if doc.active_version is not None else None
    if active is None:
        return []
    arms = [active]
    if (
        doc.previous_version is not None
        and doc.previous_version != active.version
        and active.attempts < settings.skill_trial_attempts
        and doc.previous_version in cand.versions
    ):
        arms.append(cand.versions[doc.previous_version])
    if tool_allowed is not None:
        arms = [a for a in arms if all(tool_allowed(t) for t in a.tools)]
    return arms


def choose_skill(
    cands: list[SkillCandidate],
    rng: random.Random,
    tool_allowed: Callable[[str], bool] | None = None,
) -> tuple[SkillCandidate, SkillVersion] | None:
    """Pure selection (PRD 6.3). Keep candidates at or above the relevance floor
    (at most ``skill_candidates_max``, ordered by similarity), draw one value per
    arm from Beta(1 + successes, 1 + failures) with the injected generator, and
    take the highest draw. None when nothing passes the floor."""
    passing = [c for c in cands if c.similarity >= settings.skill_relevance_floor]
    best: tuple[float, SkillCandidate, SkillVersion] | None = None
    for cand in passing[: settings.skill_candidates_max]:
        for arm in _arms(cand, tool_allowed):
            a, b = beta_params(arm.attempts, arm.successes)
            draw = rng.betavariate(a, b)
            if best is None or draw > best[0]:
                best = (draw, cand, arm)
    return (best[1], best[2]) if best else None


def build_stubs(
    cands: list[SkillCandidate], tool_allowed: Callable[[str], bool] | None = None
) -> list[SkillStub]:
    """Stubs for the top ``skill_index_max`` live skills by relevance. A skill whose
    active version needs a disallowed tool is left out."""
    stubs: list[SkillStub] = []
    for cand in cands:
        if len(stubs) >= settings.skill_index_max:
            break
        active = (
            cand.versions.get(cand.doc.active_version)
            if cand.doc.active_version is not None
            else None
        )
        if active is None:
            continue
        if tool_allowed is not None and not all(tool_allowed(t) for t in active.tools):
            continue
        stubs.append(
            SkillStub(
                name=cand.doc.name,
                one_line=_one_line(cand.doc.when_to_use),
                tags=list(cand.doc.tags),
                version=active.version,
                mastery=mastery(active.attempts, active.successes)[1],
            )
        )
    return stubs


async def _request_embedding(
    text: str, embed: Callable[[str], Awaitable[Any]]
) -> list[float] | None:
    """One embeddings call with the configured timeout; None on any failure."""
    try:
        vec = await asyncio.wait_for(embed(text), timeout=settings.skill_embed_timeout_ms / 1000)
    except Exception as exc:  # includes TimeoutError: fall back to no skill
        logger.warning("Skill selection: request embedding unavailable (%s)", exc)
        return None
    return list(vec) if vec else None


async def select_for_turn(
    store: SkillStore,
    request_text: str,
    requester_role: str,
    rng: random.Random,
    *,
    embed: Callable[[str], Awaitable[Any]] | None = None,
    request_embedding: list[float] | None = None,
    tool_allowed: Callable[[str], bool] | None = None,
) -> TurnSkills:
    """Index stubs plus the chosen skill and its body for one turn, before the
    model call. Empty with a flag off, for a non-owner requester, or when no
    embedding is available. ``request_embedding`` is reused when the caller has
    one; otherwise ``embed`` is called once (an embeddings call, never an LLM)."""
    if not selection_enabled() or requester_role != "owner":
        return TurnSkills()
    if request_embedding is None:
        if embed is None:
            return TurnSkills()
        request_embedding = await _request_embedding(request_text, embed)
        if request_embedding is None:
            return TurnSkills()
    cands = await candidates(request_embedding, store)
    result = TurnSkills(stubs=build_stubs(cands, tool_allowed))
    picked = choose_skill(cands, rng, tool_allowed)
    if picked is not None:
        cand, arm = picked
        # The arm was read with the live versions, so it is the same body load_body
        # would return; no second query.
        if arm.body:
            result.chosen = (cand.doc.id, arm.version)
            result.chosen_name = cand.doc.name
            result.body = arm.body
    return result
