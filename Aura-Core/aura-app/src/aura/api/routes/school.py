"""Dynamic Skill Synthesis API routes."""

import ast
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter()

_learning_engine: Any = None
_llm_layers: Any = None

BLOCKED_IMPORTS = {"os", "sys", "subprocess", "shutil", "socket", "pty", "builtins"}
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def set_dependencies(learning_engine: Any, llm_layers: Any) -> None:
    global _learning_engine, _llm_layers
    _learning_engine = learning_engine
    _llm_layers = llm_layers


def get_learning_engine() -> Any:
    if _learning_engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Learning engine not initialized",
        )
    return _learning_engine


def get_llm_layers() -> Any:
    if _llm_layers is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM layers not initialized",
        )
    return _llm_layers


class SynthesizeRequest(BaseModel):
    request: str = Field(..., min_length=3, max_length=1000)


def validate_synthesized_code(code: str) -> ast.Module:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Generated code is not valid Python: {e.msg} at line {e.lineno}",
        ) from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in BLOCKED_IMPORTS:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Security violation: blocked import '{alias.name}'",
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = (node.module or "").split(".", 1)[0]
            if module_name in BLOCKED_IMPORTS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Security violation: blocked import from '{node.module}'",
                )

    return tree


def extract_tool_name(tree: ast.Module) -> str:
    for node in tree.body:
        value_node: ast.AST | None = None
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "TOOL_DEFINITION" for target in node.targets):
                value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "TOOL_DEFINITION":
                value_node = node.value

        if value_node is None:
            continue

        try:
            definition = ast.literal_eval(value_node)
        except (ValueError, SyntaxError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TOOL_DEFINITION must be a literal dictionary",
            ) from e

        if not isinstance(definition, dict) or not isinstance(definition.get("name"), str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TOOL_DEFINITION must contain a string 'name' field",
            )

        tool_name = definition["name"].strip().lower()
        if not TOOL_NAME_PATTERN.match(tool_name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TOOL_DEFINITION.name must be snake_case, start with a letter, and contain only lowercase letters, numbers, and underscores",
            )
        return tool_name

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Generated code must define TOOL_DEFINITION",
    )


def assert_run_function(tree: ast.Module) -> None:
    if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run" for node in tree.body):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generated code must define a run() function",
        )


@router.post("/synthesize")
async def synthesize_skill(request: SynthesizeRequest) -> dict[str, Any]:
    learning_engine = get_learning_engine()
    llm_layers = get_llm_layers()

    prompt = f"""Generate a single Aura local tool Python module for this skill request: {request.request}

Output ONLY valid Python source code. Do not output markdown, code fences, prose, or explanations.
The module must match Aura local tools exactly:
- Define TOOL_DEFINITION as a literal dictionary with name, description, and parameters JSON schema.
- Define async def run(arguments: Dict[str, Any]) -> str or def run(arguments: Dict[str, Any]) -> str.
- The tool name must be lowercase snake_case and suitable as a Python filename.
- Keep the tool self-contained and safe.
- Do not import os, sys, subprocess, shutil, socket, pty, or builtins.
- Do not read, write, delete, or execute local files or shell commands.
"""

    try:
        code = await llm_layers.client.complete(
            messages=[
                {
                    "role": "system",
                    "content": "You synthesize safe Aura local tool modules. Return raw Python only.",
                },
                {"role": "user", "content": prompt},
            ],
            model=llm_layers.l3_model,
            temperature=0.2,
            max_tokens=2000,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"L3 synthesis failed: {str(e)}",
        ) from e

    code = code.strip()
    tree = validate_synthesized_code(code)
    assert_run_function(tree)
    tool_name = extract_tool_name(tree)

    skills_dir = Path(__file__).resolve().parents[2] / "tools" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    init_file = skills_dir / "__init__.py"
    init_file.touch(exist_ok=True)

    target_file = skills_dir / f"{tool_name}.py"
    target_file.write_text(code + "\n", encoding="utf-8")

    try:
        ingest_result = await learning_engine.ingest_local_tool_module(f"skills.{tool_name}")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Skill file written but hot-load failed: {str(e)}",
        ) from e

    return {
        "success": True,
        "tool_name": tool_name,
        "module_name": f"skills.{tool_name}",
        "message": ingest_result,
    }
