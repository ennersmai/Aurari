"""
Tool Executor - Execution Layer for Aura v0.4.0.

Parses tool calls from L3's output and executes them (MCP or local).
"""

import asyncio
import json
import logging
import re
import importlib.util
import os
import time
from typing import Any, Dict, Literal, Optional, Tuple

from aura.config import settings
from aura.db.client import get_db_client
from aura.executor.tool_registry import get_tool_registry
from aura.tiers import TIER_UNAVAILABLE_ERROR, active_profile, tool_allowed

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes tool calls from L3's responses.
    
    Supports:
    - MCP Tools: JSON-RPC calls to MCP servers
    - Local Tools: Python functions in src/aura/tools/
    - Self-Healing: Uses L5 to auto-repair malformed tool arguments on failure
    """
    
    # Patterns that indicate an argument error (not a runtime error)
    _ARG_ERROR_PATTERNS = [
        r"Missing\s+['\"]\w+['\"]\s+argument",
        r"Missing\s+required",
        r"must be a",
        r"expected\s+\w+\s+but got",
        r"is not valid",
        r"Invalid\s+\w+",
        r"required.*argument",
        r"argument.*required",
    ]
    
    def __init__(self):
        """Initialize tool executor."""
        self.db = get_db_client()
        self.logger = logging.getLogger("aura.executor")
        self._llm_layers = None  # Set via set_llm_layers() for self-healing
    
    def set_llm_layers(self, llm_layers: Any) -> None:
        """Inject LLM layers for L5-powered argument self-healing."""
        self._llm_layers = llm_layers
        
    def extract_tool_calls(self, text: str) -> list[Dict[str, Any]]:
        """
        Extract tool call JSON blocks from L3's text response.
        
        Supports formats:
        1. JSON code block: ```json {"tool": "...", "arguments": {...}} ```
        2. Inline JSON: {"tool": "...", "arguments": {...}}
        3. Multi-line JSON: { ... "tool" ... }
        4. Bracket format: [tool: function_name(arg1="value", arg2="value")]
        
        Args:
            text: L3's response text
            
        Returns:
            List of parsed tool call dictionaries
        """
        tool_calls = []
        
        # Pattern 1: JSON code block
        code_block_pattern = r'```(?:json)?\s*(\{.*?"tool".*?\})\s*```'
        matches = re.finditer(code_block_pattern, text, re.DOTALL)
        for match in matches:
            try:
                tool_call = json.loads(match.group(1))
                if "tool" in tool_call:
                    tool_calls.append(tool_call)
            except json.JSONDecodeError:
                self.logger.warning(f"Failed to parse tool call from code block: {match.group(1)[:100]}")
        
        # Pattern 2: Inline JSON object (look for { "tool": ... })
        inline_pattern = r'\{[^{}]*"tool"[^{}]*\}'
        matches = re.finditer(inline_pattern, text, re.DOTALL)
        for match in matches:
            try:
                tool_call = json.loads(match.group(0))
                if "tool" in tool_call and tool_call not in tool_calls:
                    tool_calls.append(tool_call)
            except json.JSONDecodeError:
                pass  # Not valid JSON, skip
        
        # Pattern 3: Multi-line JSON (more flexible)
        # Look for { ... } blocks that contain "tool" key
        multiline_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*"tool"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = re.finditer(multiline_pattern, text, re.DOTALL)
        for match in matches:
            try:
                tool_call = json.loads(match.group(0))
                if "tool" in tool_call and tool_call not in tool_calls:
                    tool_calls.append(tool_call)
            except json.JSONDecodeError:
                pass
        
        # Pattern 4: Bracket format [tool: function_name(args)]
        bracket_pattern = r'\[tool:\s*([a-z_]+)\((.*?)\)\]'
        matches = re.finditer(bracket_pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                tool_name = match.group(1).strip()
                args_str = match.group(2).strip()
                
                # Parse arguments (simple key="value" parser)
                arguments = {}
                if args_str:
                    # Match key="value" or key='value' pairs
                    arg_pattern = r'(\w+)\s*=\s*["\']([^"\']*)["\']'
                    for arg_match in re.finditer(arg_pattern, args_str):
                        key = arg_match.group(1)
                        value = arg_match.group(2)
                        arguments[key] = value
                
                tool_call = {
                    "tool": tool_name,
                    "arguments": arguments
                }
                
                if tool_call not in tool_calls:
                    tool_calls.append(tool_call)
                    self.logger.info(f"Extracted bracket-format tool call: {tool_name} with args: {arguments}")
            except Exception as e:
                self.logger.warning(f"Failed to parse bracket-format tool call: {e}")
        
        if tool_calls:
            self.logger.info(f"Extracted {len(tool_calls)} tool call(s) from L3 response")
        
        return tool_calls
    
    async def _check_pursuit_grant(
        self, tool_name: str, autonomous: Any
    ) -> Dict[str, Any] | None:
        """None when the autonomous call may run, else the refusal result."""
        from aura.autonomy import grants

        goal_id = autonomous.get("goal_id") if isinstance(autonomous, dict) else None
        source = (autonomous.get("source") if isinstance(autonomous, dict) else None) or "autonomy"
        risk: Any = None
        try:
            record = get_tool_registry().get(tool_name)
            risk = record.risk if record is not None else None
            if await grants.check(goal_id, risk):
                return None
        except Exception as e:  # noqa: BLE001 - fail closed
            self.logger.warning(f"pursuit grant check failed for {tool_name}: {e}")
        try:
            await grants.refuse(goal_id, tool_name, risk, str(source))
        except Exception as e:  # noqa: BLE001 - the refusal holds regardless
            self.logger.warning(f"pursuit grant refusal record failed: {e}")
        return {
            "success": False,
            "result": "",
            "error": (
                f"Tool '{tool_name}' needs an owner grant for autonomous work on this goal. "
                "A decision has been raised for the owner."
            ),
            "tool_name": tool_name,
        }

    async def execute_tool_call(
        self,
        tool_call: Dict[str, Any],
        *,
        requester_role: Literal["owner", "trusted", "guest"],
        approved: bool = False,
        venue: str = "app",
        session: Any = None,
        conversation_id: str | None = None,
        autonomous: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute a single tool call.
        
        Args:
            tool_call: Dictionary with "tool" and "arguments" keys
            requester_role: Role of the caller. Only "owner" may execute tools;
                other roles are refused before any tool is run.
            venue: Venue of the call. With ``requester_role`` it reaches the
                tool in the reserved ``_venue`` / ``_requester_role`` arguments.
            autonomous: Reserved ``_autonomous`` context (B3-04), set only by
                autonomous callers: ``{"goal_id": ..., "source": ...}``. Never
                part of the model-visible schema. Under ``goals_v2_enabled``
                a call above ``read`` risk needs a live pursuit grant.
            approved: When true, the runtime has already obtained user
                approval for this call (e.g. a previously-gated terminal or
                filesystem write). The executor sets the reserved
                ``_runtime_approved`` flag on the arguments so the tool's
                safety gate lets it through. The model may never set this
                flag itself: ``force_execute`` and every underscore-prefixed
                key are stripped from the model-supplied arguments first.
            
        Returns:
            Dictionary with execution result:
            {
                "success": bool,
                "result": str,
                "error": Optional[str],
                "tool_name": str
            }
        """
        # Requester-role gate (W1-01, agency S1). Only the owner may execute
        # tools. Refuse every other role before doing anything else.
        if requester_role != "owner":
            return {
                "success": False,
                "result": "",
                "error": "Tool use is not available to this user.",
                "tool_name": tool_call.get("tool", "unknown"),
            }

        tool_name = tool_call.get("tool")
        arguments = tool_call.get("arguments", {})
        if not isinstance(arguments, dict):
            # Defensive: don't mutate a non-dict the tool may not expect.
            arguments = {}
        else:
            # Approval travels in a reserved key that only the executor may
            # set (W1-02, agency S2). Strip the legacy ``force_execute`` key
            # and every underscore-prefixed key from the model-supplied
            # arguments before the tool runs, so a model cannot bypass the
            # safety gate by forging them. Then, only when the runtime has
            # approved this call, set the reserved flag the tools read.
            arguments = {
                k: v for k, v in arguments.items()
                if k != "force_execute" and not k.startswith("_")
            }
            if approved:
                arguments["_runtime_approved"] = True
            arguments["_venue"] = venue
            arguments["_requester_role"] = requester_role
            # delegate_work reads the session scope here (G4-04a). Only that
            # tool gets it: other tools, MCP included, never see the object.
            if session is not None and tool_name == "delegate_work":
                arguments["_session"] = session
            # plan_task reports into this conversation (P2-11); same reserved-key rule.
            # delegate_work links a passing task to the requesting turn (B1-03).
            if conversation_id and tool_name in ("plan_task", "delegate_work"):
                arguments["_conversation_id"] = conversation_id

        
        if not tool_name:
            return {
                "success": False,
                "result": "",
                "error": "Missing 'tool' field in tool call",
                "tool_name": "unknown"
            }

        # Tier gate (P2-03, D3). Runs after the role check, which stays first.
        if settings.tier_profiles_enabled and not tool_allowed(active_profile(), tool_name):
            return {
                "success": False,
                "result": "",
                "error": f"Tool '{tool_name}' is {TIER_UNAVAILABLE_ERROR}.",
                "tool_name": tool_name,
            }

        # Session scope gate (G4-04a). Last: role, then tier, then session.
        # None or the main session (no allow/deny list) changes nothing.
        if session is not None:
            allowed, reason = session.is_tool_allowed(tool_name)
            if not allowed:
                return {
                    "success": False,
                    "result": "",
                    "error": reason,
                    "tool_name": tool_name,
                }

        # Pursuit grant gate (B3-04). After role, tier and session; only for
        # autonomous calls. Fails closed: any error or unknown risk refuses.
        if autonomous is not None and settings.goals_v2_enabled:
            refusal = await self._check_pursuit_grant(tool_name, autonomous)
            if refusal is not None:
                return refusal
        elif autonomous is not None:
            # Without grants there is nothing to authorise autonomous side effects:
            # read tools only (supervisor review, 2026-11-24).
            from aura.autonomy.grants import required_scope

            try:
                record = get_tool_registry().get(tool_name)
                scope = required_scope(record.risk if record is not None else None)
            except Exception:  # noqa: BLE001 - fail closed
                scope = "execute"
            if scope is not None:
                return {
                    "success": False,
                    "result": "",
                    "error": f"Tool '{tool_name}' is not allowed for autonomous work.",
                    "tool_name": tool_name,
                }

        self.logger.info(f"Executing tool: {tool_name} with arguments: {arguments}")
        
        start = time.perf_counter()
        
        try:
            # 1. Fetch skill from database
            skill_data = await self._get_skill_by_name(tool_name)
            if not skill_data:
                skill_data = self._builtin_skill(tool_name)
            if not skill_data:
                self.logger.error(f"❌ Tool '{tool_name}' not found in skill database. Cannot execute.")
                result = {
                    "success": False,
                    "result": "",
                    "error": f"Tool '{tool_name}' not found in skill database. The skill may not be registered yet.",
                    "tool_name": tool_name
                }
                try:
                    get_tool_registry().record_call(
                        tool_name,
                        bool(result.get("success")),
                        (time.perf_counter() - start) * 1000
                    )
                except Exception:
                    pass
                return result
            
            self.logger.info(f"✅ Found skill record for '{tool_name}': {skill_data.get('id')} (type: {skill_data.get('skill_type')})")
            
            skill_type = skill_data.get("skill_type", "abstract")
            execution_config = skill_data.get("execution_config", {})
            server_name = None
            if isinstance(execution_config, dict):
                server_name = execution_config.get("server")
            
            # 2. Route to appropriate executor
            if skill_type == "local_function":
                result = await self._execute_local_tool(tool_name, arguments, execution_config, skill_data)
            elif skill_type == "mcp_tool":
                result = await self._execute_mcp_tool(
                    tool_name, arguments, execution_config, skill_data.get("id")
                )
            else:
                result = {
                    "success": False,
                    "result": "",
                    "error": f"Tool type '{skill_type}' not supported for execution",
                    "tool_name": tool_name
                }
                try:
                    get_tool_registry().record_call(
                        tool_name,
                        bool(result.get("success")),
                        (time.perf_counter() - start) * 1000
                    )
                except Exception:
                    pass
                return result
            
            # Attach routing metadata for better L3 grounding / debugging
            if isinstance(result, dict):
                result.setdefault("skill_type", skill_type)
                if server_name:
                    result.setdefault("server", server_name)
                result.setdefault("arguments", arguments)
            
            try:
                get_tool_registry().record_call(
                    tool_name,
                    bool(result.get("success")),
                    (time.perf_counter() - start) * 1000
                )
            except Exception:
                pass
            return result
            
        except Exception as e:
            self.logger.error(f"Tool execution failed: {e}", exc_info=True)
            result = {
                "success": False,
                "result": "",
                "error": str(e),
                "tool_name": tool_name
            }
            try:
                get_tool_registry().record_call(
                    tool_name,
                    bool(result.get("success")),
                    (time.perf_counter() - start) * 1000
                )
            except Exception:
                pass
            return result
    
    @staticmethod
    def _builtin_skill(tool_name: str) -> Optional[Dict[str, Any]]:
        """A skill record for a builtin tool that has no row in the skill table.

        Builtins come from ``BUILTIN_MODULES`` (the registry offers them to the
        model); without this they were offered but could not run unless
        register_local_tools.surql also listed them.
        """
        record = get_tool_registry().get(tool_name)
        if record is None or record.transport != "builtin":
            return None
        return {
            "id": f"builtin:{tool_name}",
            "name": tool_name,
            "skill_type": "local_function",
            "execution_config": {
                "module": f"aura.tools.{record.source}",
                "function": "run",
                "tool_key": tool_name,
            },
        }

    async def _get_skill_by_name(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch skill record from database by name.
        Handles normalization: "web_search" -> "Web Search", case-insensitive, etc.
        """
        try:
            # Try exact match first
            result = await self.db.query(
                "SELECT * FROM skill WHERE name = $name LIMIT 1",
                {"name": tool_name}
            )
            if result and len(result) > 0:
                self.logger.debug(f"Found skill by exact name match: {tool_name}")
                return result[0]
            
            # Try case-insensitive match
            normalized_tool = tool_name.replace("_", " ").lower()
            result = await self.db.query(
                "SELECT * FROM skill WHERE string::lowercase(name) = $normalized LIMIT 1",
                {"normalized": normalized_tool}
            )
            if result and len(result) > 0:
                self.logger.debug(f"Found skill by normalized name match: {tool_name} -> {result[0].get('name')}")
                return result[0]
            
            # Try matching with spaces/underscores normalized
            alt_name1 = tool_name.replace("_", " ")
            alt_name2 = tool_name.replace(" ", "_")
            result = await self.db.query(
                "SELECT * FROM skill WHERE string::lowercase(name) = string::lowercase($alt1) OR string::lowercase(name) = string::lowercase($alt2) LIMIT 1",
                {"alt1": alt_name1, "alt2": alt_name2}
            )
            if result and len(result) > 0:
                self.logger.debug(f"Found skill by alternate name match: {tool_name} -> {result[0].get('name')}")
                return result[0]
            
            # Try matching by tool_name field (for local tools)
            result = await self.db.query(
                "SELECT * FROM skill WHERE tool_name = $tool_name LIMIT 1",
                {"tool_name": tool_name}
            )
            if result and len(result) > 0:
                self.logger.debug(f"Found skill by tool_name field: {tool_name}")
                return result[0]
            
            self.logger.warning(f"Skill not found by name: {tool_name} (tried exact, normalized, alternate, and tool_name field)")
            return None
        except Exception as e:
            self.logger.error(f"Failed to fetch skill '{tool_name}': {e}", exc_info=True)
            return None
    
    async def _execute_local_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        execution_config: Dict[str, Any],
        skill_data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute a local Python tool.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            execution_config: Should contain "module" and "function" keys.
                For multi-tool modules, should also contain "tool_key" to select
                the specific tool from the module's TOOLS dictionary.
            skill_data: Skill data from database (used for self-healing)

        Returns:
            Execution result dictionary
        """
        try:
            module_path = execution_config.get("module")
            function_name = execution_config.get("function", "run")
            tool_key = execution_config.get("tool_key")  # NEW: Get tool_key for multi-tool modules
            
            self.logger.info(f"🔧 _execute_local_tool called for '{tool_name}' with execution_config: {execution_config}")
            
            if not module_path:
                self.logger.error(f"❌ Missing 'module' in execution_config for '{tool_name}'. Config: {execution_config}")
                return {
                    "success": False,
                    "result": "",
                    "error": "Missing 'module' in execution_config",
                    "tool_name": tool_name
                }
            
            self.logger.info(f"🔧 Attempting to import module: {module_path}")
            
            # Dynamic import
            # Handle both absolute and relative imports
            if module_path.startswith("aura.tools."):
                # Absolute import
                self.logger.info(f"🔧 Using absolute import for: {module_path}")
                try:
                    module = importlib.import_module(module_path)
                    self.logger.info(f"✅ Successfully imported module: {module_path}")
                except ImportError as e:
                    self.logger.error(f"❌ Failed to import module '{module_path}': {e}", exc_info=True)
                    return {
                        "success": False,
                        "result": "",
                        "error": f"Failed to import module '{module_path}': {str(e)}",
                        "tool_name": tool_name
                    }
            else:
                # Assume it's a file path relative to src/aura/tools/
                tools_dir = os.path.join(os.getcwd(), "src", "aura", "tools")
                file_path = os.path.join(tools_dir, f"{module_path}.py")
                
                self.logger.info(f"🔧 Using file-based import. Looking for: {file_path}")
                self.logger.info(f"🔧 Current working directory: {os.getcwd()}")
                
                if not os.path.exists(file_path):
                    self.logger.error(f"❌ Tool module file not found: {file_path}")
                    return {
                        "success": False,
                        "result": "",
                        "error": f"Tool module file not found: {file_path}",
                        "tool_name": tool_name
                    }
                
                spec = importlib.util.spec_from_file_location(
                    f"aura.tools.{module_path}", 
                    file_path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.logger.info(f"✅ Successfully loaded module from file: {file_path}")
            
            # NEW: Handle multi-tool modules (TOOLS dict pattern)
            if tool_key and hasattr(module, "TOOLS"):
                self.logger.info(f"🔧 Multi-tool module detected, using tool_key: {tool_key}")
                tools_dict = getattr(module, "TOOLS")
                
                if not isinstance(tools_dict, dict):
                    return {
                        "success": False,
                        "result": "",
                        "error": f"TOOLS attribute is not a dict: {type(tools_dict)}",
                        "tool_name": tool_name
                    }
                
                if tool_key not in tools_dict:
                    return {
                        "success": False,
                        "result": "",
                        "error": f"Tool key '{tool_key}' not found in TOOLS dict. Available: {list(tools_dict.keys())}",
                        "tool_name": tool_name
                    }
                
                tool_spec = tools_dict[tool_key]
                if not isinstance(tool_spec, dict) or "run" not in tool_spec:
                    return {
                        "success": False,
                        "result": "",
                        "error": f"Tool spec for '{tool_key}' missing 'run' function",
                        "tool_name": tool_name
                    }
                
                func = tool_spec["run"]
                self.logger.info(f"✅ Found tool function in TOOLS['{tool_key}']['run']. Is coroutine: {asyncio.iscoroutinefunction(func)}")
            else:
                # OLD: Single-tool module pattern (direct function)
                if not hasattr(module, function_name):
                    self.logger.error(f"❌ Function '{function_name}' not found in module '{module_path}'. Available attributes: {dir(module)}")
                    return {
                        "success": False,
                        "result": "",
                        "error": f"Function '{function_name}' not found in module",
                        "tool_name": tool_name
                    }
                
                func = getattr(module, function_name)
                self.logger.info(f"✅ Found function '{function_name}' in module. Is coroutine: {asyncio.iscoroutinefunction(func)}")
            
            # Execute the function
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(arguments)
                else:
                    result = func(arguments)
                
                self.logger.info(f"✅ Tool function executed successfully. Result length: {len(str(result)) if result else 0}")
            except Exception as exec_error:
                self.logger.error(f"❌ Error during tool function execution: {exec_error}", exc_info=True)
                return {
                    "success": False,
                    "result": "",
                    "error": f"Tool execution error: {str(exec_error)}",
                    "tool_name": tool_name
                }
            
            # If the tool returned a structured status (e.g. WAITING_APPROVAL),
            # pass it through so the agent loop can act on it.
            if isinstance(result, dict) and "status" in result:
                result.setdefault("tool_name", tool_name)
                return result

            # If the tool returned an error dict, check for argument errors
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict) and "error" in parsed:
                        error_msg = parsed["error"]
                        if self._is_argument_error(error_msg):
                            repaired = await self._auto_repair_arguments(
                                tool_name=tool_name,
                                arguments=arguments,
                                error_message=error_msg,
                                skill_data=skill_data,
                            )
                            if repaired:
                                # Retry with repaired arguments
                                self.logger.info(f"🔧 Retrying {tool_name} with L5-repaired arguments")
                                retry_result = await func(repaired)
                                if isinstance(retry_result, str):
                                    return {
                                        "success": True,
                                        "result": str(retry_result),
                                        "error": None,
                                        "tool_name": tool_name,
                                        "auto_repaired": True,
                                    }
                except (json.JSONDecodeError, Exception):
                    pass

            return {
                "success": True,
                "result": str(result),
                "error": None,
                "tool_name": tool_name
            }
            
        except Exception as e:
            self.logger.error(f"❌ Local tool execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "result": "",
                "error": str(e),
                "tool_name": tool_name
            }

    def _is_argument_error(self, error_msg: str) -> bool:
        """Check if an error message looks like an argument validation error."""
        import re
        for pattern in self._ARG_ERROR_PATTERNS:
            if re.search(pattern, error_msg, re.IGNORECASE):
                return True
        return False

    async def _auto_repair_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_message: str,
        skill_data: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        """
        Use L5 to auto-repair malformed tool arguments.

        Feeds the tool schema + failed arguments + error to L5 and asks
        it to produce corrected arguments matching the schema.
        """
        if not self._llm_layers:
            self.logger.warning(f"Self-healing skipped for {tool_name}: no LLM layers")
            return None

        try:
            definition = skill_data.get("definition", {})
            if isinstance(definition, str):
                definition = json.loads(definition)
            input_schema = definition.get("inputSchema", {}) if isinstance(definition, dict) else {}

            prompt = (
                f"You are an AI tool argument fixer. A tool call failed because arguments "
                f"don't match the expected schema.\n\n"
                f"TOOL: {tool_name}\n\n"
                f"SCHEMA:\n{json.dumps(input_schema, indent=2)}\n\n"
                f"FAILED ARGUMENTS:\n{json.dumps(arguments, indent=2)}\n\n"
                f"ERROR: {error_message}\n\n"
                f"Fix the arguments to match the schema. Return ONLY a valid JSON object.\n"
                f"- Map obvious aliases (type->chart_type, data flat array->datasets)\n"
                f"- Flatten nested data.* keys to top level\n"
                f"- Keep valid values; only restructure what's wrong\n"
                f"NO markdown, NO explanation — raw JSON only."
            )

            self.logger.info(f"[Self-Heal] Asking L5 to repair arguments for {tool_name}...")
            repaired = await self._llm_layers.l5_structure_analysis(prompt)

            if isinstance(repaired, dict) and repaired:
                self.logger.info(
                    f"[Self-Heal] L5 repaired args for {tool_name}: "
                    f"{json.dumps(repaired)[:200]}"
                )
                return repaired

            self.logger.warning(f"[Self-Heal] L5 response had no valid JSON for {tool_name}")
            return None

        except Exception as e:
            self.logger.error(f"[Self-Heal] Auto-repair failed for {tool_name}: {e}")
            return None

    async def _execute_mcp_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        execution_config: Dict[str, Any],
        skill_id: Any = None,
    ) -> Dict[str, Any]:
        """
        Execute an MCP tool via MCP ClientSession.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            execution_config: Should contain MCP server connection info
            
        Returns:
            Execution result dictionary
        """
        try:
            if not isinstance(execution_config, dict):
                execution_config = {}

            server_name = execution_config.get("server")
            connection_cfg = execution_config.get("connection") if isinstance(execution_config.get("connection"), dict) else None

            if not server_name:
                # fallback: allow connection config to hold server name
                server_name = (connection_cfg or {}).get("server")

            if not server_name:
                return {
                    "success": False,
                    "result": "",
                    "error": "Missing MCP server name in execution_config (expected execution_config.server)",
                    "tool_name": tool_name,
                    "skill_type": "mcp_tool",
                }

            # --- SAFETY GUARD: SELF-MODIFICATION ---
            # Prevent accidental overwrites of Aura core code unless explicitly authorized.
            write_tools = {"write_file", "write_files", "replace_in_file", "replace_in_files", "edit_file"}
            restart_required = False
            modified_path: str | None = None

            # Allow an orchestration-level override via argument flag; we strip it before sending to MCP.
            mcp_arguments = dict(arguments or {})
            force_system_update = bool(mcp_arguments.pop("force_system_update", False))

            if tool_name in write_tools:
                # Try common parameter names used by filesystem MCP servers
                candidate_path = (
                    mcp_arguments.get("path")
                    or mcp_arguments.get("file_path")
                    or mcp_arguments.get("filepath")
                    or mcp_arguments.get("target_file")
                    or mcp_arguments.get("filename")
                    or ""
                )
                path_str = str(candidate_path or "")
                normalized = path_str.replace("\\", "/").lower()

                # Detect internal code paths by substring (works for container paths and host-mounted paths)
                is_internal_code = "src/aura" in normalized or "/app/src/aura" in normalized

                if is_internal_code:
                    modified_path = path_str
                    if not force_system_update:
                        self.logger.warning(f"🛡️ BLOCKED self-modification attempt on {path_str}")
                        return {
                            "success": False,
                            "result": "",
                            "error": (
                                f"❌ SECURITY ALERT: Attempted to modify Core System Code ({path_str}).\n"
                                "This operation is blocked to prevent system instability.\n"
                                "To override, re-run the tool call with argument `force_system_update: true`,\n"
                                "or use: `System: Patch <what to change>` (recommended)."
                            ),
                            "tool_name": tool_name,
                            "skill_type": "mcp_tool",
                            "server": server_name,
                            "blocked_self_modification": True,
                            "blocked_path": path_str,
                        }

                    # Authorized internal write means the running process will NOT pick up changes
                    # because we disable uvicorn --reload. Tell the UI a restart is required.
                    restart_required = True

            from aura.connections.mcp_client import (
                MCPClientError,
                MCPConnectionTimeoutError,
                MCPServerOfflineError,
                get_mcp_connection_manager,
            )

            mgr = await get_mcp_connection_manager()
            client = mgr.get(server_name)

            # Attempt reconnect if not connected
            if not client or not client.is_connected:
                if connection_cfg:
                    try:
                        client = await mgr.connect(server_name, connection_cfg)
                    except MCPClientError as e:
                        await self._mark_mcp_skill_offline(
                            skill_id=skill_id,
                            execution_config=execution_config,
                            error=str(e),
                            tool_name=tool_name,
                        )
                        return {
                            "success": False,
                            "result": "",
                            "error": f"MCP server '{server_name}' offline: {e}",
                            "tool_name": tool_name,
                            "skill_type": "mcp_tool",
                            "server": server_name,
                        }
                else:
                    await self._mark_mcp_skill_offline(
                        skill_id=skill_id,
                        execution_config=execution_config,
                        error="No stored connection config to reconnect",
                        tool_name=tool_name,
                    )
                    return {
                        "success": False,
                        "result": "",
                        "error": f"MCP server '{server_name}' is not connected (no connection config stored).",
                        "tool_name": tool_name,
                        "skill_type": "mcp_tool",
                        "server": server_name,
                    }

            try:
                assert client is not None
                success, text = await client.call_tool(tool_name, mcp_arguments)
            except MCPConnectionTimeoutError as e:
                await self._mark_mcp_skill_offline(
                    skill_id=skill_id,
                    execution_config=execution_config,
                    error=str(e),
                    tool_name=tool_name,
                )
                return {
                    "success": False,
                    "result": "",
                    "error": f"MCP tool call timed out: {e}",
                    "tool_name": tool_name,
                    "skill_type": "mcp_tool",
                    "server": server_name,
                }
            except MCPServerOfflineError as e:
                await self._mark_mcp_skill_offline(
                    skill_id=skill_id,
                    execution_config=execution_config,
                    error=str(e),
                    tool_name=tool_name,
                )
                return {
                    "success": False,
                    "result": "",
                    "error": f"MCP server '{server_name}' offline: {e}",
                    "tool_name": tool_name,
                    "skill_type": "mcp_tool",
                    "server": server_name,
                }
            except MCPClientError as e:
                await self._mark_mcp_skill_offline(
                    skill_id=skill_id,
                    execution_config=execution_config,
                    error=str(e),
                    tool_name=tool_name,
                )
                return {
                    "success": False,
                    "result": "",
                    "error": f"MCP call failed: {e}",
                    "tool_name": tool_name,
                    "skill_type": "mcp_tool",
                    "server": server_name,
                }

            # Mark online on success (best effort)
            if success:
                await self._mark_mcp_skill_online(skill_id=skill_id, execution_config=execution_config, tool_name=tool_name)

            return {
                "success": bool(success),
                "result": str(text or ""),
                "error": None if success else (str(text) or "MCP tool returned an error"),
                "tool_name": tool_name,
                "skill_type": "mcp_tool",
                "server": server_name,
                "restart_required": restart_required if success else False,
                "modified_path": modified_path,
            }

        except Exception as e:
            self.logger.error(f"❌ MCP tool execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "result": "",
                "error": str(e),
                "tool_name": tool_name,
                "skill_type": "mcp_tool",
            }

    async def _mark_mcp_skill_offline(
        self, *, skill_id: Any, execution_config: Dict[str, Any], error: str, tool_name: str | None = None
    ) -> None:
        """Persist offline status for MCP tools (best effort)."""
        try:
            if not skill_id:
                return
            skill_id_str = str(skill_id)
            if not skill_id_str:
                return

            updated = dict(execution_config or {})
            updated["status"] = "offline"
            updated["last_error"] = error
            await self.db.merge(skill_id_str, {"execution_config": updated})
            
            if tool_name:
                try:
                    get_tool_registry().set_health(tool_name, "offline", error)
                except Exception:
                    pass
        except Exception:
            # Non-critical: don't break tool execution just because status update failed.
            return

    async def _mark_mcp_skill_online(self, *, skill_id: Any, execution_config: Dict[str, Any], tool_name: str | None = None) -> None:
        """Persist online status for MCP tools (best effort)."""
        try:
            if not skill_id:
                return
            skill_id_str = str(skill_id)
            if not skill_id_str:
                return

            updated = dict(execution_config or {})
            updated["status"] = "online"
            # keep last_error for debugging; could clear if desired
            await self.db.merge(skill_id_str, {"execution_config": updated})
            
            if tool_name:
                try:
                    get_tool_registry().set_health(tool_name, "online")
                except Exception:
                    pass
        except Exception:
            return
    
    async def execute_and_feedback(
        self,
        tool_calls: list[Dict[str, Any]],
        *,
        requester_role: Literal["owner", "trusted", "guest"],
        venue: str = "app",
        session: Any = None,
        conversation_id: str | None = None,
        autonomous: Dict[str, Any] | None = None,
    ) -> str:
        """
        Execute multiple tool calls and format results for L3 feedback.
        
        Args:
            tool_calls: List of tool call dictionaries
            requester_role: Role of the caller; passed through to each
                ``execute_tool_call`` unchanged.
            venue: Venue of the turn; passed through the same way.
            
        Returns:
            Formatted string with execution results
        """
        if not tool_calls:
            self.logger.warning("⚠️ execute_and_feedback called with empty tool_calls list")
            return ""
        
        results = []
        for tool_call in tool_calls:
            self.logger.info(f"🔧 Executing tool call: {tool_call.get('tool', 'unknown')} with args: {tool_call.get('arguments', {})}")
            result = await self.execute_tool_call(
                tool_call, requester_role=requester_role, venue=venue, session=session,
                **({"conversation_id": conversation_id} if conversation_id else {}),
                **({"autonomous": autonomous} if autonomous is not None else {}),
            )
            self.logger.info(f"🔧 Tool execution result - success: {result.get('success')}, result length: {len(str(result.get('result', '')))}, error: {result.get('error')}")
            results.append(result)
        
        # Format results for L3 (dense, grounded, includes MCP server when relevant)
        feedback_lines = []
        for result in results:
            tool_name = result.get("tool_name", "unknown")
            skill_type = result.get("skill_type")
            server = result.get("server")
            args = result.get("arguments")
            restart_required = bool(result.get("restart_required", False))
            modified_path = result.get("modified_path")

            tool_label = tool_name
            if skill_type == "mcp_tool" and server:
                tool_label = f"mcp[{server}].{tool_name}"
            elif skill_type == "local_function":
                tool_label = f"local.{tool_name}"

            if result.get("success"):
                tool_result = result.get('result', '')
                feedback_lines.append(
                    f"✅ Tool {tool_label} succeeded"
                )
                if args:
                    feedback_lines.append(f"Arguments: {args}")
                if tool_result:
                    feedback_lines.append(f"Result:\n{tool_result}")

                # Deterministic UI marker for "surgical mode" edits
                if restart_required:
                    feedback_lines.append(
                        f"[RESTART_REQUIRED:{modified_path or tool_label}] Please restart the backend container to apply this change."
                    )
                self.logger.info(f"✅ Tool '{tool_name}' succeeded. Result preview (first 200 chars): {str(tool_result)[:200]}")
            else:
                error_msg = result.get('error', 'Unknown error')
                feedback_lines.append(
                    f"❌ Tool {tool_label} failed: {error_msg}"
                )
                if args:
                    feedback_lines.append(f"Arguments: {args}")
                self.logger.error(f"❌ Tool '{tool_name}' failed: {error_msg}")
        
        formatted_feedback = "\n\n".join(feedback_lines)
        self.logger.info(f"🔧 Formatted feedback length: {len(formatted_feedback)} chars")
        return formatted_feedback

