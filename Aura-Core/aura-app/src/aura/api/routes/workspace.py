"""Workspace API routes for Aura's IDE.

Provides file tree, file contents, diff, and file-system watcher endpoints
that power the IDE frontend.  All mutations go through Aura's filesystem
tools so every action is logged in task memory.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from aura.config import settings

# Background watcher task handle
_watcher_task: asyncio.Task | None = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspace", tags=["workspace"])

# Global references (set during startup)
_task_queue: Any = None


def set_task_queue(tq: Any) -> None:
    """Set the task queue reference from main.py lifespan."""
    global _task_queue
    _task_queue = tq


def _get_workspace_root() -> Path:
    """Resolve Aura's workspace directory."""
    if settings.aura_workspace_path:
        ws = Path(settings.aura_workspace_path)
    else:
        ws = Path.cwd() / "aura_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ============================================================================
# SCHEMAS
# ============================================================================

class FileWriteRequest(BaseModel):
    content: str = Field(..., description="File content to write")


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/tree")
async def get_workspace_tree(
    max_depth: int = 4,
    path: str = "",
) -> dict[str, Any]:
    """Recursive file tree of AURA_WORKSPACE_PATH with Aura's task annotations."""
    root = _get_workspace_root()
    target = root / path if path else root

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")

    def build_tree(current: Path, depth: int = 0) -> dict[str, Any]:
        node: dict[str, Any] = {
            "name": current.name or str(current),
            "path": str(current.relative_to(root)),
            "type": "directory",
        }
        if depth >= max_depth:
            node["truncated"] = True
            return node

        children: list[dict[str, Any]] = []
        try:
            for item in sorted(current.iterdir()):
                # Skip hidden dirs and common noise
                if item.name.startswith(".") or item.name in (
                    "__pycache__", "node_modules", ".git", ".venv", "venv",
                ):
                    continue
                if item.is_dir():
                    children.append(build_tree(item, depth + 1))
                else:
                    child: dict[str, Any] = {
                        "name": item.name,
                        "path": str(item.relative_to(root)),
                        "type": "file",
                        "size": item.stat().st_size,
                        "modified": item.stat().st_mtime,
                    }
                    children.append(child)
        except PermissionError:
            node["error"] = "Permission denied"

        node["children"] = children
        return node

    tree = build_tree(target)

    # Attach task annotations if we have an active task
    annotations: dict[str, Any] = {}
    if _task_queue:
        active_task = await _task_queue.get_active_task()
        if active_task and active_task.file_annotations:
            annotations = active_task.file_annotations

    return {
        "success": True,
        "workspace": str(root),
        "tree": tree,
        "annotations": annotations,
    }


@router.get("/file/{path:path}")
async def get_workspace_file(path: str) -> dict[str, Any]:
    """File contents + Aura's memory annotations for that file."""
    root = _get_workspace_root()
    file_path = root / path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {path}")

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Fetch annotations from active task
    annotations: list[dict[str, Any]] = []
    if _task_queue:
        active_task = await _task_queue.get_active_task()
        if active_task and path in active_task.file_annotations:
            annotations = active_task.file_annotations[path]

    return {
        "success": True,
        "path": path,
        "content": content,
        "size": len(content),
        "modified": file_path.stat().st_mtime,
        "annotations": annotations,
    }


@router.post("/file/{path:path}")
async def save_workspace_file(path: str, body: FileWriteRequest) -> dict[str, Any]:
    """Save file through Aura's filesystem tools so it's logged."""
    root = _get_workspace_root()
    file_path = root / path

    # Save previous version for diff
    if _task_queue and file_path.exists():
        active_task = await _task_queue.get_active_task()
        if active_task:
            try:
                old_content = file_path.read_text(encoding="utf-8", errors="replace")
                await _task_queue.save_file_version(active_task.task_id, path, old_content)
            except Exception:
                pass

    # Write file
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(body.content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "success": True,
        "path": path,
        "size": len(body.content),
    }


@router.get("/diff/{path:path}")
async def get_file_diff(path: str) -> dict[str, Any]:
    """Diff current file vs previous version from task history."""
    root = _get_workspace_root()
    file_path = root / path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    current = file_path.read_text(encoding="utf-8", errors="replace")

    previous = None
    if _task_queue:
        active_task = await _task_queue.get_active_task()
        if active_task and path in active_task.file_versions:
            versions = active_task.file_versions[path]
            if versions:
                previous = versions[-1].get("content")

    return {
        "success": True,
        "path": path,
        "current": current,
        "previous": previous,
        "has_diff": previous is not None and previous != current,
    }


# ============================================================================
# WEBSOCKET: File system watcher
# ============================================================================

# Active WebSocket connections for file watching
_watch_connections: list[WebSocket] = []


def _build_file_node(item: Path, root: Path) -> dict[str, Any]:
    """Build a FileNode dict for a single filesystem item."""
    rel = str(item.relative_to(root))
    if item.is_dir():
        return {"name": item.name, "path": rel, "type": "directory"}
    try:
        stat = item.stat()
        return {
            "name": item.name,
            "path": rel,
            "type": "file",
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }
    except Exception:
        return {"name": item.name, "path": rel, "type": "file"}


