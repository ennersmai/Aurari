# aura/tools/filesystem.py
"""
Filesystem tools for Aura.

Each tool follows the pattern:
- TOOL_DEFINITION: JSON Schema
- run(arguments: Dict[str, Any]) -> str
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Security: Allowed paths - environment-aware detection
if os.path.exists("/app/src/aura"):
    # Docker environment
    ALLOWED_PATHS = [
        Path("/app"),
        Path("/app/src/aura"),
    ]
elif os.path.exists("C:/Users"):
    # Windows local dev
    ALLOWED_PATHS = [
        Path.cwd(),
        Path.cwd() / "src" / "aura",
    ]
else:
    # Linux/Mac local dev or unknown
    ALLOWED_PATHS = [
        Path.cwd(),
        Path.cwd() / "src" / "aura",
    ]

logger.info(f"FileSystemTools detected allowed paths: {ALLOWED_PATHS}")

CORE_PATH_MARKERS = [
    "src/aura/engines/",
    "src/aura/orchestrator/",
    "src/aura/main.py",
]


def _is_core_path(path: str) -> bool:
    """Check if a path targets Aura's own core brain (engines, orchestrator, main)."""
    normalized = path.replace("\\", "/").lower()
    return any(marker in normalized for marker in CORE_PATH_MARKERS)


def _is_path_allowed(path: str) -> bool:
    """Check if path is within allowed directories."""
    path_obj = Path(path)
    
    # If path is relative, try resolving it from each allowed base
    if not path_obj.is_absolute():
        for base in ALLOWED_PATHS:
            try:
                full_path = (base / path_obj).resolve()
                if any(full_path.is_relative_to(allowed) for allowed in ALLOWED_PATHS):
                    return True
            except Exception:
                continue
        return False
    
    # If absolute, check directly
    resolved = path_obj.resolve()
    return any(
        resolved.is_relative_to(allowed) or resolved == allowed
        for allowed in ALLOWED_PATHS
    )


# ============================================================================
# READ_FILE
# ============================================================================

READ_FILE_DEFINITION = {
    "name": "read_file",
    "description": "Read the complete contents of a file. Use this to examine source code, configuration files, or any text-based files.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (relative or absolute)"
            }
        },
        "required": ["path"]
    }
}


async def read_file_run(arguments: Dict[str, Any]) -> str:
    """Read file contents."""
    path = arguments.get("path")
    
    if not path:
        return json.dumps({"error": "Missing 'path' argument"})
    
    if not _is_path_allowed(path):
        return json.dumps({"error": f"Access denied: {path}"})
    
    try:
        file_path = Path(path)
        if not file_path.exists():
            return json.dumps({"error": f"File not found: {path}"})
        
        if not file_path.is_file():
            return json.dumps({"error": f"Not a file: {path}"})
        
        content = file_path.read_text(encoding="utf-8")
        logger.info(f"📖 Read file: {path} ({len(content)} chars)")
        
        return json.dumps({
            "success": True,
            "path": str(file_path),
            "content": content,
            "size": len(content)
        })
        
    except Exception as e:
        logger.error(f"Failed to read file {path}: {e}")
        return json.dumps({"error": str(e)})


# ============================================================================
# LIST_DIRECTORY
# ============================================================================

LIST_DIRECTORY_DEFINITION = {
    "name": "list_directory",
    "description": "List all files and directories in a given path. Shows file types and sizes.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list (default: current directory)",
                "default": "."
            }
        }
    }
}


async def list_directory_run(arguments: Dict[str, Any]) -> str:
    """List directory contents."""
    path = arguments.get("path", ".")
    
    if not _is_path_allowed(path):
        return json.dumps({"error": f"Access denied: {path}"})
    
    try:
        dir_path = Path(path)
        if not dir_path.exists():
            return json.dumps({"error": f"Directory not found: {path}"})
        
        if not dir_path.is_dir():
            return json.dumps({"error": f"Not a directory: {path}"})
        
        entries = []
        for item in sorted(dir_path.iterdir()):
            entry = {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "path": str(item),
            }
            
            if item.is_file():
                entry["size"] = item.stat().st_size
            
            entries.append(entry)
        
        logger.info(f"📂 Listed directory: {path} ({len(entries)} entries)")
        
        return json.dumps({
            "success": True,
            "path": str(dir_path),
            "entries": entries,
            "count": len(entries)
        })
        
    except Exception as e:
        logger.error(f"Failed to list directory {path}: {e}")
        return json.dumps({"error": str(e)})


