"""W1-14: a changed fact replaces the old one.

Memory PRD F5. Before this card, ``create_insight`` treated a semantically
similar insight above the deduplication threshold as a duplicate: it bumped
the existing insight's confidence and returned its id, no matter the insight
type. That meant a corrected fact ("The user lives in Sofia" -> "The user
lives in Varna") was silently dropped — the old, now-wrong fact stayed active
and the new one was never stored.

After W1-14, in the branch where a semantically similar insight is found above
the threshold and the insight type is ``FACT``: if the normalised content
differs, the new fact is stored as a new record, the old one is marked
``deprecated = true`` and gets ``superseded_by`` pointing at the new id. For
every other insight type today's behaviour (bump confidence, return the
existing id) is unchanged. The deduplication threshold function is untouched.

The test drives the real ``LearningEngine.create_insight`` against a minimal
in-memory database whose semantic-similarity query computes a real cosine so
the supersession branch is exercised end-to-end:

* "The user lives in Sofia" then "The user lives in Varna" leaves one active
  fact (Varna); the Sofia record is ``deprecated`` and its ``superseded_by``
  points at the Varna record's id.
* Repeating the same fact twice still leaves a single record (the existing
  exact-match dedup path).
"""

import math
import re

import pytest

from aura.engines.learning.engine import LearningEngine


# ---------------------------------------------------------------------------
# Deterministic embedding stub
# ---------------------------------------------------------------------------

# A small set of "structure" words weighted heavily so two sentences that
# differ by one content word ("Sofia" vs "Varna") still score above the
# dynamic dedup threshold (>= 0.90). Content words default to weight 1.
_WEIGHTED = {"the": 10, "user": 10, "users": 10, "lives": 10, "live": 10,
             "in": 10, "of": 10, "a": 10, "is": 10, "name": 10}


class _StubEmbeddings:
    """Deterministic bag-of-words embeddings, no network, no model.

    Each word maps to its own dimension in a single growing index shared
    across calls, so every returned vector has the same length and cosine
    similarity is well-defined between embeddings produced at different
    times. Structure words (``_WEIGHTED``) get weight 10; every other word
    gets weight 1. Two sentences sharing their structure words therefore
    have high cosine similarity even when their content words differ, which
    is what lets the Varna fact enter the supersession branch against the
    stored Sofia fact.
    """

    def __init__(self):
        self._index: dict[str, int] = {}

    async def embed(self, content: str) -> list[float]:
        # Grow the index for any new words first, so the vector length covers
        # every dimension seen so far (vectors from earlier calls stay
        # comparable).
        for word in re.findall(r"[a-zA-Z]+", content.lower()):
            if word not in self._index:
                self._index[word] = len(self._index)
        vec = [0.0] * len(self._index)
        for word in re.findall(r"[a-zA-Z]+", content.lower()):
            vec[self._index[word]] += _WEIGHTED.get(word, 1)
        return vec


