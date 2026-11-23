"""Skill document storage (G5-01). Persistence only: no selection, no approval flow."""

import logging
from typing import Any
from uuid import uuid4

import numpy as np
from surrealdb import RecordID

from aura.clock import get_clock
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows, to_record_id
from aura.models.learning import SkillDoc, SkillVersion

logger = logging.getLogger(__name__)

_STATES = ("candidate", "trusted", "retired")
_VERSION_RETRIES = 3


def rid_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, RecordID):
        return f"{value.table_name}:{value.id}"
    return str(value)


def _to_doc(row: dict[str, Any]) -> SkillDoc:
    data = dict(row)
    data["id"] = rid_str(data.get("id")) or ""
    data["node"] = rid_str(data.get("node"))
    return SkillDoc(**data)


def _to_version(row: dict[str, Any]) -> SkillVersion:
    data = dict(row)
    data["id"] = rid_str(data.get("id")) or ""
    data["skill"] = rid_str(data.get("skill")) or ""
    return SkillVersion(**data)


class SkillStore:
    """SurrealDB-backed store for skill documents and their versions."""

    def __init__(self, db: Any = None) -> None:
        self.db = db if db is not None else get_db_client()

    async def create_doc(
        self,
        name: str,
        when_to_use: str,
        tags: list[str] | None = None,
        state: str = "candidate",
        origin_speaker: str = "owner",
        workspace: str | None = None,
        node: str | None = None,
        when_embedding: list[float] | None = None,
    ) -> SkillDoc:
        """Create a document. A name that already exists raises ValueError."""
        if state not in _STATES:
            raise ValueError(f"unknown skill state: {state}")
        if await self.get_doc(name) is not None:
            raise ValueError(f"skill name already exists: {name}")
        now = get_clock().now()
        data: dict[str, Any] = {
            "name": name,
            "when_to_use": when_to_use,
            "tags": list(tags or []),
            "state": state,
            "origin_speaker": origin_speaker,
            "created_at": now,
            "updated_at": now,
        }
        if workspace is not None:
            data["workspace"] = workspace
        if node is not None:
            data["node"] = to_record_id(node)
        if when_embedding is not None:
            data["when_embedding"] = [float(x) for x in when_embedding]
        rid = RecordID("skill_doc", uuid4().hex[:12])
        try:
            await self.db.query("CREATE $rid CONTENT $data", {"rid": rid, "data": data})
        except Exception as exc:  # unique index on name (race with another writer)
            raise ValueError(f"skill doc not created: {name}: {exc}") from exc
        doc = await self.get_doc(name)
        if doc is None:
            raise ValueError(f"skill doc not created: {name}")
        return doc

    async def get_doc(self, name: str) -> SkillDoc | None:
        rows = extract_rows(
            await self.db.query("SELECT * FROM skill_doc WHERE name = $name", {"name": name})
        )
        return _to_doc(rows[0]) if rows else None

    async def add_version(
        self,
        skill: str,
        body: str,
        source: str,
        tools: list[str] | None = None,
        examples: list[str] | None = None,
        pitfalls: list[str] | None = None,
        source_task: str | None = None,
        change_note: str | None = None,
        approved: bool = False,
        approved_by: str | None = None,
    ) -> SkillVersion:
        """Store the next version (max + 1, never reused, no old row is touched).

        ``approved=True`` stamps ``approved_at`` from the clock.
        """
        doc_rid = to_record_id(skill)
        last_exc: Exception | None = None
        for _ in range(_VERSION_RETRIES):
            rows = extract_rows(
                await self.db.query(
                    "SELECT version FROM skill_version WHERE skill = $skill "
                    "ORDER BY version DESC LIMIT 1",
                    {"skill": doc_rid},
                )
            )
            number = int(rows[0]["version"]) + 1 if rows else 1
            now = get_clock().now()
            data: dict[str, Any] = {
                "skill": doc_rid,
                "version": number,
                "body": body,
                "tools": list(tools or []),
                "examples": list(examples or []),
                "pitfalls": list(pitfalls or []),
                "source": source,
                "created_at": now,
            }
            if source_task is not None:
                data["source_task"] = source_task
            if change_note is not None:
                data["change_note"] = change_note
            if approved:
                data["approved_at"] = now
                if approved_by is not None:
                    data["approved_by"] = approved_by
            rid = RecordID("skill_version", f"{doc_rid.id}_{number}")
            try:
                await self.db.query("CREATE $rid CONTENT $data", {"rid": rid, "data": data})
            except Exception as exc:  # number taken by a concurrent writer: retry
                last_exc = exc
                continue
            stored = await self.get_version(skill, number)
            if stored is not None:
                return stored
        raise RuntimeError(f"skill version not stored for {skill}: {last_exc}")

    async def get_version(self, skill: str, version: int) -> SkillVersion | None:
        rows = extract_rows(
            await self.db.query(
                "SELECT * FROM skill_version WHERE skill = $skill AND version = $version",
                {"skill": to_record_id(skill), "version": int(version)},
            )
        )
        return _to_version(rows[0]) if rows else None

    async def list_versions(self, skill: str) -> list[SkillVersion]:
        rows = extract_rows(
            await self.db.query(
                "SELECT * FROM skill_version WHERE skill = $skill ORDER BY version ASC",
                {"skill": to_record_id(skill)},
            )
        )
        return [_to_version(r) for r in rows]

    async def list_docs(
        self, state: str | None = None, include_unapproved: bool = False
    ) -> list[SkillDoc]:
        """Documents by name. Unless asked, only those with an approved version."""
        if state is None:
            rows = extract_rows(await self.db.query("SELECT * FROM skill_doc ORDER BY name ASC"))
        else:
            rows = extract_rows(
                await self.db.query(
                    "SELECT * FROM skill_doc WHERE state = $state ORDER BY name ASC",
                    {"state": state},
                )
            )
        docs = [_to_doc(r) for r in rows]
        if include_unapproved:
            return docs
        approved = extract_rows(
            await self.db.query(
                "SELECT skill FROM skill_version "
                "WHERE approved_at != NONE AND rejected = false"
            )
        )
        ok = {rid_str(r["skill"]) for r in approved}
        return [d for d in docs if d.id in ok]

    async def _update(self, skill: str, patch: dict[str, Any]) -> None:
        patch = {**patch, "updated_at": get_clock().now()}
        await self.db.query(
            "UPDATE $rid MERGE $patch", {"rid": to_record_id(skill), "patch": patch}
        )

    async def set_state(self, skill: str, state: str) -> None:
        """Set the state; retiring stamps ``retired_at``, leaving it clears it."""
        if state not in _STATES:
            raise ValueError(f"unknown skill state: {state}")
        patch: dict[str, Any] = {"state": state}
        patch["retired_at"] = get_clock().now() if state == "retired" else None
        await self._update(skill, patch)

    async def set_active(self, skill: str, version: int) -> None:
        """Make ``version`` active; the old active one becomes ``previous_version``."""
        if await self.get_version(skill, version) is None:
            raise ValueError(f"no version {version} for {skill}")
        rows = extract_rows(
            await self.db.query("SELECT active_version FROM $rid", {"rid": to_record_id(skill)})
        )
        if not rows:
            raise ValueError(f"no skill doc {skill}")
        current = rows[0].get("active_version")
        patch: dict[str, Any] = {"active_version": int(version)}
        if current is not None and int(current) != int(version):
            patch["previous_version"] = int(current)
        await self._update(skill, patch)

    async def touch_used(self, skill: str) -> None:
        await self._update(skill, {"last_used_at": get_clock().now()})

    async def nearest_doc(self, embedding: list[float]) -> tuple[SkillDoc, float] | None:
        """Nearest non-retired doc by cosine of ``when_embedding`` (computed in Python)."""
        rows = extract_rows(
            await self.db.query(
                "SELECT * FROM skill_doc WHERE state != 'retired' AND when_embedding != NONE"
            )
        )
        query = np.asarray(embedding, dtype=float)
        qn = float(np.linalg.norm(query))
        if qn == 0.0:
            return None
        best: tuple[dict[str, Any], float] | None = None
        for row in rows:
            emb = row.get("when_embedding")
            if not emb or len(emb) != len(query):
                continue
            vec = np.asarray(emb, dtype=float)
            vn = float(np.linalg.norm(vec))
            if vn == 0.0:
                continue
            sim = float(np.dot(query, vec) / (qn * vn))
            if best is None or sim > best[1]:
                best = (row, sim)
        return (_to_doc(best[0]), best[1]) if best else None

    async def approve(
        self, skill: str, version: int, by: str, trusted: bool = False
    ) -> None:
        """Owner approval: stamp ``approved_at``, make it active, keep the doc a
        candidate (on trial) or make it ``trusted``."""
        if await self.get_version(skill, version) is None:
            raise ValueError(f"no version {version} for {skill}")
        await self.db.query(
            "UPDATE skill_version SET approved_at = $now, approved_by = $by, rejected = false "
            "WHERE skill = $skill AND version = $version",
            {"now": get_clock().now(), "by": by, "skill": to_record_id(skill),
             "version": int(version)},
        )
        await self.set_active(skill, version)
        if trusted:
            await self.set_state(skill, "trusted")

    async def reject(self, skill: str, version: int) -> None:
        """Owner denial: the version is never offered again."""
        if await self.get_version(skill, version) is None:
            raise ValueError(f"no version {version} for {skill}")
        await self.db.query(
            "UPDATE skill_version SET rejected = true WHERE skill = $skill AND version = $version",
            {"skill": to_record_id(skill), "version": int(version)},
        )