# ============================================================================
# DIRECTORY_TREE
# ============================================================================

DIRECTORY_TREE_DEFINITION = {
    "name": "directory_tree",
    "description": "Get a hierarchical tree view of directories and files. Useful for understanding project structure.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Root directory path",
                "default": "."
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth to traverse (default: 3)",
                "default": 3
            }
        }
    }
}


async def directory_tree_run(arguments: Dict[str, Any]) -> str:
    """Get directory tree structure."""
    path = arguments.get("path", ".")
    max_depth = arguments.get("max_depth", 3)
    
    if not _is_path_allowed(path):
        return json.dumps({"error": f"Access denied: {path}"})
    
    def build_tree(current_path: Path, current_depth: int = 0) -> Dict[str, Any]:
        """Recursively build tree structure."""
        tree = {
            "name": current_path.name or str(current_path),
            "type": "directory",
            "path": str(current_path),
            "children": []
        }
        
        if current_depth >= max_depth:
            tree["truncated"] = True
            return tree
        
        try:
            for item in sorted(current_path.iterdir()):
                if item.is_dir():
                    subtree = build_tree(item, current_depth + 1)
                    tree["children"].append(subtree)
                else:
                    tree["children"].append({
                        "name": item.name,
                        "type": "file",
                        "path": str(item),
                        "size": item.stat().st_size
                    })
        except PermissionError:
            tree["error"] = "Permission denied"
        
        return tree
    
    try:
        dir_path = Path(path)
        if not dir_path.exists():
            return json.dumps({"error": f"Directory not found: {path}"})
        
        tree = build_tree(dir_path)
        logger.info(f"🌳 Built directory tree: {path}")
        
        return json.dumps({
            "success": True,
            "tree": tree
        })
        
    except Exception as e:
        logger.error(f"Failed to build directory tree for {path}: {e}")
        return json.dumps({"error": str(e)})


# ============================================================================
# SEARCH_FILES
# ============================================================================

SEARCH_FILES_DEFINITION = {
    "name": "search_files",
    "description": "Search for files matching a pattern (glob syntax). Example patterns: '*.py', '**/*.md', 'engine*.py'",
    "inputSchema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files"
            },
            "root_path": {
                "type": "string",
                "description": "Root directory to search from",
                "default": "."
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": 100
            }
        },
        "required": ["pattern"]
    }
}


async def search_files_run(arguments: Dict[str, Any]) -> str:
    """Search for files matching pattern."""
    pattern = arguments.get("pattern")
    root_path = arguments.get("root_path", ".")
    max_results = arguments.get("max_results", 100)
    
    if not pattern:
        return json.dumps({"error": "Missing 'pattern' argument"})
    
    if not _is_path_allowed(root_path):
        return json.dumps({"error": f"Access denied: {root_path}"})
    
    try:
        dir_path = Path(root_path)
        results = []
        
        for match in dir_path.glob(pattern):
            if len(results) >= max_results:
                break
            if match.is_file():
                results.append({
                    "path": str(match),
                    "name": match.name,
                    "size": match.stat().st_size
                })
        
        logger.info(f"🔍 Search '{pattern}' in {root_path}: {len(results)} results")
        
        return json.dumps({
            "success": True,
            "pattern": pattern,
            "root_path": str(dir_path),
            "results": results,
            "count": len(results)
        })
        
    except Exception as e:
        logger.error(f"Failed to search files: {e}")
        return json.dumps({"error": str(e)})


# ============================================================================
# GET_FILE_INFO
# ============================================================================

GET_FILE_INFO_DEFINITION = {
    "name": "get_file_info",
    "description": "Get detailed metadata about a file or directory (size, modified time, type, etc.)",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to get info about"
            }
        },
        "required": ["path"]
    }
}


