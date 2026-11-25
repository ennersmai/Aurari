"""Tier profiles (P2-03): what each tier (Lean, Core, Titan) may do.

The slider is ``settings.model_stack_index`` (0 Lean, 1 Core, 2 Titan). A
:class:`TierProfile` holds every capability knob of Phase 2 plan section 3.1.
Defaults are the three constants below; ``.aura/tier_overrides.json`` (path in
``settings.tier_overrides_path``) may override any knob per tier::

    {"2": {"tools_offered_max": 12}, "0": {"turn_budget_usd": 0.05}}

Everything here only matters while ``settings.tier_profiles_enabled`` is true.
With the flag off no caller consults this module and behaviour is unchanged.

With the flag on, the profile and the L1 route decide how much Aura thinks;
clients no longer send reasoning toggles (P2-42, ignored if still sent). The
requester-role check always runs first (D9, D13).

L3 reasoning until P2-06: L1 routes do not exist yet, so "route think" never
happens, and no stakes value exists either. :func:`l3_reasoning_allowed` is
therefore False on every tier today. P2-06 feeds it real route and stakes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aura.config import settings

logger = logging.getLogger(__name__)

# aura-app/ (this file is aura-app/src/aura/tiers.py)
APP_DIR = Path(__file__).resolve().parents[2]

TIER_NAMES: dict[int, str] = {0: "lean", 1: "core", 2: "titan"}

# Tools only some tiers may use: tool name -> TierProfile boolean that allows it.
# ``plan_task`` (P2-08) is also behind settings.task_graphs_enabled; see plan_task_enabled().
TIER_GATED_TOOLS: dict[str, str] = {
    "delegate_work": "allow_delegate",
    "plan_task": "allow_task_graph",
}

# ``consult`` (P2-27) is allowed when the profile grants any helper calls (Lean: none).
CONSULT_TOOL = "consult"

TIER_UNAVAILABLE_ERROR = "not available on this tier"


class TierProfile(BaseModel):
    """Every knob from plan section 3.1, range-validated."""

    model_config = ConfigDict(extra="forbid")

    name: str = "lean"
    # "never" | "think" (route think only) | "think_or_stakes" (route think, or
    # stakes >= l3_stakes_threshold). See l3_reasoning_allowed().
    l3_reasoning: Literal["never", "think", "think_or_stakes"] = "never"
    l3_stakes_threshold: float = Field(0.7, ge=0.0, le=1.0)
    # "off" | "on" | "on_with_reasoning" (post-analysis, and its reasoning).
    l2_post_analysis: Literal["off", "on", "on_with_reasoning"] = "off"
    turn_budget_seconds: int = Field(45, ge=1, le=3600)
    turn_budget_usd: float = Field(0.03, ge=0.0, le=100.0)
    tools_offered_max: int = Field(3, ge=1, le=50)
    context_budget_tokens: int = Field(5000, ge=500, le=200000)
    history_floor_exchanges: int = Field(3, ge=0, le=50)
    allow_delegate: bool = False
    allow_task_graph: bool = False
    task_graph_max_nodes: int = Field(0, ge=0, le=100)
    task_budget_usd: float = Field(0.0, ge=0.0, le=1000.0)
    task_budget_minutes: int = Field(0, ge=0, le=10000)
    consult_swift_per_turn: int = Field(0, ge=0, le=100)
    consult_sage_per_turn: int = Field(0, ge=0, le=100)
    # "off" | "think_high_stakes" (route think and stakes >= afterthought_min_stakes)
    afterthought: Literal["off", "think_high_stakes"] = "off"
    afterthought_min_stakes: float = Field(0.8, ge=0.0, le=1.0)
    full_tools_max: int = Field(3, ge=0, le=50)
    stub_tools_max: int = Field(5, ge=0, le=200)
    autonomy_max_level: int = Field(1, ge=0, le=5)


LEAN = TierProfile(name="lean")
CORE = TierProfile(
    name="core",
    l3_reasoning="think",
    l2_post_analysis="on",
    turn_budget_seconds=120,
    turn_budget_usd=0.20,
    tools_offered_max=6,
    context_budget_tokens=10000,
    history_floor_exchanges=4,
    consult_swift_per_turn=3,
    consult_sage_per_turn=1,
    full_tools_max=4,
    stub_tools_max=12,
    autonomy_max_level=2,
)
TITAN = TierProfile(
    name="titan",
    l3_reasoning="think_or_stakes",
    l2_post_analysis="on_with_reasoning",
    turn_budget_seconds=300,
    turn_budget_usd=1.00,
    tools_offered_max=10,
    context_budget_tokens=20000,
    history_floor_exchanges=6,
    allow_delegate=True,
    allow_task_graph=True,
    task_graph_max_nodes=8,
    task_budget_usd=2.00,
    task_budget_minutes=120,
    consult_swift_per_turn=8,
    consult_sage_per_turn=3,
    afterthought="think_high_stakes",
    full_tools_max=5,
    stub_tools_max=20,
    autonomy_max_level=3,
)
DEFAULT_PROFILES: dict[int, TierProfile] = {0: LEAN, 1: CORE, 2: TITAN}

# One cache entry: (path, mtime_ns or None) -> profiles by index.
_cache_key: tuple[str, int | None] | None = None
_cache_profiles: dict[int, TierProfile] = DEFAULT_PROFILES
_warned = False


def reset_tier_cache() -> None:
    """Forget the cached overrides and the one-warning latch (tests, P2-04 writes)."""
    global _cache_key, _cache_profiles, _warned
    _cache_key = None
    _cache_profiles = DEFAULT_PROFILES
    _warned = False


def invalidate_cache() -> None:
    """Drop the cached profiles so the next read reloads the file (P2-04 writes).

    Keeps the one-warning latch, so a bad file does not warn again per write.
    """
    global _cache_key, _cache_profiles
    _cache_key = None
    _cache_profiles = DEFAULT_PROFILES


def _warn_once(message: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        logger.warning(message)


def _overrides_path() -> Path:
    path = Path(settings.tier_overrides_path)
    return path if path.is_absolute() else APP_DIR / path


# D3: only Titan (index 2) may delegate or plan task graphs; overrides cannot
# grant these elsewhere. The tier name is fixed.
TITAN_ONLY_KNOBS = ("allow_delegate", "allow_task_graph")
TITAN_INDEX = 2


def build_profile(index: int, patch: dict[str, Any]) -> TierProfile:
    """Defaults for ``index`` merged with ``patch``; raises ValueError or
    ValidationError for anything the overrides may not change (D3, name)."""
    if "name" in patch:
        raise ValueError("the tier name cannot be overridden")
    if index != TITAN_INDEX:
        granted = [k for k in TITAN_ONLY_KNOBS if patch.get(k)]
        if granted:
            raise ValueError(f"{granted} are Titan only (D3)")
    return TierProfile(**{**DEFAULT_PROFILES[index].model_dump(), **patch})


def _load_profiles(path: Path) -> dict[int, TierProfile]:
    """Defaults merged with the file. Any problem gives the defaults and one warning."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("top level must be an object keyed by tier index")
        unknown = set(raw) - {str(i) for i in DEFAULT_PROFILES}
        if unknown:
            raise ValueError(f"unknown tier keys {sorted(unknown)}")
        merged: dict[int, TierProfile] = {}
        for index, default in DEFAULT_PROFILES.items():
            patch = raw.get(str(index), {})
            if not isinstance(patch, dict):
                raise ValueError(f"tier {index} overrides must be an object")
            merged[index] = build_profile(index, patch)
        return merged
    except (OSError, ValueError, ValidationError) as exc:
        # json.JSONDecodeError is a ValueError.
        _warn_once(f"Ignoring tier overrides at {path}: {exc}. Using default profiles.")
        return DEFAULT_PROFILES


