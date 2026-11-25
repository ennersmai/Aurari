"""Idea lineage store (P2-28): runs, seeds, candidates, final ideas and lens yield.

Tables live in scripts/schema_behavior.surql. Roles: ``seed`` (L3's own obvious ideas,
never shown as the answer), ``candidate`` (a helper's idea) and ``final`` (what L3
converged on, with ``parent_ids`` as its sources).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from surrealdb import RecordID

from aura.clock import get_clock
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows, to_record_id
from aura.engines.creativity.dedupe import same_idea


def _rid(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, RecordID):
        return f"{value.table_name}:{value.id}"
    return str(value)


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["id"] = _rid(out.get("id"))
    return out


def get_store() -> "LineageStore":
    return LineageStore(get_db_client())


class LineageStore:
    def __init__(self, db: Any = None) -> None:
        self.db = db if db is not None else get_db_client()

    async def _get(self, rid: str, table: str) -> dict[str, Any] | None:
        if not isinstance(rid, str) or not rid.startswith(f"{table}:") or len(rid) > 80:
            return None
        rows = extract_rows(await self.db.query("SELECT * FROM $rid", {"rid": to_record_id(rid)}))
        return _clean(rows[0]) if rows else None

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        return await self._get(run_id, "creative_run")

    async def get_idea(self, idea_id: str) -> dict[str, Any] | None:
        return await self._get(idea_id, "creative_idea")

    async def ideas(self, run_id: str, role: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM creative_idea WHERE run = $run"
        params: dict[str, Any] = {"run": run_id}
        if role is not None:
            sql += " AND role = $role"
            params["role"] = role
        rows = extract_rows(await self.db.query(sql + " ORDER BY created_at, id", params))
        return [_clean(r) for r in rows]

    async def _add_idea(self, run_id: str, role: str, text: str, **extra: Any) -> str:
        data: dict[str, Any] = {"run": run_id, "role": role, "text": text,
                                "created_at": get_clock().now()}
        data.update({k: v for k, v in extra.items() if v is not None})
        rid = RecordID("creative_idea", uuid4().hex[:12])
        await self.db.query("CREATE $rid CONTENT $data", {"rid": rid, "data": data})
        return f"creative_idea:{rid.id}"

    async def create_run(self, question: str, seeds: list[str]) -> tuple[str, list[str]]:
        rid = RecordID("creative_run", uuid4().hex[:12])
        await self.db.query(
            "CREATE $rid CONTENT $data",
            {"rid": rid, "data": {"question": question, "created_at": get_clock().now()}},
        )
        run_id = f"creative_run:{rid.id}"
        return run_id, [await self._add_idea(run_id, "seed", t) for t in seeds]

    async def add_candidates(
        self, run_id: str, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Store helper ideas (each: text, model, lens). Marks duplicates (word-set Jaccard
        against earlier kept candidates) and overlap with the run's seeds."""
        seeds = await self.ideas(run_id, "seed")
        stored: list[dict[str, Any]] = []
        for item in items:
            first = next((s for s in stored if s["duplicate_of"] is None
                          and same_idea(item["text"], s["text"])), None)
            overlaps = any(same_idea(item["text"], s["text"]) for s in seeds)
            dup = first["id"] if first else None
            idea_id = await self._add_idea(
                run_id, "candidate", item["text"], model=item["model"], lens=item["lens"],
                duplicate_of=dup, overlaps_seed=overlaps,
            )
            stored.append({**item, "id": idea_id, "duplicate_of": dup, "overlaps_seed": overlaps})
        await self.db.query(
            "UPDATE $rid SET explored_at = $now",
            {"rid": to_record_id(run_id), "now": get_clock().now()},
        )
        return stored

    async def lens_yields(self) -> dict[tuple[str, str], tuple[int, int]]:
        rows = extract_rows(await self.db.query("SELECT * FROM lens_yield", {}))
        return {(r["model"], r["lens"]): (int(r["offered"]), int(r["survived"])) for r in rows}

    async def _bump_yield(self, model: str, lens: str, offered: int, survived: int) -> None:
        rows = extract_rows(await self.db.query(
            "SELECT * FROM lens_yield WHERE model = $model AND lens = $lens",
            {"model": model, "lens": lens},
        ))
        now = get_clock().now()
        if rows:
            await self.db.query(
                "UPDATE $rid SET offered = $o, survived = $s, updated_at = $now",
                {"rid": to_record_id(_rid(rows[0]["id"])), "o": int(rows[0]["offered"]) + offered,
                 "s": int(rows[0]["survived"]) + survived, "now": now},
            )
        else:
            await self.db.query(
                "CREATE $rid CONTENT $data",
                {"rid": RecordID("lens_yield", uuid4().hex[:12]),
                 "data": {"model": model, "lens": lens, "offered": offered,
                          "survived": survived, "updated_at": now}},
            )

    async def finalize(self, run_id: str, finals: list[dict[str, Any]]) -> dict[str, Any]:
        """Record final ideas ``[{text, sources: [idea ids]}]`` (already validated), compute
        their overlap with the seeds, the run's novelty, and update the lens yield."""
        seeds = await self.ideas(run_id, "seed")
        candidates = await self.ideas(run_id, "candidate")
        cited = {s for f in finals for s in f["sources"]}
        out = []
        for f in finals:
            overlaps = any(same_idea(f["text"], s["text"]) for s in seeds)
            idea_id = await self._add_idea(
                run_id, "final", f["text"], parent_ids=list(f["sources"]), overlaps_seed=overlaps,
            )
            out.append({"id": idea_id, "text": f["text"], "sources": list(f["sources"]),
                        "overlaps_seed": overlaps})
        novelty = sum(1 for o in out if not o["overlaps_seed"]) / len(out) if out else 0.0
        tally: dict[tuple[str, str], list[int]] = {}
        for c in candidates:
            survived = c["id"] in cited
            await self.db.query(
                "UPDATE $rid SET survived = $s", {"rid": to_record_id(c["id"]), "s": survived}
            )
            if c.get("model") and c.get("lens"):
                t = tally.setdefault((c["model"], c["lens"]), [0, 0])
                t[0] += 1
                t[1] += 1 if survived else 0
        for (model, lens), (offered, survived) in tally.items():
            await self._bump_yield(model, lens, offered, survived)
        await self.db.query(
            "UPDATE $rid SET finalized_at = $now, final_count = $n, novelty = $nov",
            {"rid": to_record_id(run_id), "now": get_clock().now(), "n": len(out), "nov": novelty},
        )
        return {"finals": out, "novelty": novelty}

    async def tree(self, run_id: str) -> dict[str, Any] | None:
        """The idea tree for the inspector: finals with their sources, seeds, candidates."""
        run = await self.get_run(run_id)
        if run is None:
            return None
        ideas = await self.ideas(run_id)
        by_id = {i["id"]: i for i in ideas}

        def source(sid: str) -> dict[str, Any]:
            i = by_id.get(sid, {})
            return {"id": sid, "role": i.get("role"), "model": i.get("model"), "lens": i.get("lens")}

        return {
            "run": run_id, "question": run["question"], "novelty": run.get("novelty"),
            "seeds": [i for i in ideas if i["role"] == "seed"],
            "candidates": [i for i in ideas if i["role"] == "candidate"],
            "finals": [
                {**i, "sources": [source(s) for s in (i.get("parent_ids") or [])]}
                for i in ideas if i["role"] == "final"
            ],
        }
