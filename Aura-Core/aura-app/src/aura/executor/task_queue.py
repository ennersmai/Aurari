"""Task Queue Service — persistent task lifecycle management.

Singleton service that manages Aura's long-running tasks in SurrealDB.
Every step is persisted immediately so if Docker restarts mid-step the
step is marked interrupted and the task can resume cleanly.

Designed for future multi-Aura federation: another Aura instance could
query your task queue via the REST API built on top of this service.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows
from aura.models.task import BlockerInfo, Task, TaskStatus, TaskStepRecord

logger = logging.getLogger(__name__)


class TaskQueueService:
    """Persistent task queue backed by SurrealDB."""

    def __init__(self) -> None:
        self.db = get_db_client()

    # =========================================================================
    # CREATE
    # =========================================================================

    async def create_task(
        self,
        goal: str,
        workspace_path: str = "",
        session_id: str = "main",
        delegated: bool = False,
    ) -> Task:
        """Create a new task and persist it immediately.

        Args:
            session_id: The session this task belongs to. Defaults to "main"
                for backward compatibility with pre-Sessions code paths.
        """
        short_id = uuid4().hex[:12]
        task_id = f"task:{short_id}"
        namespace = f"task_{short_id}"

        task = Task(
            task_id=task_id,
            goal=goal,
            status=TaskStatus.QUEUED,
            workspace_path=workspace_path,
            task_memory_namespace=namespace,
            session_id=session_id,
            delegated=delegated,
        )

        await self.db.create(task_id, task.model_dump(mode="json"))
        logger.info(f"Task created: {task_id} (session={session_id}) — {goal[:80]}")
        return task

    # =========================================================================
    # READ
    # =========================================================================

    async def get_task(self, task_id: str) -> Task | None:
        """Fetch a single task by ID."""
        try:
            result = await self.db.select(task_id)
            if result:
                return Task(**result[0])
            return None
        except Exception as e:
            logger.error(f"Failed to fetch task {task_id}: {e}")
            return None

    async def get_active_tasks(self, session_id: str | None = None) -> list[Task]:
        """Return every running task, optionally filtered to one session.

        Replaces the singleton-era `get_active_task`: with sessions,
        multiple tasks can run concurrently across sessions.
        """
        if session_id is not None:
            result = await self.db.query(
                """
                SELECT * FROM task
                WHERE status = 'running' AND session_id = $sid
                ORDER BY updated_at DESC
                """,
                {"sid": session_id},
            )
        else:
            result = await self.db.query(
                """
                SELECT * FROM task
                WHERE status = 'running'
                ORDER BY updated_at DESC
                """
            )
        return [Task(**row) for row in (result or [])]

    async def get_active_task(self, session_id: str | None = None) -> Task | None:
        """Backward-compat shim: return the *most recent* running task.

        Prefer `get_active_tasks()` for new code. Existing callers that
        assumed at-most-one-active-task continue to work because this
        returns the most-recently-updated running task.
        """
        active = await self.get_active_tasks(session_id=session_id)
        return active[0] if active else None

    async def get_tasks(
        self,
        status_filter: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[Task]:
        """List tasks with optional status and session filters."""
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if status_filter:
            clauses.append("status = $status")
            params["status"] = status_filter
        if session_id is not None:
            clauses.append("session_id = $sid")
            params["sid"] = session_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        result = await self.db.query(
            f"SELECT * FROM task {where} ORDER BY updated_at DESC LIMIT $limit",
            params,
        )
        return [Task(**row) for row in (result or [])]

    async def get_task_history(
        self,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[Task]:
        """Get completed/failed tasks for history view, optionally per session."""
        if session_id is not None:
            result = await self.db.query(
                """
                SELECT * FROM task
                WHERE status IN ['complete', 'failed'] AND session_id = $sid
                ORDER BY completed_at DESC
                LIMIT $limit
                """,
                {"sid": session_id, "limit": limit},
            )
        else:
            result = await self.db.query(
                """
                SELECT * FROM task
                WHERE status IN ['complete', 'failed']
                ORDER BY completed_at DESC
                LIMIT $limit
                """,
                {"limit": limit},
            )
        return [Task(**row) for row in (result or [])]

    async def get_delegated_tasks(self, closed_limit: int = 50) -> list[Task]:
        """Delegated tasks: every open one, plus the latest closed ones.

        A delegated task is created by DelegationRunner with ``delegated``
        true (its ``session_id`` then holds the OpenCode session id).
        """
        open_rows = await self.db.query(
            """
            SELECT * FROM task
            WHERE delegated = true
              AND status IN ['queued', 'running', 'paused', 'waiting_approval', 'needs_owner']
            ORDER BY updated_at DESC
            """
        )
        closed_rows = await self.db.query(
            """
            SELECT * FROM task
            WHERE delegated = true
              AND status IN ['complete', 'failed']
            ORDER BY completed_at DESC
            LIMIT $limit
            """,
            {"limit": closed_limit},
        )
        return [Task(**row) for row in (open_rows or []) + (closed_rows or [])]

    # =========================================================================
    # UPDATE — status transitions
    # =========================================================================

    async def start_task(self, task_id: str) -> Task | None:
        """Transition task to running."""
        return await self._update_status(task_id, TaskStatus.RUNNING)

    async def pause_task(self, task_id: str) -> Task | None:
        """Pause a running task."""
        return await self._update_status(task_id, TaskStatus.PAUSED)

    async def resume_task(self, task_id: str) -> Task | None:
        """Resume a paused task."""
        return await self._update_status(task_id, TaskStatus.RUNNING)

    async def complete_task(self, task_id: str) -> Task | None:
        """Mark task as completed."""
        now = datetime.utcnow()
        await self.db.merge(task_id, {
            "status": TaskStatus.COMPLETE.value,
            "completed_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "blocker": None,
        })
        logger.info(f"Task completed: {task_id}")
        return await self.get_task(task_id)

    async def fail_task(self, task_id: str, reason: str = "") -> Task | None:
        """Mark task as failed."""
        now = datetime.utcnow()
        await self.db.merge(task_id, {
            "status": TaskStatus.FAILED.value,
            "completed_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "blocker": reason or None,
        })
        logger.info(f"Task failed: {task_id} — {reason[:100]}")
        return await self.get_task(task_id)

    async def set_waiting_approval(self, task_id: str, blocker: str) -> None:
        """Set task status to waiting_approval with blocker description."""
        await self.db.merge(task_id, {
            "status": TaskStatus.WAITING_APPROVAL.value,
            "blocker": blocker,
            "updated_at": datetime.utcnow().isoformat(),
        })

    async def set_blocker_info(self, task_id: str, blocker_data: dict[str, Any]) -> None:
        """Persist structured escalation data alongside the blocker string."""
        try:
            info = BlockerInfo(**blocker_data)
            await self.db.merge(task_id, {
                "blocker_info": info.model_dump(mode="json"),
                "updated_at": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            logger.error(f"Failed to set blocker_info for {task_id}: {e}")

    async def clear_blocker(self, task_id: str) -> None:
        """Clear blocker and blocker_info, resume task."""
        await self.db.merge(task_id, {
            "status": TaskStatus.RUNNING.value,
            "blocker": None,
            "blocker_info": None,
            "updated_at": datetime.utcnow().isoformat(),
        })

    async def _update_status(self, task_id: str, status: TaskStatus) -> Task | None:
        """Generic status update helper."""
        await self.db.merge(task_id, {
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat(),
            "blocker": None,
        })
        return await self.get_task(task_id)

    # =========================================================================
    # STEP PERSISTENCE — crash safety
    # =========================================================================

    async def persist_step(self, task_id: str, step: TaskStepRecord) -> None:
        """Append a step to the task's execution history immediately."""
        try:
            await self.db.query(
                """
                UPDATE $task_id SET
                    steps += [$step],
                    current_step_index = $idx,
                    updated_at = time::now()
                """,
                {
                    "task_id": task_id,
                    "step": step.model_dump(mode="json"),
                    "idx": step.step_number,
                },
            )
        except Exception as e:
            logger.error(f"CRITICAL: Failed to persist step {step.step_number} for {task_id}: {e}")

    async def mark_step_interrupted(self, task_id: str, step_number: int) -> None:
        """Mark the last step as interrupted (Docker crash recovery)."""
        task = await self.get_task(task_id)
        if not task or not task.steps:
            return
        # Find and update the step
        for s in task.steps:
            if s.step_number == step_number:
                s.title = f"[INTERRUPTED] {s.title}"
                s.success = False
                break
        await self.db.merge(task_id, {
            "steps": [s.model_dump(mode="json") for s in task.steps],
            "status": TaskStatus.PAUSED.value,
            "updated_at": datetime.utcnow().isoformat(),
        })

    # =========================================================================
    # RESONANCE TRACKING
    # =========================================================================

    async def add_resonance_score(self, task_id: str, score: float) -> None:
        """Append a resonance score snapshot to the task."""
        try:
            await self.db.query(
                """
                UPDATE $task_id SET
                    resonance_scores += [$score],
                    updated_at = time::now()
                """,
                {"task_id": task_id, "score": score},
            )
        except Exception as e:
            logger.error(f"Failed to add resonance score to {task_id}: {e}")

    # =========================================================================
    # FILE ANNOTATIONS
    # =========================================================================

    async def add_file_annotation(
        self,
        task_id: str,
        file_path: str,
        annotation: dict[str, Any],
    ) -> None:
        """Add a memory-backed annotation to a file within a task."""
        task = await self.get_task(task_id)
        if not task:
            return
        annotations = task.file_annotations
        if file_path not in annotations:
            annotations[file_path] = []
        annotations[file_path].append(annotation)
        await self.db.merge(task_id, {
            "file_annotations": annotations,
            "updated_at": datetime.utcnow().isoformat(),
        })

    async def save_file_version(
        self,
        task_id: str,
        file_path: str,
        content: str,
        step_number: int | None = None,
    ) -> None:
        """Save a snapshot of a file for diff/replay view.

        Keyed by {task_id}:{path}:{step_number} so any step can be replayed.
        """
        task = await self.get_task(task_id)
        if not task:
            return
        versions = task.file_versions
        if file_path not in versions:
            versions[file_path] = []
        versions[file_path].append({
            "content": content[:50000],  # Cap at 50KB per version
            "timestamp": datetime.utcnow().isoformat(),
            "step_number": step_number,
        })
        # Keep last 20 versions per file (more for replay)
        if len(versions[file_path]) > 20:
            versions[file_path] = versions[file_path][-20:]
        await self.db.merge(task_id, {
            "file_versions": versions,
            "updated_at": datetime.utcnow().isoformat(),
        })

    # =========================================================================
    # IDE CHAT PERSISTENCE
    # =========================================================================

    async def store_ide_chat_message(
        self,
        task_id: str,
        role: str,
        content: str,
        file_context: str = "",
    ) -> None:
        """Store an IDE chat message in the task's memory namespace."""
        task = await self.get_task(task_id)
        if not task:
            return
        try:
            from aura.engines.memory.manager import get_memory_manager
            mm = get_memory_manager()
            await mm.store_memory(
                content=content,
                namespace=task.task_memory_namespace,
                importance=0.6,
                tags=["ide_dialogue", role],
                metadata={
                    "type": "ide_dialogue",
                    "role": role,
                    "file_context": file_context,
                    "task_id": task_id,
                },
            )
        except Exception as e:
            logger.error(f"Failed to store IDE chat message for {task_id}: {e}")

    async def get_ide_chat_history(
        self,
        task_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch IDE dialogue memories from the task's namespace."""
        task = await self.get_task(task_id)
        if not task or not task.task_memory_namespace:
            return []
        try:
            result = await self.db.query(
                """
                SELECT * FROM memory
                WHERE namespace = $ns
                  AND tags CONTAINS 'ide_dialogue'
                ORDER BY timestamp ASC
                LIMIT $lim
                """,
                {"ns": task.task_memory_namespace, "lim": limit},
            )
            messages = []
            for row in (result or []):
                meta = row.get("metadata", {})
                messages.append({
                    "role": meta.get("role", "aura"),
                    "content": row.get("content", ""),
                    "file_context": meta.get("file_context", ""),
                    "timestamp": row.get("timestamp", ""),
                })
            return messages
        except Exception as e:
            logger.error(f"Failed to fetch IDE chat history for {task_id}: {e}")
            return []

    # =========================================================================
    # DELETE
    # =========================================================================

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task and its data."""
        try:
            await self.db.delete(task_id)
            logger.info(f"Task deleted: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            return False

    # =========================================================================
    # RESUME ON STARTUP
    # =========================================================================

    async def recover_interrupted_tasks(self) -> list[Task]:
        """Find tasks that were running when the system went down and pause them."""
        try:
            result = await self.db.query(
                """
                SELECT * FROM task
                WHERE status = 'running'
                """
            )
            # SurrealDB query() returns nested results; extract the actual rows
            rows = extract_rows(result)

            interrupted = []
            for row in rows:
                try:
                    task = Task(**row)
                    await self.db.merge(task.task_id, {
                        "status": TaskStatus.PAUSED.value,
                        "blocker": "System restart — task was interrupted",
                        "updated_at": datetime.utcnow().isoformat(),
                    })
                    interrupted.append(task)
                    logger.warning(f"Recovered interrupted task: {task.task_id} — {task.goal[:60]}")
                except Exception as e:
                    logger.error(f"Failed to recover task row: {e}")
            return interrupted
        except Exception as e:
            logger.error(f"recover_interrupted_tasks failed: {e}")
            return []


# =========================================================================
# SINGLETON
# =========================================================================

_task_queue: TaskQueueService | None = None


def get_task_queue() -> TaskQueueService:
    """Get the global TaskQueueService singleton."""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueueService()
    return _task_queue