async def get_file_info_run(arguments: Dict[str, Any]) -> str:
    """Get file metadata."""
    path = arguments.get("path")
    
    if not path:
        return json.dumps({"error": "Missing 'path' argument"})
    
    if not _is_path_allowed(path):
        return json.dumps({"error": f"Access denied: {path}"})
    
    try:
        file_path = Path(path)
        if not file_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})
        
        stat = file_path.stat()
        
        info = {
            "path": str(file_path),
            "name": file_path.name,
            "type": "directory" if file_path.is_dir() else "file",
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
        }
        
        if file_path.is_file():
            info["extension"] = file_path.suffix
        
        logger.info(f"ℹ️ Got file info: {path}")
        
        return json.dumps({
            "success": True,
            "info": info
        })
        
    except Exception as e:
        logger.error(f"Failed to get file info for {path}: {e}")
        return json.dumps({"error": str(e)})


# ============================================================================
# WRITE_FILE
# ============================================================================

WRITE_FILE_DEFINITION = {
    "name": "write_file",
    "description": "Write content to a file. Creates the file if it doesn't exist, or overwrites if it does. Creates parent directories automatically.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        },
        "required": ["path", "content"]
    }
}


async def write_file_run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Write content to a file."""
    path = arguments.get("path")
    content = arguments.get("content")
    force_execute: bool = bool(arguments.get("force_execute", False))

    if not path:
        return {"status": "ERROR", "success": False, "error": "Missing 'path' argument"}
    if content is None:
        return {"status": "ERROR", "success": False, "error": "Missing 'content' argument"}

    if not _is_path_allowed(path):
        return {"status": "ERROR", "success": False, "error": f"Access denied: {path}"}

    if _is_core_path(path) and not force_execute:
        logger.info(f"⛔ Core modification intercepted: {path}")
        return {
            "status": "WAITING_APPROVAL",
            "message": f"Core modification requested for {path}. User approval required.",
            "pending_file": path,
            "pending_content": content,
            "success": False,
        }

    try:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(content, encoding="utf-8")
        logger.info(f"✏️ Wrote file: {path} ({len(content)} chars)")

        result: Dict[str, Any] = {
            "status": "OK",
            "success": True,
            "path": str(file_path),
            "size": len(content),
        }
        if _is_core_path(path):
            result["message"] = "Core file updated. A /system/restart is required to apply changes."
            result["restart_required"] = True
        return result

    except Exception as e:
        logger.error(f"Failed to write file {path}: {e}")
        return {"status": "ERROR", "success": False, "error": str(e)}


# ============================================================================
# EDIT_FILE
# ============================================================================

EDIT_FILE_DEFINITION = {
    "name": "edit_file",
    "description": "Edit a file by replacing a specific string with new content. Useful for targeted modifications without rewriting the entire file.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit"
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find and replace"
            },
            "new_string": {
                "type": "string",
                "description": "The replacement string"
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences (default: false, replaces first only)",
                "default": False
            }
        },
        "required": ["path", "old_string", "new_string"]
    }
}


async def edit_file_run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Edit a file by replacing a string."""
    path = arguments.get("path")
    old_string = arguments.get("old_string")
    new_string = arguments.get("new_string")
    replace_all = arguments.get("replace_all", False)
    force_execute: bool = bool(arguments.get("force_execute", False))

    if not path:
        return {"status": "ERROR", "success": False, "error": "Missing 'path' argument"}
    if old_string is None:
        return {"status": "ERROR", "success": False, "error": "Missing 'old_string' argument"}
    if new_string is None:
        return {"status": "ERROR", "success": False, "error": "Missing 'new_string' argument"}

    if not _is_path_allowed(path):
        return {"status": "ERROR", "success": False, "error": f"Access denied: {path}"}

    if _is_core_path(path) and not force_execute:
        logger.info(f"⛔ Core modification intercepted: {path}")
        return {
            "status": "WAITING_APPROVAL",
            "message": f"Core modification requested for {path}. User approval required.",
            "pending_file": path,
            "pending_content": new_string,
            "success": False,
        }

    try:
        file_path = Path(path)
        if not file_path.exists():
            return {"status": "ERROR", "success": False, "error": f"File not found: {path}"}

        content = file_path.read_text(encoding="utf-8")

        if old_string not in content:
            return {"status": "ERROR", "success": False, "error": f"String not found in file: '{old_string[:100]}...'"}

        if replace_all:
            count = content.count(old_string)
            new_content = content.replace(old_string, new_string)
        else:
            count = 1
            new_content = content.replace(old_string, new_string, 1)

        file_path.write_text(new_content, encoding="utf-8")
        logger.info(f"📝 Edited file: {path} ({count} replacement(s))")

        result: Dict[str, Any] = {
            "status": "OK",
            "success": True,
            "path": str(file_path),
            "replacements": count,
            "new_size": len(new_content),
        }
        if _is_core_path(path):
            result["message"] = "Core file updated. A /system/restart is required to apply changes."
            result["restart_required"] = True
        return result

    except Exception as e:
        logger.error(f"Failed to edit file {path}: {e}")
        return {"status": "ERROR", "success": False, "error": str(e)}