def _cosine(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2:
        return 0.0
    # Bags of words may have different lengths because the index grows per
    # embed call; align on the shorter (extra dims are zero for the other).
    n = min(len(v1), len(v2))
    dot = sum(v1[i] * v2[i] for i in range(n))
    n1 = math.sqrt(sum(x * x for x in v1))
    n2 = math.sqrt(sum(x * x for x in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


# ---------------------------------------------------------------------------
# Minimal in-memory database for create_insight
# ---------------------------------------------------------------------------

_INSIGHT_TABLE = "insight"


class _FakeInsightDB:
    """Recognises only the queries ``create_insight`` issues.

    * the all-active-by-type SELECT (exact/substring dedup),
    * the semantic-similarity SELECT (cosine computed for real),
    * ``create`` and ``merge`` on the insight table.

    Anything else raises ``NotImplementedError`` so the test cannot pass
    against a query it does not model.
    """

    def __init__(self):
        self.rows: dict[str, dict] = {}
        # recorded (sql, vars) for assertions
        self.queries: list[tuple[str, dict]] = []
        self.merges: list[tuple[str, dict]] = []
        self.creates: list[tuple[str, dict]] = []

    async def query(self, sql: str, vars: dict | None = None) -> list[dict]:
        self.queries.append((sql, dict(vars or {})))
        s = sql.strip().lower()

        # All-active-by-type SELECT: SELECT * FROM insight WHERE type = ... AND
        # domain = ... AND user_id = ... AND deprecated = false
        if s.startswith("select") and "from insight" in s and "deprecated = false" in s \
                and "similarity" not in s:
            out = []
            for rid, row in self.rows.items():
                if (row.get("type") == vars.get("type")
                        and row.get("domain") == vars.get("domain")
                        and row.get("user_id") == vars.get("user_id")
                        and not row.get("deprecated", False)):
                    r = dict(row)
                    r["id"] = rid
                    out.append(r)
            return out

        # Semantic-similarity SELECT: SELECT *, vector::similarity::cosine(...)
        # AS similarity FROM insight WHERE ... ORDER BY similarity DESC LIMIT 10
        if s.startswith("select") and "from insight" in s and "similarity" in s:
            qemb = vars.get("query_embedding") or []
            scored = []
            for rid, row in self.rows.items():
                if (row.get("type") == vars.get("type")
                        and row.get("domain") == vars.get("domain")
                        and row.get("user_id") == vars.get("user_id")
                        and not row.get("deprecated", False)):
                    sim = _cosine(qemb, row.get("embedding") or [])
                    r = dict(row)
                    r["id"] = rid
                    r["similarity"] = sim
                    scored.append(r)
            scored.sort(key=lambda r: r.get("similarity", 0.0), reverse=True)
            limit = 10
            m = re.search(r"limit\s+(\d+)", s)
            if m:
                limit = int(m.group(1))
            return scored[:limit]

        raise NotImplementedError(f"Unexpected query: {sql}")

    async def create(self, thing: str, data: dict) -> list[dict]:
        self.creates.append((thing, dict(data)))
        self.rows[thing] = dict(data)
        return [{"id": thing, **data}]

    async def merge(self, thing: str, data: dict) -> list[dict]:
        self.merges.append((thing, dict(data)))
        if thing in self.rows:
            self.rows[thing].update(data)
            return [{"id": thing, **self.rows[thing]}]
        return []

    async def select(self, thing: str) -> list[dict]:
        if ":" in thing:
            if thing in self.rows:
                return [dict(self.rows[thing])]
            return []
        return [dict(r) for r in self.rows.values()]


def _make_engine() -> tuple[LearningEngine, _FakeInsightDB, _StubEmbeddings]:
    """Build a LearningEngine (without running ``__init__``) wired to the fake
    db + stub embeddings, and return all three for inspection."""
    engine = LearningEngine.__new__(LearningEngine)
    db = _FakeInsightDB()
    embeddings = _StubEmbeddings()
    engine.db = db
    engine.embeddings = embeddings
    engine._insight_creation_lock = __import__("asyncio").Lock()
    engine._message_bus = None
    engine.logger = __import__("logging").getLogger("test_learning")
    engine.insights_created = 0
    return engine, db, embeddings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_changed_fact_supersedes_the_old_one():
    """'The user lives in Sofia' followed by 'The user lives in Varna' leaves
    exactly one active fact (Varna) and the Sofia record deprecated with a
    ``superseded_by`` link to the Varna record."""
    engine, db, _ = _make_engine()

    sofia_id = await engine.create_insight({
        "content": "The user lives in Sofia",
        "type": "FACT",
        "domain": "personal",
        "user_id": "u1",
        "confidence": 1.0,
    })
    varna_id = await engine.create_insight({
        "content": "The user lives in Varna",
        "type": "FACT",
        "domain": "personal",
        "user_id": "u1",
        "confidence": 1.0,
    })

    # Two records were created.
    assert sofia_id != varna_id, "the changed fact must be a new record"
    assert len(db.creates) == 2

    # Exactly one active (non-deprecated) fact remains, and it is Varna.
    active = [(rid, r) for rid, r in db.rows.items() if not r.get("deprecated", False)]
    assert len(active) == 1, f"expected 1 active fact, got {len(active)}"
    active_id, active_row = active[0]
    assert "varna" in active_row["content"].lower()
    assert active_id == varna_id

    # The old (Sofia) record is deprecated and links to its replacement.
    sofia_row = db.rows[sofia_id]
    assert sofia_row["deprecated"] is True
    assert sofia_row["superseded_by"] == varna_id


@pytest.mark.asyncio
async def test_repeating_the_same_fact_leaves_one_record():
    """Repeating the same fact twice still leaves a single record — the
    existing exact-match dedup path returns the first record's id and stores
    nothing new."""
    engine, db, _ = _make_engine()

    first_id = await engine.create_insight({
        "content": "The user lives in Sofia",
        "type": "FACT",
        "domain": "personal",
        "user_id": "u1",
        "confidence": 1.0,
    })
    second_id = await engine.create_insight({
        "content": "The user lives in Sofia",
        "type": "FACT",
        "domain": "personal",
        "user_id": "u1",
        "confidence": 1.0,
    })

    assert first_id == second_id, "repeating the same fact must return the same id"
    assert len(db.creates) == 1, "no new record should be created for a repeat"
    assert len(db.rows) == 1
    # The single record is still active and has no supersession link.
    only = list(db.rows.values())[0]
    assert only["deprecated"] is False
    assert "superseded_by" not in only


@pytest.mark.asyncio
async def test_non_fact_type_keeps_today_behaviour():
    """For a non-FACT type (e.g. PREFERENCE) a semantically similar insight
    above the threshold still bumps the existing confidence and returns the
    existing id — today's behaviour, unchanged by W1-14."""
    engine, db, _ = _make_engine()

    first_id = await engine.create_insight({
        "content": "The user likes dark chocolate",
        "type": "PREFERENCE",
        "domain": "food",
        "user_id": "u1",
        "confidence": 0.5,
    })
    second_id = await engine.create_insight({
        "content": "The user likes dark chocolate",
        "type": "PREFERENCE",
        "domain": "food",
        "user_id": "u1",
        "confidence": 0.9,
    })

    # Same record, no new record, not deprecated.
    assert first_id == second_id
    assert len(db.creates) == 1
    only = list(db.rows.values())[0]
    assert only["deprecated"] is False
    assert "superseded_by" not in only
    # Confidence was raised to the higher value.
    assert only["confidence"] == 0.9


@pytest.mark.asyncio
async def test_fact_supersession_merge_payload():
    """The deprecation merge on the old record sets exactly ``deprecated`` and
    ``superseded_by`` (the new id)."""
    engine, db, _ = _make_engine()

    sofia_id = await engine.create_insight({
        "content": "The user lives in Sofia",
        "type": "FACT",
        "domain": "personal",
        "user_id": "u1",
        "confidence": 1.0,
    })
    varna_id = await engine.create_insight({
        "content": "The user lives in Varna",
        "type": "FACT",
        "domain": "personal",
        "user_id": "u1",
        "confidence": 1.0,
    })

    # Find the deprecation merge (the only merge whose payload has
    # ``deprecated``/``superseded_by``).
    deprecation_merges = [
        m for m in db.merges
        if "deprecated" in m[1] or "superseded_by" in m[1]
    ]
    assert len(deprecation_merges) == 1, (
        f"expected exactly one supersession merge, got {deprecation_merges}"
    )
    target, payload = deprecation_merges[0]
    assert target == sofia_id
    assert payload == {"deprecated": True, "superseded_by": varna_id}
