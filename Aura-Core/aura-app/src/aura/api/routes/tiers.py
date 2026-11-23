"""Tier API (P2-04).

GET  /system/tiers                  - effective profile, overrides and models per tier
POST /system/tiers/{index}          - partial profile; merged into the overrides file
POST /system/tiers/{index}/reset    - drop that tier's overrides

Overrides live in ``settings.tier_overrides_path`` (see ``aura.tiers``). Writes
are atomic (temp file + ``os.replace``) and invalidate the tiers cache at once.
Unauthenticated like the rest of the API (known FOR_MAI item).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from aura import tiers
from aura.config import settings

router = APIRouter(tags=["tiers"])
logger = logging.getLogger(__name__)

_write_lock = asyncio.Lock()


def _read_overrides(path: Path) -> dict[str, dict[str, Any]]:
    """Raw overrides from the file; anything unreadable or malformed is empty."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        k: v for k, v in raw.items()
        if k in {str(i) for i in tiers.DEFAULT_PROFILES} and isinstance(v, dict)
    }


def _effective(index: int, overrides: dict[str, Any]) -> tiers.TierProfile:
    try:
        return tiers.build_profile(index, overrides)
    except (ValidationError, ValueError):
        return tiers.DEFAULT_PROFILES[index]


def _write_atomic(path: Path, data: dict[str, dict[str, Any]]) -> None:
    """Write ``data`` (or delete the file when empty) without a partial state."""
    if not data:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _check_index(index: int) -> None:
    if index not in tiers.DEFAULT_PROFILES:
        raise HTTPException(status_code=404, detail=f"No tier {index}; expected 0..2")


def _snapshot() -> dict[str, Any]:
    path = tiers._overrides_path()
    raw = _read_overrides(path)
    out = []
    for index, name in tiers.TIER_NAMES.items():
        own = raw.get(str(index), {})
        out.append({
            "index": index,
            "name": name,
            "profile": _effective(index, own).model_dump(),
            "overrides": own,
            "models": settings.models_for_stack(index),
        })
    return {"active_index": settings.model_stack_index, "tiers": out}


@router.get("/tiers")
async def get_tiers() -> dict[str, Any]:
    return _snapshot()


@router.post("/tiers/{index}")
async def set_tier(index: int, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _check_index(index)
    async with _write_lock:
        path = tiers._overrides_path()
        raw = _read_overrides(path)
        merged_patch = {**raw.get(str(index), {}), **patch}
        try:
            tiers.build_profile(index, merged_patch)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raw[str(index)] = merged_patch
        _write_atomic(path, raw)
        tiers.invalidate_cache()
    return _snapshot()


@router.post("/tiers/{index}/reset")
async def reset_tier(index: int) -> dict[str, Any]:
    _check_index(index)
    async with _write_lock:
        path = tiers._overrides_path()
        raw = _read_overrides(path)
        raw.pop(str(index), None)
        _write_atomic(path, raw)
        tiers.invalidate_cache()
    return _snapshot()