def active_profile() -> TierProfile:
    """The active stack's profile with overrides applied (cached by file mtime)."""
    global _cache_key, _cache_profiles
    path = _overrides_path()
    try:
        mtime: int | None = path.stat().st_mtime_ns
    except OSError:
        mtime = None
    key = (str(path), mtime)
    if key != _cache_key:
        _cache_profiles = DEFAULT_PROFILES if mtime is None else _load_profiles(path)
        _cache_key = key
    return _cache_profiles[settings.model_stack_index]


def l3_reasoning_allowed(profile: TierProfile, route: str | None, stakes: float | None) -> bool:
    """May this turn use L3 deep reasoning under ``profile``?

    ``route`` is the L1 route and ``stakes`` the L1 stakes score; both are None
    until P2-06, which makes this False on every tier. The coordinator uses
    this value alone (P2-42).
    """
    if profile.l3_reasoning == "never":
        return False
    if route == "think":
        return True
    return (
        profile.l3_reasoning == "think_or_stakes"
        and stakes is not None
        and stakes >= profile.l3_stakes_threshold
    )


def l2_analysis_allowed(profile: TierProfile) -> bool:
    return profile.l2_post_analysis != "off"


def l2_reasoning_allowed(profile: TierProfile) -> bool:
    return profile.l2_post_analysis == "on_with_reasoning"


