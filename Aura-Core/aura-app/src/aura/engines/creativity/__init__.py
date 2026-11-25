"""Creativity engines (P2-28 Diverge): dedupe, lens choice and the idea lineage store."""

from __future__ import annotations

from aura.config import settings
from aura.tiers import consult_enabled


def diverge_enabled(profile=None) -> bool:
    """The Diverge tools are offered and callable only with diverge_enabled AND consult available."""
    return bool(settings.diverge_enabled) and consult_enabled(profile)
