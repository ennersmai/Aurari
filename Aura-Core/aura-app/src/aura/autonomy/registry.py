"""Registry of autonomous asyncio tasks and the kill switch (B1-06, T14).

Autonomous work registers its task here so ``cancel_all`` can stop it. The
kill switch sets ``killed`` first (a synchronous cache write, so every
``may_initiate`` refuses at once), then cancels the registry, autonomous
delegations and autonomous task graphs.

Scope (PRD 8.3: "A kill switch that stops all autonomous activity
immediately"): work the owner asked for is not autonomous and is left
running. A delegation counts as autonomous only when its config carries a
truthy ``autonomous`` attribute (nothing sets it today); a task graph is
autonomous when it has neither ``created_by_turn`` nor ``conversation_id``
(owner chat planning always sets the conversation).
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from aura.autonomy import controls, trace
from aura.config import settings

logger = logging.getLogger(__name__)

# task -> (kind, owner_ref); entries remove themselves when the task finishes.
_tasks: dict[asyncio.Task, tuple[str, str]] = {}
_interrupt_callbacks: list[Callable[[], Any]] = []


def register_autonomous_task(task: asyncio.Task, kind: str, owner_ref: str) -> asyncio.Task:
    """Track ``task`` until it finishes. Returns the task for chaining."""
    _tasks[task] = (kind, owner_ref)
    task.add_done_callback(lambda t: _tasks.pop(t, None))
    return task


def registered() -> list[dict[str, str]]:
    return [{"kind": k, "owner_ref": r} for k, r in _tasks.values()]


async def cancel_all(reason: str) -> list[dict[str, str]]:
    """Cancel and await every registered task; returns what was cancelled."""
    items = [(t, meta) for t, meta in list(_tasks.items()) if not t.done()]
    for t, _ in items:
        t.cancel()
    await asyncio.gather(*(t for t, _ in items), return_exceptions=True)
    for _, (kind, ref) in items:
        logger.info("autonomous task cancelled (%s): %s %s", reason, kind, ref)
    return [{"kind": k, "owner_ref": r} for _, (k, r) in items]


def add_interrupt_callback(cb: Callable[[], Any]) -> None:
    """Cooperative pause hook for B2-04 and B4-02 to fill."""
    _interrupt_callbacks.append(cb)


async def interrupt_for_user() -> None:
    """The owner spoke: ask cooperative autonomous work to pause."""
    for cb in list(_interrupt_callbacks):
        try:
            res = cb()
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:  # noqa: BLE001 - one hook must not block the rest
            logger.warning("interrupt callback failed: %s", e)


def interrupt_for_user_nowait() -> None:
    """Synchronous variant for the chat hot path: sync callbacks run now,
    coroutine callbacks are scheduled (never awaited here)."""
    for cb in list(_interrupt_callbacks):
        try:
            res = cb()
            if asyncio.iscoroutine(res):
                asyncio.get_running_loop().create_task(res)
        except Exception as e:  # noqa: BLE001
            logger.warning("interrupt callback failed: %s", e)


def reset() -> None:
    """Forget registrations and hooks (tests)."""
    _tasks.clear()
    _interrupt_callbacks.clear()


async def _abort_delegations() -> list[dict[str, str]]:
    from aura.executor import delegation

    stopped: list[dict[str, str]] = []
    targets = [r for r in delegation.running_runners() if getattr(r.config, "autonomous", False)]
    results = await asyncio.gather(*(r.abort() for r in targets), return_exceptions=True)
    for r, res in zip(targets, results):
        if isinstance(res, BaseException):
            logger.warning("delegation abort failed for %s: %s", r.task_id, res)
        stopped.append({"kind": "delegation", "owner_ref": str(r.task_id)})
    return stopped


async def _cancel_autonomous_graphs() -> tuple[list[dict[str, str]], list[str]]:
    from aura.executor.task_graph import get_task_graph_store
    from aura.executor.task_scheduler import get_task_scheduler

    sched = get_task_scheduler()
    store = get_task_graph_store()
    stopped: list[dict[str, str]] = []
    kept: list[str] = []
    cancelled: list[asyncio.Task] = []
    # The scheduler has no per-graph cancel (shutdown cancels all), so the
    # per-graph task is cancelled directly; its own CancelledError handler
    # marks the nodes interrupted.
    for gid, task in list(sched._tasks.items()):
        try:
            graph = await store.get_graph(gid)
        except Exception as e:  # noqa: BLE001
            logger.warning("graph lookup failed for %s: %s", gid, e)
            kept.append(gid)
            continue
        if graph is not None and (graph.created_by_turn or graph.conversation_id):
            kept.append(gid)
            continue
        task.cancel()
        cancelled.append(task)
        stopped.append({"kind": "task_graph", "owner_ref": gid})
    await asyncio.gather(*cancelled, return_exceptions=True)
    return stopped, kept


async def kill(db: Any = None) -> dict[str, Any]:
    """The kill switch. Never depends on a flag or on the database for the refusal."""
    try:
        await controls.set_killed(True, db)
    except Exception as e:  # noqa: BLE001 - the in-memory refusal must still hold
        logger.error("kill switch could not persist: %s", e)
        if controls._cache is not None:
            controls._cache.killed = True
        else:
            controls._cache = controls.Controls(killed=True)
    if settings.goals_v2_enabled:
        try:
            from aura.autonomy import grants

            await grants.revoke_all(db)
        except Exception as e:  # noqa: BLE001 - the kill must still proceed
            logger.error("kill switch could not revoke grants: %s", e)
    stopped = await cancel_all("kill_switch")
    stopped += await _abort_delegations()
    graphs, kept = await _cancel_autonomous_graphs()
    stopped += graphs
    result = {
        "killed": True,
        "stopped": stopped,
        "left_running_owner_graphs": kept,
        "note": "Owner-started work (chat task graphs, delegations you requested) is not autonomous and was left running.",
    }
    await trace.record(
        "owner", "kill_switch", f"stopped {len(stopped)} autonomous item(s)", refs=[s["owner_ref"] for s in stopped], db=db
    )
    return result