def tool_allowed(profile: TierProfile, tool_name: str) -> bool:
    """False only for a tier-gated tool the profile does not allow."""
    if tool_name == CONSULT_TOOL:
        return consult_allowed_by_profile(profile)
    knob = TIER_GATED_TOOLS.get(tool_name)
    return knob is None or bool(getattr(profile, knob))


def consult_allowed_by_profile(profile: TierProfile) -> bool:
    return profile.consult_swift_per_turn + profile.consult_sage_per_turn > 0


def consult_enabled(profile: TierProfile | None = None) -> bool:
    """consult is offered and callable only with consult_enabled AND tier_profiles_enabled
    AND a profile with helper calls per turn (P2-27). Lean has none."""
    if not (settings.consult_enabled and settings.tier_profiles_enabled):
        return False
    return consult_allowed_by_profile(profile or active_profile())


def plan_task_enabled(profile: TierProfile | None = None) -> bool:
    """plan_task is offered and callable only with task_graphs_enabled AND
    tier_profiles_enabled AND a profile that allows task graphs (P2-08)."""
    if not (settings.task_graphs_enabled and settings.tier_profiles_enabled):
        return False
    return bool((profile or active_profile()).allow_task_graph)


def afterthought_allowed(
    profile: TierProfile | None, route: str | None, stakes: float | None
) -> bool:
    """May this turn get an Afterthought (P2-30)? Needs afterthought_enabled AND
    tier_profiles_enabled, a profile with ``afterthought`` on (Titan by default),
    L1 route ``think`` and stakes >= the profile's ``afterthought_min_stakes``.
    Route and stakes are None unless l1_routes_enabled, which makes this False."""
    if profile is None or not (settings.afterthought_enabled and settings.tier_profiles_enabled):
        return False
    return (
        profile.afterthought == "think_high_stakes"
        and route == "think"
        and stakes is not None
        and stakes >= profile.afterthought_min_stakes
    )


def gated_tools_denied(profile: TierProfile) -> set[str]:
    """Names of the tier-gated tools this profile may not offer."""
    denied = {name for name in TIER_GATED_TOOLS if not tool_allowed(profile, name)}
    if settings.consult_enabled and not consult_allowed_by_profile(profile):
        denied.add(CONSULT_TOOL)
    return denied


def recall_budget_tokens(profile: TierProfile) -> int:
    return int(settings.tier_recall_share * profile.context_budget_tokens)


def history_budget_tokens(profile: TierProfile) -> int:
    return profile.context_budget_tokens - recall_budget_tokens(profile)


def trim_history(
    history: list[dict[str, str]],
    profile: TierProfile,
    count_tokens: Any,
) -> list[dict[str, str]]:
    """Keep the newest messages that fit the history budget.

    Newest first, never below ``history_floor_exchanges`` exchanges (two
    messages each). ``count_tokens`` maps text to a token count.
    """
    budget = history_budget_tokens(profile)
    floor = profile.history_floor_exchanges * 2
    used = 0
    kept = 0
    for message in reversed(history):
        cost = count_tokens(str(message.get("content", "")))
        if kept >= floor and used + cost > budget:
            break
        used += cost
        kept += 1
    return history[len(history) - kept:]


# P2-42: the client no longer controls reasoning; old clients may still send these.
DEPRECATED_REASONING_FIELDS = (
    "reasoning_enabled",
    "l2_reasoning_enabled",
    "deep_analysis_enabled",
    "enable_l2",
    "enable_l2_analysis",
)
_deprecation_logged = False


def note_deprecated_reasoning_controls(provided: list[str]) -> None:
    """Log one deprecation line per process the first time any old field is sent."""
    global _deprecation_logged
    if provided and not _deprecation_logged:
        _deprecation_logged = True
        logger.warning(
            "Deprecated reasoning controls ignored (%s): the tier slider and L1 "
            "route decide how much Aura thinks (P2-42).",
            ", ".join(provided),
        )


def reset_deprecation_latch() -> None:
    """Re-arm the one-line deprecation log (tests)."""
    global _deprecation_logged
    _deprecation_logged = False