# ============================================================================
# CREATE_DIRECTORY
# ============================================================================

CREATE_DIRECTORY_DEFINITION = {
    "name": "create_directory",
    "description": "Create a new directory, including any necessary parent directories.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path of the directory to create"
            }
        },
        "required": ["path"]
    }
}


async def create_directory_run(arguments: Dict[str, Any]) -> str:
    """Create a directory."""
    path = arguments.get("path")

    if not path:
        return json.dumps({"error": "Missing 'path' argument"})

    if not _is_path_allowed(path):
        return json.dumps({"error": f"Access denied: {path}"})

    try:
        dir_path = Path(path)
        already_existed = dir_path.exists()
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Created directory: {path}")

        return json.dumps({
            "success": True,
            "path": str(dir_path),
            "already_existed": already_existed
        })

    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}")
        return json.dumps({"error": str(e)})


# ============================================================================
# DELETE_FILE
# ============================================================================

DELETE_FILE_DEFINITION = {
    "name": "delete_file",
    "description": "Delete a file or empty directory. Will NOT delete non-empty directories for safety.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file or empty directory to delete"
            }
        },
        "required": ["path"]
    }
}


async def delete_file_run(arguments: Dict[str, Any]) -> str:
    """Delete a file or empty directory."""
    path = arguments.get("path")

    if not path:
        return json.dumps({"error": "Missing 'path' argument"})

    if not _is_path_allowed(path):
        return json.dumps({"error": f"Access denied: {path}"})

    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        if target.is_file():
            size = target.stat().st_size
            target.unlink()
            logger.info(f"🗑️ Deleted file: {path} ({size} bytes)")
            return json.dumps({
                "success": True,
                "path": str(target),
                "type": "file",
                "size_deleted": size
            })
        elif target.is_dir():
            # Safety: Only delete empty directories
            if any(target.iterdir()):
                return json.dumps({
                    "error": f"Directory is not empty: {path}. Cannot delete non-empty directories for safety."
                })
            target.rmdir()
            logger.info(f"🗑️ Deleted empty directory: {path}")
            return json.dumps({
                "success": True,
                "path": str(target),
                "type": "directory"
            })
        else:
            return json.dumps({"error": f"Unknown path type: {path}"})

    except Exception as e:
        logger.error(f"Failed to delete {path}: {e}")
        return json.dumps({"error": str(e)})


# ============================================================================
# EXPORTS
# ============================================================================

# Export all tools
TOOLS = {
    "read_file": {
        "definition": READ_FILE_DEFINITION,
        "run": read_file_run
    },
    "list_directory": {
        "definition": LIST_DIRECTORY_DEFINITION,
        "run": list_directory_run
    },
    "directory_tree": {
        "definition": DIRECTORY_TREE_DEFINITION,
        "run": directory_tree_run
    },
    "search_files": {
        "definition": SEARCH_FILES_DEFINITION,
        "run": search_files_run
    },
    "get_file_info": {
        "definition": GET_FILE_INFO_DEFINITION,
        "run": get_file_info_run
    },
    "write_file": {
        "definition": WRITE_FILE_DEFINITION,
        "run": write_file_run
    },
    "edit_file": {
        "definition": EDIT_FILE_DEFINITION,
        "run": edit_file_run
    },
    "create_directory": {
        "definition": CREATE_DIRECTORY_DEFINITION,
        "run": create_directory_run
    },
    "delete_file": {
        "definition": DELETE_FILE_DEFINITION,
        "run": delete_file_run
    }
}