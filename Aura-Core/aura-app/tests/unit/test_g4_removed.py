"""T15: the agent loop, /agent/*, /workspace/* routes and the IDE page are gone."""
from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
SRC = APP_ROOT / "src" / "aura"

REMOVED_MODULES = {
    "aura.executor.agent_loop",
    "aura.api.routes.agent",
    "aura.api.routes.workspace",
}


def _imported_names(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def test_no_module_imports_removed_modules() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        hit = _imported_names(tree) & REMOVED_MODULES
        if hit:
            offenders.append((str(path.relative_to(APP_ROOT)), sorted(hit)))
    assert not offenders, offenders


def test_app_has_no_agent_or_workspace_routes() -> None:
    from aura.main import app

    bad = [
        r.path for r in app.routes
        if getattr(r, "path", "").startswith(("/agent/", "/workspace/"))
    ]
    assert not bad, bad


def test_ide_page_removed() -> None:
    assert not (APP_ROOT / "frontend" / "src" / "pages" / "ide.tsx").exists()
