"""Regression for the theme-recall flake: ids shown as ``fact:⟨81n8...⟩``.

``str(RecordID)`` wraps an id that starts with a digit in angle brackets. The
theme query must bind the bare id, or the fact never matches a ``member_of``
edge and a theme that qualifies by membership is dropped (which made
test_recall_themes_embedded fail about one run in ten, with random ids).
"""

from __future__ import annotations

from surrealdb import RecordID

from aura.engines.recall.engine import RecallEngine
from aura.engines.recall.models import Candidate


class _Db:
    def __init__(self):
        self.vars = None

    async def query(self, sql, vars=None):
        self.vars = vars
        return []


def _fact(key: str) -> Candidate:
    return Candidate(
        block="memories", key=key, dedup_keys=(key,), payload={}, rank=0, source="recall.facts"
    )


async def test_theme_query_binds_bare_fact_ids():
    db = _Db()
    engine = RecallEngine.__new__(RecallEngine)

    await engine._theme_candidates(
        db, "app", None, [_fact("fact:⟨81n800zrm8eggdub8p8z⟩"), _fact("fact:abc")]
    )

    assert db.vars["facts"] == [
        RecordID("fact", "81n800zrm8eggdub8p8z"),
        RecordID("fact", "abc"),
    ]


def test_to_record_id_strips_digit_id_brackets():
    from surrealdb import RecordID
    from aura.db.query_utils import to_record_id
    rid = RecordID("fact", "81n8abc")
    assert to_record_id(str(rid)) == rid
    assert to_record_id("fact:abc") == RecordID("fact", "abc")