async def notify_file_change(event_type: str, path: str, **extra: Any) -> None:
    """Push file-change events to all connected IDE clients."""
    root = _get_workspace_root()
    node = None
    full_path = root / path
    if full_path.exists():
        node = _build_file_node(full_path, root)

    message = json.dumps({
        "type": event_type,
        "path": path,
        "node": node,
        "timestamp": datetime.utcnow().isoformat(),
        **{k: v for k, v in extra.items() if k != "node"},
    })
    dead: list[WebSocket] = []
    for ws in _watch_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _watch_connections.remove(ws)


async def _filesystem_watcher() -> None:
    """Background coroutine that watches the workspace for changes using polling.

    Uses a simple stat-based approach to detect created/modified/deleted files
    without requiring watchfiles as a dependency.
    """
    root = _get_workspace_root()
    skip = {".git", "__pycache__", "node_modules", ".venv", "venv"}
    prev_snapshot: dict[str, float] = {}

    def _scan(directory: Path) -> dict[str, float]:
        result: dict[str, float] = {}
        try:
            for item in directory.rglob("*"):
                # Skip hidden and noisy directories
                parts = item.relative_to(root).parts
                if any(p.startswith(".") or p in skip for p in parts):
                    continue
                try:
                    result[str(item.relative_to(root))] = item.stat().st_mtime
                except Exception:
                    pass
        except Exception:
            pass
        return result

    # Initial scan
    prev_snapshot = _scan(root)
    logger.info(f"Workspace watcher started — tracking {len(prev_snapshot)} items")

    while True:
        await asyncio.sleep(2.0)  # Poll every 2 seconds
        if not _watch_connections:
            # No clients, still scan to keep snapshot current
            prev_snapshot = _scan(root)
            continue

        current = _scan(root)

        # Detect created
        for path in current.keys() - prev_snapshot.keys():
            await notify_file_change("created", path)

        # Detect deleted
        for path in prev_snapshot.keys() - current.keys():
            await notify_file_change("deleted", path)

        # Detect modified
        for path in current.keys() & prev_snapshot.keys():
            if current[path] != prev_snapshot[path]:
                await notify_file_change("modified", path)

        prev_snapshot = current


def start_workspace_watcher() -> None:
    """Start the background filesystem watcher (call from main.py lifespan)."""
    global _watcher_task
    if _watcher_task is None or _watcher_task.done():
        _watcher_task = asyncio.create_task(_filesystem_watcher())
        logger.info("Workspace filesystem watcher task created")


@router.websocket("/watch")
async def workspace_watch(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time file change notifications.

    On connect: sends the full initial tree.
    Ongoing: receives delta events from the background watcher.
    Client can send 'ping' for keepalive.
    """
    await websocket.accept()
    _watch_connections.append(websocket)
    logger.info(f"IDE file watcher connected ({len(_watch_connections)} total)")

    # Send initial full tree
    try:
        root = _get_workspace_root()

        def _quick_tree(current: Path, depth: int = 0) -> dict[str, Any]:
            node: dict[str, Any] = {
                "name": current.name or str(current),
                "path": str(current.relative_to(root)),
                "type": "directory",
            }
            if depth >= 4:
                node["truncated"] = True
                return node
            children: list[dict[str, Any]] = []
            try:
                for item in sorted(current.iterdir()):
                    if item.name.startswith(".") or item.name in (
                        "__pycache__", "node_modules", ".git", ".venv", "venv",
                    ):
                        continue
                    if item.is_dir():
                        children.append(_quick_tree(item, depth + 1))
                    else:
                        children.append(_build_file_node(item, root))
            except PermissionError:
                node["error"] = "Permission denied"
            node["children"] = children
            return node

        tree = _quick_tree(root)
        await websocket.send_text(json.dumps({
            "type": "initial_tree",
            "tree": tree,
            "timestamp": datetime.utcnow().isoformat(),
        }))
    except Exception as e:
        logger.error(f"Failed to send initial tree: {e}")

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _watch_connections:
            _watch_connections.remove(websocket)
        logger.info(f"IDE file watcher disconnected ({len(_watch_connections)} total)")


# ============================================================================
# IDE CHAT ENDPOINTS
# ============================================================================

class IdeChatRequest(BaseModel):
    message: str
    task_id: str | None = None
    file_context: str = ""


@router.post("/ide-chat")
async def ide_chat_send(body: IdeChatRequest) -> dict[str, Any]:
    """Store an IDE chat message and return stored status."""
    if not _task_queue or not body.task_id:
        return {"success": False, "error": "No active task for chat persistence"}
    await _task_queue.store_ide_chat_message(
        task_id=body.task_id,
        role="user",
        content=body.message,
        file_context=body.file_context,
    )
    return {"success": True}


@router.post("/ide-chat/aura")
async def ide_chat_store_aura(body: IdeChatRequest) -> dict[str, Any]:
    """Store Aura's IDE chat response."""
    if not _task_queue or not body.task_id:
        return {"success": False, "error": "No active task for chat persistence"}
    await _task_queue.store_ide_chat_message(
        task_id=body.task_id,
        role="aura",
        content=body.message,
        file_context=body.file_context,
    )
    return {"success": True}


@router.get("/ide-chat/{task_id}")
async def ide_chat_history(task_id: str, limit: int = 20) -> dict[str, Any]:
    """Fetch IDE chat history for a task."""
    if not _task_queue:
        return {"success": False, "messages": []}
    if not task_id.startswith("task:"):
        task_id = f"task:{task_id}"
    messages = await _task_queue.get_ide_chat_history(task_id, limit=limit)
    return {"success": True, "messages": messages}
