# G4-04 parity: agent loop features after OpenCode delegation

Source: agency PRD 4.1. Existing tests are named `file::test`; tests in `tests/unit/test_g4_parity.py` are new. Date: 2026-11-23.

## Agent loop parity (T16)

| Row | Covered by | Note |
|---|---|---|
| Multi-step autonomous execution | tests/unit/test_delegation.py::TestStartDelegation::test_returns_task_id, tests/unit/test_delegation.py::TestDelegationRunner::test_steps_are_persisted | Fake OpenCode client. A real multi-step run is the manual acceptance in FOR_MAI section 3. |
| Live step log streamed to the UI | tests/unit/test_delegation.py::TestDelegationRunner::test_steps_are_persisted, tests/unit/test_delegation_controls.py::test_list_and_detail | UI rendering: frontend `Workbench.test.tsx`. |
| Abort, pause all, abort all | tests/unit/test_delegation_controls.py::test_abort_calls_client_and_fails_task, ::test_pause_all_refuses_delegate_work_but_runner_continues, ::test_abort_all_reaches_every_runner | OpenCode has no session pause, so pause-all only blocks new delegations. |
| Approval for risky actions | tests/unit/test_delegation.py::TestDelegationRunner::test_permission_asked_creates_pending_decision_and_waits, tests/unit/test_decisions.py::TestDecisionService::test_answer_allow | Policy table: tests/unit/test_policy.py; read allowed and write-outside-workspace denied: tests/unit/test_delegation.py::TestDelegationRunner::test_read_request_allowed_at_once, ::test_write_outside_workspace_denied_at_once. |
| Guidance injected mid-task | tests/unit/test_delegation_controls.py::test_guidance_reaches_send_and_is_recorded | |
| Blocker detection | tests/unit/test_delegation_monitor.py::test_error_streak_fires_once_with_one_decision, ::test_repeat_loop_normalises_args_and_fires_once, ::test_token_budget_80_percent_fires_once_before_the_stop, ::test_time_budget_80_percent_fires_once_before_the_stop | |
| Suggested next action on a blocker | tests/unit/test_delegation_monitor.py::test_suggestion_is_stored_on_the_blocker | |
| Heartbeat during long tasks | tests/unit/test_delegation_monitor.py::test_heartbeat_on_a_silent_session | |
| Emotional snapshot per step | tests/unit/test_delegation_monitor.py::test_step_carries_top_three_emotions, ::test_emit_appraisal_reaches_engine_only_with_flag | |
| Step persistence and resume after restart | tests/unit/test_delegation_monitor.py::test_recovery_reattaches_running_and_pauses_the_rest, ::test_reattach_with_running_session_starts_a_monitor | |
| File version snapshots | tests/unit/test_delegation_controls.py::test_diff_comes_from_client | Diffs come from OpenCode; the old file-version store is removed in G4-05. |
| Per-session tool allowlist, memory namespace, identity overlay | tests/unit/test_g4_parity.py::test_session_context_carries_allowlist_namespace_and_overlay, tests/unit/test_session_scope_tools.py::test_forced_call_outside_the_allowlist_is_refused, ::test_denylisted_call_is_refused, ::test_main_session_changes_nothing, ::test_guest_is_refused_by_role_before_the_session_check, ::test_lean_tier_is_refused_by_tier_before_the_session_check, ::test_model_supplied_session_is_ignored, ::test_sub_session_excludes_disallowed_tools_and_keeps_the_tier_exclude, ::test_session_reaches_the_tool_loop_and_the_forced_seed, ::test_tool_loop_passes_the_session_only_when_set, ::test_delegate_work_refused_outside_the_allowlist, ::test_brief_contains_the_overlay_section, ::test_resolve_session_sets_scope_for_a_sub_session, ::test_resolve_session_is_none_for_main | **Covered (G4-04a): allowlist and overlay.** The chat path excludes disallowed tools from `select_tools` and refuses them in `execute_tool_call` (order: role, tier, session). `delegate_work` is refused outside the allowlist and its brief carries the overlay. **Namespace: not covered.** Memory v2 has no namespaces (episode/fact have no namespace field; fact recall applies no namespace filter); tracked as a follow-up, not a G4 blocker. The chat path still applies the namespace to the v1 `memory` table through `_resolve_session`. |
| Autonomous goal pursuit | manual: create a goal with autonomous pursuit and check the loop runs | **Gap.** `GoalEngine.pursue_goal_autonomously` stores `tool_permissions` with the comment "will be used when tools are implemented"; it does not call built-in tools or `delegate_work`. Not built in this card. |

## Built-in tools that stay (T17)

Every tool: registered with transport `builtin`, schema unchanged by `sanitize_schema` (the registry's own filter), no `force_execute`, no `_`-prefixed property (`test_kept_tool_registered_with_no_approval_argument`, one case per tool). Real calls go through `ToolExecutor.execute_tool_call` as owner. The filesystem tools only reach `ALLOWED_PATHS` (the repo), so the tests point that at `tmp_path`.

| Tool | Covered by | Note |
|---|---|---|
| read_file, list_directory, directory_tree, search_files, get_file_info | test_g4_parity.py::test_filesystem_tools_round_trip | |
| write_file, edit_file, create_directory, delete_file | test_g4_parity.py::test_filesystem_tools_round_trip | Write approval for core paths: test_tool_approval_runtime.py::test_filesystem_core_write_gate_reads_runtime_approved. Outside the root: ::test_filesystem_refuses_a_path_outside_the_allowed_root. |
| terminal | test_g4_parity.py::test_terminal_safe_command_runs_and_unsafe_waits | Safe command (`echo`) runs. An unsafe command with a forged `force_execute` returns WAITING_APPROVAL and does not run. The built-in tool holds the call itself (no Decision record is created by it). |
| execute_code | test_g4_parity.py::test_execute_code_runs_python | `print(1)` in `tmp_path` with `code_execution_enabled` set. The tool has no approval gate of its own, only the setting. |
| generate_chart | test_g4_parity.py::test_generate_chart_is_local_and_returns_a_config | Pure local. |
| web_search | registration and schema only (`test_kept_tool_registered_...`, `test_web_search_schema_has_a_query`) | Not called: it uses the network. |
| Non-owner | test_g4_parity.py::test_non_owner_cannot_call_a_built_in_tool | |

All 13 kept tools are in the registry. None is missing.
