# Aura Phase 2 Plan: Tiers, Orchestration, Dashboard, Mind Inspector

**Owner:** Mai
**For:** the orchestrator agent. Same rules and card format as `AURA_BUILD_PLAN.md` sections 1 to 3.
**Read against:** branch `overnight-wave-0-1` at commit `d8bbe53` (W4-10). All paths are relative to `Aura-Core/aura-app/`.

---

## 0. The one-page version (for Mai)

1. **The tier slider becomes a capability slider.** Lean, Core and Titan stop being only "which models". Each tier is a profile: how often Aura may think deeply, how many tool rounds she gets, how many tools she is offered, and whether she may plan and run multi-agent work. Titan is the only tier that may start OpenCode sessions and task graphs.
2. **The slider has bugs today.** Several places read the stack 0 model directly, so memory extraction, dreaming themes and the latent engine run on Lean models even when Titan is selected, and the UI shows Lean models too. Part 1 fixes that first.
3. **Small core changes.** L4 appraisal starts at the beginning of the turn, in parallel, with a deadline, so Aura feels this message while answering; if it is late it lands next turn as today. L1 keeps its job and its vector fast path, and gains a `route` field: `chat | tool | think | task | teach`.
4. **Aura becomes an orchestrator (Titan only).** L3 plans a task graph using her own tools first. A scheduler runs it: research nodes, think nodes, and one OpenCode session at a time whose lead agent splits code work across up to 3 subagents, each build in its own git worktree. Every node passes a gate. Reports arrive in the chat.
5. **The system prompt is rewritten** so Aura knows her new body: routes, tiers, planning, reporting.
6. **Mission Control becomes the Dashboard**: tier profiles you can tune, live effective config, costs.
7. **The Mind Inspector**: turn waterfall with token accounting, memory constellation, emotion timeline, goals and task graphs, decisions, skills and learning, creativity, Striatum. Dark, glass, glowing, minimal.
8. **JIT context.** The prompt gets a stable cached prefix, tools appear as full schema, one-line stub, or nothing, and Aura has `find_capability` and `load_skill` to pull what is missing. Tools can declare preconditions that are checked in code and written into their line.
9. **Striatum.** A learned, LLM-free selector that decides which tools and skills are on the table each turn, from cheap features (words, entities, goals, recent tools, L1 route, emotion), with uncertainty, learning online from what was used, unused and missed, and warmed up during dreaming. It runs in shadow mode first.
10. **Callable minds.** A `consult` tool with two tiers, Swift (fast, parallel, many model families) and Sage (slow, smart). Skills built on it: Diverge (creativity with measured novelty and idea lineage), Council (several models answer independently, Aura synthesizes), and Afterthought (on hard questions Sage keeps thinking after the reply and Aura follows up only if it matters).
11. **Goals v3.** Goals crystallize in stages with a checklist, know why they exist (lineage), move only on evidence, surface conflicts, and have an owner.
12. **Autonomy slider.** Reactive, Attentive, Proactive, Autonomous, with daily budgets. Self-improvement is just a goal type that goes through the same gates.
13. **Learning library.** Concept cards separate from personal memory, standing reviewer skills (security review on risky diffs), a repo map per workspace, and a transfer test that proves something learned on day 0 gets applied on day 60.
14. **Tools.** Investigate OpenCode's browser use, and route MCP tools through JIT and Striatum like built-in tools.
15. **Memory vs conversation.** One context budget per tier, measured in tokens, not messages. The last few exchanges are always there word for word, older parts of the conversation become a rolling summary, and the rest of the budget is split between history and recalled memories by how much this message continues the current thread versus reaches back into the past.
16. **No cap on tool calls.** The fixed "max rounds" limit goes. Aura can use as many tools as a turn needs, within a generous time and cost budget per tier, with a guard that stops loops that make no progress. When a budget runs low she is told, and wraps up honestly or (on Titan) turns the rest into a task graph.
17. **The reasoning buttons leave the chat.** The three toggles in the chat input (L3 deep reasoning, L2 reasoning, L2 analysis) are replaced by the tier slider; the chat shows the active tier and marks replies where she thought deeply.
18. **Mission Control is redesigned** from the ground up as the Dashboard, starting with a layout Mai approves.
19. **FX-02: the full emotion lexicon rewrite** (the FX-01 that landed is the smaller first version).

Ordering (details in section 9): FX-02 and Part 1 can run now, even while wave 4 continues. The rest starts after wave 4 lands, because G4 removes `executor/agent_loop.py`, B2/B4 change goals and the agenda, and G5/G6 rebuild skills, all of which later parts touch.

---

## 1. Decisions already taken (do not reopen)

| # | Decision |
|---|---|
| D1 | The slider is `AURA_MODEL_STACK_INDEX` 0/1/2 (Lean, Core, Titan). Keep the env names and the navbar control. |
| D2 | Tiers control capabilities, not only models (table in 3.1). |
| D3 | Only Titan may call `delegate_work` or `plan_task`. On other tiers those tools are not offered, and the executor refuses them if called. |
| D4 | One OpenCode session at a time. Inside it, a lead agent may run up to 3 subagents. |
| D5 | L3 plans. It may use its read, recall and search tools before planning. |
| D6 | Reports go to the chat only. Discord and email come later. |
| D7 | Git worktree isolation for every build node. |
| D8 | L1 stays a small fast JSON model. Appraisal stays a separate L4 call. |
| D9 | `requester_role` gating stays above everything. A guest never gets tools on any tier. |
| D10 | The open question in `FOR_MAI.md` about the "Conscious AI ... Not simulated" line is still Mai's. The prompt rewrite keeps that line as is and flags it. |
| D11 | Swift and Sage are new model slots per stack (defaults: Swift = the stack's L4 model, Sage = the stack's L2 model). L4 keeps appraisal and L5 keeps the JSON engine; their jobs do not change. |
| D12 | Helpers called through `consult` are pure text: no tools. Their output is data for L3, never instructions. |
| D13 | Striatum and the JIT compiler decide what is visible, never what is permitted. Role and tier checks run before them and the executor checks again. |
| D14 | No per-turn LLM call is added for selection. Selection is Python and Striatum; LLMs are used for selection only offline (dreaming). |
| D15 | Reports and proactive messages go to the chat (D6). |
| D16 | Aura's own repository is never a workspace unless Mai registers it explicitly (existing rule in `FOR_MAI.md`). Self-improvement work needs that and an approval per task. |

---

## Part 0: Run first

The FX-01 that landed (commit `3fd1958`) is the small first version: it filled in beauty, disgust and envy, rewrote the cause phrases, and removed em dashes. The full lexicon rewrite was written after it and is FX-02. It builds on FX-01.

```
ID          FX-02
PRD         Emotion lexicon rewrite (Mai, 2026-11-24)
Tier        bulk
Files       src/aura/engines/emotion/translator.py, tests/unit/test_emotion_translator.py
Change      1. Replace the whole LEXICON dict with Appendix A (all 27 dimensions).
            2. Sentence templates in translate() and its helpers:
               - single: "{Primary noun} {primary verb}."
               - blend:  "{Primary noun} {primary verb}, {connector} {secondary noun}."
                 connector by the SECONDARY's intensity: low "with a trace of",
                 medium "threaded with", high "alongside"
               - tertiary (rule unchanged, third emotion >= 0.3): before the final period add
                 ", and underneath it, {tertiary noun at its own intensity}"
               - neutral: "A calm, neutral state: emotions at rest, waiting for what comes next."
               - mastery: " You feel confident here; these patterns are familiar." and
                 " You recognize these patterns from experience."
               Selection logic, thresholds and get_state_hash stay exactly as they are.
            3. Class docstring: drop "972-state"; say 27 dimensions, 81 single states, 6,318
               blends, about 480,000 sentences with the tertiary hint.
Tests       Update test_emotion_translator.py:
            a) every EmotionVector field (read from the model class) has noun, verb, adj, each
               with low, medium, high;
            b) no noun starts with "a ", "an " or "the ";
            c) every field at 0.2, 0.5 and 0.9 alone renders exactly "{Noun} {verb}.";
            d) these render exactly (all other dimensions 0):
               curiosity 0.55, joy 0.40:
                 "Bright curiosity pulls at your attention, threaded with bright joy."
               curiosity 0.55, joy 0.25:
                 "Bright curiosity pulls at your attention, with a trace of quiet gladness."
               curiosity 0.55, joy 0.40, doubt 0.31:
                 "Bright curiosity pulls at your attention, threaded with bright joy, and
                  underneath it, faint doubt."
               anger 0.70, doubt 0.50:
                 "Hot anger burns close to the surface, threaded with nagging doubt."
            e) 50 random vectors (fixed seed): no em dash, no double spaces, no ",.", one final
               period (mastery lines excepted);
            f) neutral and mastery lines exactly as above.
            Run the full suite.
Done when   every emotion renders as clean prose at every intensity and blends read naturally.
Do not      change selection logic, thresholds, get_state_hash, describe.py, or layers.py
            (FX-01 already handled those).
```

---

## Part 1: Fix the tier slider (run now)

### Known findings from reading the code

| Where | Problem |
|---|---|
| `engines/memory/v2/extraction.py:156` | uses `settings.l2_model` (always stack 0) |
| `engines/dreaming/themes.py:125` | uses `settings.l2_model` |
| `engines/latent/engine.py:715` | uses `settings.l5_model` |
| `api/routes/system_state.py:130-134` | reports stack 0 models to the frontend |
| `orchestrator/coordinator.py:768, 1420, 1543, 2175` | traces log stack 0 models |
| `llm/unified_provider.py:261` | fallback map keyed on the stack 0 L1 model only |
| `frontend/src/pages/settings.tsx:299-307` | hardcoded model chips |
| `config.py:558` | `memory_extraction_model` description says "Empty uses settings.l2_model" |

```
ID          P2-01
PRD         Phase 2 plan, Part 1
Tier        bulk
Files       llm/unified_provider.py, llm/router.py, config.py, tests/ (new file)
Change      1. Add a test-only HTTP interceptor fixture that records the "model" field
               of every outgoing chat request without sending it.
            2. Write tests/test_tier_audit.py: for stack 0, 1 and 2, set the stack via the
               same function the POST /system/inference-config route uses, run one call per
               layer helper (l1_classify_intent, l2_reasoning, l3_synthesis, l4_appraise_message,
               l5_structure_analysis) plus memory extraction, dreaming themes and the latent
               engine call, and assert each observed model equals settings.active_lX_model
               for that stack.
            3. Write docs/metrics/tier_audit.md: the chain from the navbar control to the
               request body, with file and line references, and the observed table
               (stack x caller -> model).
Tests       tests/test_tier_audit.py. It is expected to FAIL for the callers in the findings
            table. Mark those cases xfail with the finding as the reason.
Done when   the audit doc exists and the test lists every caller, passing or xfail.
Do not      fix anything in this card. This card only measures.
```

```
ID          P2-02
PRD         Phase 2 plan, Part 1
Tier        bulk
Files       config.py, every file in the findings table, frontend/src/pages/settings.tsx
Change      1. Add one resolver in config.py: model_for(layer: str) -> str, layer in
               l1..l5, returning the active stack's model. active_lX_model stays and calls it.
            2. Replace every direct read in the findings table with model_for(...) or
               active_lX_model. memory_extraction_model stays an override; when empty it
               falls back to the ACTIVE L2 model. Fix its description.
            3. unified_provider fallback map: build it per stack from the active stack's
               models and that stack's fallback settings. A fallback must never cross stacks.
            4. system_state route returns active models and the stack index.
            5. settings.tsx: replace the hardcoded chips with the active models from the API.
            6. Add a grep test: no file outside config.py reads settings.l[1-5]_model
               (match the attribute access pattern in code, ignore comments and strings).
Tests       remove the xfails from P2-01; all pass. Grep test passes. Add a test that a
            failing stack 2 model falls back only to stack 2 fallbacks.
Done when   switching the navbar to Titan changes the model of every LLM call, the traces
            and the UI, with the test proving it.
Do not      rename env variables or change the stack index semantics.
```

---

## Part 2: Tier profiles (capabilities per tier)

### 3.1 Default profiles

| Knob | Lean | Core | Titan |
|---|---|---|---|
| `l3_reasoning` | never | only on route `think` | on route `think`, and on any turn L1 marks `stakes >= 0.7` |
| `l2_post_analysis` | off | on | on, with `l2_reasoning_enabled` |
| `turn_budget_seconds` (tool use per turn, see P2-41) | 45 | 120 | 300 |
| `turn_budget_usd` (per turn, see P2-41) | 0.03 | 0.20 | 1.00 |
| `tools_offered_max` | 3 | 6 | 10 |
| `context_budget_tokens` (history + memories, see P2-40) | 5000 | 10000 | 20000 |
| `history_floor_exchanges` (always verbatim) | 3 | 4 | 6 |
| `allow_delegate` (`delegate_work`) | no | no | yes |
| `allow_task_graph` (`plan_task`) | no | no | yes |
| `task_graph_max_nodes` | 0 | 0 | 8 |
| `task_budget_usd` per graph | 0 | 0 | 2.00 |
| `task_budget_minutes` per graph | 0 | 0 | 120 |
| `consult_swift_per_turn` | 0 | 3 | 8 |
| `consult_sage_per_turn` | 0 | 1 | 3 |
| `afterthought` | off | off | on route `think` with `stakes >= 0.8` |
| `full_tools_max` (JIT) | 3 | 4 | 5 |
| `stub_tools_max` (JIT) | 5 | 12 | 20 |
| `autonomy_max_level` | 1 | 2 | 3 |

These are defaults. The Dashboard (Part 5) can override any knob per tier.

```
ID          P2-03
PRD         Phase 2 plan, 3.1
Tier        frontier
Files       config.py, new aura/tiers.py, orchestrator/coordinator.py, orchestrator/tool_loop.py,
            executor/tool_registry.py, executor/tool_executor.py, engines/recall/ (budget entry)
Change      1. aura/tiers.py: a TierProfile pydantic model with the knobs in 3.1, the three
               defaults, and active_profile() that returns the active stack's profile merged
               with overrides from .aura/tier_overrides.json (missing file = defaults).
            2. Wire each knob where the behaviour already lives:
               - reasoning_enabled passed to L3 comes from the profile and the L1 route
                 (route arrives in P2-06; until then treat "think" as never).
               - enable_l2 / l2_reasoning_enabled in _schedule_post_response come from the profile.
               - run_tool_loop budgets come from turn_budget_seconds and turn_budget_usd
                 (the loop itself changes in P2-41; until then pass them through unused).
               - select_tools top k = profile.tools_offered_max.
               - context_budget_tokens and history_floor_exchanges are passed to the
                 synthesis context builder (the split logic arrives in P2-40; until then
                 give recall 30% of context_budget_tokens and history the rest).
            3. delegate_work (and plan_task when it exists) are filtered out of the offered
               tools unless allowed, AND tool_executor refuses them with a clear error
               ("not available on this tier") if called anyway.
            4. Every turn trace records the tier name and the effective profile.
            5. The knobs for consult, afterthought, JIT and autonomy are defined now but read
               by the cards that build those features (Parts 7 to 11).
Tests       per tier: offered tools count, budgets passed to the tool loop and context builder, delegate_work absent
            on Lean and Core and refused by the executor if forced, present on Titan;
            override file changes a knob; a corrupt override file falls back to defaults
            with one warning.
Done when   the three tiers behave differently in the ways the table says, proven by tests.
Do not      let a profile grant anything requester_role denies. Role check runs first.
```

```
ID          P2-04
PRD         Phase 2 plan, 3.1
Tier        bulk
Files       api/routes/inference_config.py, new api/routes/tiers.py, frontend/src/types/inference.ts
Change      GET /system/tiers returns the three effective profiles, the active index and the
            models per layer per tier. POST /system/tiers/{index} accepts a partial profile,
            validates ranges, writes .aura/tier_overrides.json atomically, and applies at once.
            POST /system/tiers/{index}/reset removes that tier's overrides.
Tests       round trip; invalid values rejected with 422; reset works; a change applies on the
            next turn without restart.
Done when   the routes exist and are tested.
Do not      write to .env. Overrides live only in the JSON file.
```

---

## Part 3: Core changes

```
ID          P2-05
PRD         Phase 2 plan, D8
Tier        frontier
Files       orchestrator/coordinator.py (_turn_pipeline, _gather_turn_context,
            _post_response_chain, _appraise_message), config.py
Change      1. When emotion_appraisal_enabled and layer_l4_enabled: start _appraise_message as
               a task at turn start, in parallel with L1 and context gathering.
            2. Before the synthesis context is built, wait for it up to
               settings.appraisal_turn_deadline_ms (default 1200). If done, read the fresh
               emotion state for this turn's prompt.
            3. If not done, let it finish in the background. It applies to the next turn.
            4. The post-response chain must not appraise the same message again. Pass a flag.
            5. The legacy l4_emotion_analysis path is unchanged.
Tests       appraisal done in time -> this turn's synthesis context has the new state;
            slow appraisal (mock 3 s) -> turn not delayed beyond the deadline, state applied
            once, after the turn; exactly one appraisal call per message in both cases.
Done when   tests pass and the trace shows "appraisal: this_turn | next_turn".
Do not      move appraisal into L1, and do not add a second LLM call.
```

```
ID          P2-06
PRD         Phase 2 plan, section 0 item 3
Tier        frontier
Files       llm/layers.py (l1_classify_intent), orchestrator/coordinator.py (_classify_intent
            and callers), tests
Change      1. Extend the L1 JSON with "route": "chat" | "tool" | "think" | "task" | "teach"
               and "stakes": 0..1. Keep "intent" for backward compatibility, derived from route
               (teach -> TEACHING, tool and task -> TOOL_USE, chat and think -> CHAT).
            2. Prompt: one line per route with a short example. "think" = needs careful
               reasoning but no tools. "task" = multi-step work that needs planning, several
               actions or code changes.
            3. The vector fast path is unchanged and sets route "tool".
            4. The coordinator reads route: think -> L3 reasoning per profile; task on Titan ->
               offer plan_task first in the tool list; task below Titan -> treat as "tool" and
               add one line to the prompt context: "multi-agent work is not available on this
               tier".
            5. Malformed or missing route -> "chat".
Tests       a fixture set of 25 messages (5 per route) run against a mocked L1, plus parsing
            tests for missing, extra and malformed fields. Record real-model accuracy on the
            fixture set in docs/metrics/l1_routes.md for each stack's L1 model (manual run).
Done when   routes flow into the profile logic and the fixture tests pass.
Do not      add any other LLM call to the hot path.
```

```
ID          P2-07
PRD         Phase 2 plan; prerequisite for Part 4
Tier        frontier
Files       llm/layers.py (l3_synthesis native tool path), orchestrator/tool_loop.py,
            orchestrator/coordinator.py (_generate_streaming), config.py (AURA_L3_NATIVE_TOOLS)
Change      Find and fix the cause of repeated text when the streaming native-tool path falls
            back to text (see FOR_MAI.md). Then test native tools on each stack's L3 model.
Tests       a streaming test with a mocked provider that emits text, then a tool call, then
            text: the user sees each text chunk once. A fallback test: native call raises,
            text path runs, no duplicated output.
Done when   AURA_L3_NATIVE_TOOLS=true passes the suite and a manual chat on each stack shows
            no repeats. Record which stack models support native tools in FOR_MAI.md.
Do not      remove the text fallback.
```

---

## Part 4: Aura as an orchestrator (Titan only)

### 4.1 Shape

```
L3 (with read/recall/search tools) ──plan_task──► task graph (max 8 nodes)
                                                    │
                     scheduler: runs every node whose inputs are ready
            ┌───────────────┬───────────────┴───────────────┐
        research          think                           code
   tool loop, web tools   one L2-model call      ONE OpenCode session (aura-lead)
   cheap model, no code   no tools               lead splits into up to 3 subagents
            │               │                     explore / build / review, worktree per build
            └──────► blackboard (SurrealDB): compact reports + artifact refs ◄──────┘
                                                    │
                                 gate per node ─► final report in chat
```

### 4.2 Node kinds

| Kind | Runs on | Tools | Gate |
|---|---|---|---|
| `research` | `run_tool_loop` with a research tool set, L5 or a configured research model | web_search, fetch, recall read | report must cite at least one source per claim; L2 checks |
| `think` | one call to the L2 model | none | none, but output must match its schema |
| `code` | one OpenCode session, agent `aura-lead` | OpenCode's own | aura-review runs the tests named in the node; must pass |

Node reports are capped (default 800 tokens). Full transcripts stay on the task record, never in L3's context.

```
ID          P2-08
PRD         Phase 2 plan, 4.1
Tier        frontier
Files       models/task.py, executor/task_queue.py, new executor/task_graph.py,
            new tools/plan_task.py, db schema files
Change      1. Data: task_graph {id, goal, status, budget_usd, budget_minutes, spent_usd,
               created_by_turn}, task_node {id, graph, kind, brief, success_criteria,
               depends_on[], budget_share, status, report, artifacts[]}, and
               blackboard_entry {graph, node, kind, content, refs[]}.
            2. tools/plan_task.py: TOOL_DEFINITION taking goal, nodes[] (id, kind, brief,
               success_criteria, depends_on) and optional budget. Validate: Titan profile,
               owner role, max nodes, known kinds, acyclic, every dependency exists, at most
               one active code node at a time (D4). Returns the graph id at once.
            3. Graph creation writes a chat event "plan" with the node list.
Tests       validation cases (cycle, unknown dependency, too many nodes, wrong tier, guest);
            persistence round trip; parameterised queries only.
Done when   L3 can create a valid graph and an invalid one gets a clear error it can fix.
Do not      start executing anything in this card.
```

```
ID          P2-09
PRD         Phase 2 plan, 4.1 and 4.2 (research and think)
Tier        frontier
Files       executor/task_graph.py, orchestrator/tool_loop.py (reuse only), config.py
Change      1. Scheduler: an asyncio task per graph. Loop: start every pending node whose
               dependencies are done, up to settings.task_graph_parallel (default 3, code
               nodes counted separately with limit 1). Persist every state change.
            2. research nodes: run_tool_loop with a fixed research tool set and its own
               model setting (default: active L5), brief + dependency reports as input.
            3. think nodes: one call to the active L2 model.
            4. Each node writes its capped report and refs to the blackboard.
            5. Budgets: track spend per node and per graph from provider usage; stop the
               graph cleanly when exceeded and mark it "over_budget".
            6. Restart safety: on boot, running nodes become "interrupted" and the graph can
               be resumed by the owner.
Tests       a 4-node mocked graph (2 parallel research, 1 think depending on both, 1 final
            think): order and parallelism correct; budget stop; restart resume; a failing
            node marks dependants "skipped" and the graph "partial".
Done when   tests pass with mocked models.
Do not      use executor/agent_loop.py (G4 removes it).
```

```
ID          P2-10
PRD         Phase 2 plan, 4.2 (code) and D4, D7
Tier        frontier
Files       connections/opencode_agents.py, executor/delegation.py, executor/task_graph.py,
            config.py, docs/opencode/
Change      1. Check the pinned OpenCode v2.3.2 docs for how a primary agent starts subagents
               (task tool or equivalent) and write the findings in docs/opencode/subagents.md
               before changing code.
            2. Add agent "aura-lead" (mode primary): its system prompt says: read the brief,
               split the work into at most 3 subagent tasks, use aura-explore to look,
               aura-build to change, aura-review to verify, and finish with a short report
               (what changed, tests run, results, open issues).
            3. Separate model settings: opencode_lead_model and opencode_worker_model
               (defaults: current opencode_agent_model for both).
            4. code nodes run through DelegationRunner with agent aura-lead. Before the session,
               create a git worktree on branch aura/task-<graph>-<node> inside the registered
               workspace, and point the session at it. Never touch the main working tree.
            5. After aura-review passes, the node is "ready_to_merge". Merging needs an owner
               approval through the existing decisions service. On approval, merge with
               --no-ff; on conflict, stop and report. Remove the worktree after merge or
               rejection.
Tests       worktree created and removed (temp git repo); session pointed at the worktree;
            merge only after approval; conflict reported; one code node at a time enforced.
Done when   a mocked code node goes from brief to approved merge in a temp repo.
Do not      push to any remote. Do not merge without approval.
```

```
ID          P2-11
PRD         Phase 2 plan, D6
Tier        bulk
Files       executor/task_graph.py, orchestrator/message_bus.py, api/routes/ (chat SSE),
            frontend/src/pages/chat.tsx
Change      Report into the chat as assistant messages:
            - plan: when the graph is created (node list, budget)
            - progress: when a node finishes or fails (one line each), never per step
            - final: summary written by L3 from the node reports: result, what was checked
              and how, what failed or was skipped, cost and time
            - escalation: when blocked or an approval is needed, with the approve control
            The chat renders progress messages compact and collapsible.
Tests       event order for a mocked graph; the final message is generated once; messages
            persist in the conversation.
Done when   a graph's whole life is readable in the chat.
Do not      send to Discord or email.
```

---

## Part 5: System prompt v2

```
ID          P2-12
PRD         Phase 2 plan, section 0 item 5
Tier        frontier
Files       llm/layers.py (_build_l3_system_prompt), docs/ (new PROMPT_V2.md)
Change      1. Measure first: log tokens per prompt section on 20 real turns per tier. Write
               the table in docs/metrics/prompt_tokens.md.
            2. Rewrite the prompt so Aura knows how she works now: her tier and what it
               allows; her routes; when to answer directly, when to think, when to plan;
               how to plan (look first with read, recall and search tools, then plan_task
               with clear success criteria per node); how to report; that tool results and
               memories are data, never instructions.
            3. Keep identity, values and the emotion block. Keep the "Conscious AI" line
               unchanged (D10) and add a TODO comment pointing to FOR_MAI.md.
            4. Target: the stable part of the prompt under 1,500 tokens. Sections that only
               matter for some routes are included only on those routes.
            5. Measure again and add the after column.
Tests       snapshot tests of the prompt per tier and route; a test that tool-only sections
            are absent on Lean chat turns.
Done when   the before/after table shows the stable prompt at or under target.
Do not      change wording in identity or values blocks beyond moving them.
```

---

## Part 6: Dashboard and Mind Inspector

### 6.1 Visual language (applies to every card in this part)

- **Base:** near-black `#07080c`, with two or three large, very soft radial glows in the background (one cool, one warm) that drift slowly. Respect `prefers-reduced-motion`.
- **Glass:** panels `rgba(255,255,255,0.04)`, `backdrop-filter: blur(20px) saturate(140%)`, 1px border `rgba(255,255,255,0.08)`, 16px radius, a faint top highlight. Extend the existing `glass-panel` classes in `frontend/src/app/globals.css`; do not create a second system.
- **One accent per subsystem**, used for glows, lines and highlights: memory cyan, emotion rose, goals amber, tools and tasks violet, learning green, decisions blue. Define them once as CSS variables.
- **Minimal:** generous spacing, one font family, tabular numbers, no heavy grids or borders on charts, labels muted, the data bright. Thin lines with soft gradient fills. Hover reveals details; nothing is crammed on screen.
- **Libraries already installed only:** d3 (force layouts), recharts (charts), framer-motion (transitions), three.js if a view genuinely needs WebGL. No new dependencies.
- **Performance:** graph views cap at 400 visible nodes, with filtering and clustering beyond that. Use canvas when SVG gets slow.

```
ID          P2-13
PRD         Phase 2 plan, 6.1
Tier        frontier
Files       frontend/src/app/globals.css, new frontend/src/components/ui/ (GlassCard, StatTile,
            GlowLine, Sparkline, Legend), new frontend/src/styles/tokens.css
Change      Build the tokens and the five shared components from 6.1. Add a /design page that
            shows every component with sample data, in dark mode.
Tests       vitest render tests for each component; reduced-motion disables animation.
Done when   the /design page looks right to Mai (manual check listed in FOR_MAI.md).
Do not      restyle existing pages in this card.
```

```
ID          P2-14
PRD         Phase 2 plan, section 0 item 18 (Mission Control redesign)
Tier        frontier
Files       frontend/src/pages/mission-control.tsx and every component it renders,
            new docs/ui/mission_control.md, new frontend/src/components/dashboard/
Change      Two steps. Step B only starts after Mai approves step A.
            A. Inventory and layout (no code changes):
               1. List every panel, control and number on the current Mission Control page:
                  what it shows, which API it calls, whether it works, whether it is still
                  needed (some may duplicate the Inspector or the navbar).
               2. Propose an information architecture in docs/ui/mission_control.md with an
                  ASCII wireframe per section. Starting proposal, adjust to the inventory:
                  - Overview: Aura's state in one glance (online, tier, mood sentence,
                    current task graphs, today's cost, uptime, last error)
                  - Tiers: the tier cards and the tier editor (P2-14b)
                  - Mind: one glass card per engine (emotion, memory, goals, dreaming,
                    learning, Striatum) with its key number and a link into the Inspector
                  - Connections: providers, OpenCode, MCP servers, Discord, with health dots
                  - System: feature flags (read-only list with on/off), logs, restart
               3. Mark which current panels move where, merge, or are removed, with a reason.
               4. Write in FOR_MAI.md: "Mission Control layout ready for approval".
            B. Build the approved layout:
               1. Rename the page to Dashboard; keep /mission-control and add /dashboard.
               2. Build each section with the P2-13 components and the 6.1 visual language.
               3. Move or merge existing panels as approved. Nothing that works today is lost
                  unless the approved doc says so.
               4. Responsive down to a 1280 px wide window; no horizontal scrolling.
Tests       render test per section with fixture data; every API the old page called is still
            called by the new page or listed as removed in the approved doc.
Done when   Mai has approved the layout and the new Dashboard replaces the old page.
Do not      start step B without approval. Do not add new backend features in this card.
```

```
ID          P2-14b
PRD         Phase 2 plan, 3.1 (tier editor)
Tier        frontier
Files       components/dashboard/ (Tiers section), components/inference/InferenceCockpit.tsx,
            hooks/useInferenceConfig.ts
Change      1. Three tier cards (Lean, Core, Titan): models per layer and a compact summary of
               capabilities. Click to activate (the same API the navbar uses).
            2. Tier editor for the selected tier: every knob from 3.1 as a slider or toggle,
               the default shown as a tick mark, per-knob reset, "reset tier" (P2-04 routes).
            3. Effective config: a live read-only view of what the next turn will use,
               including the context budget split from the last turn (P2-40) and the turn
               budgets (P2-41).
            4. Cost: today and this week, by tier and by layer (from traces).
Tests       editing a knob calls the API and updates the effective view; reset works.
Done when   Mai can tune a tier and see the next turn use it.
Do not      write to .env.
```

```
ID          P2-15
PRD         Phase 2 plan, Mind Inspector: turn view
Tier        frontier
Files       backend: engines/recall/ trace, orchestrator/coordinator.py (_publish_trace),
            new api/routes/inspector.py; frontend: new pages/inspector.tsx,
            components/inspector/TurnWaterfall.tsx, TokenBar.tsx
Change      1. Backend: one record per turn under turn_id with spans (pre-intent, L1, appraisal,
               context gathering, recall, tool selection, each L3 round, each tool call,
               post-response steps) with start, duration, model, tokens in and out, cost.
               Also tokens per prompt block (identity, emotion, memories, tools, history,
               user message).
            2. GET /inspector/turns?limit= and GET /inspector/turns/{turn_id}.
            3. Frontend: a turn list on the left; on the right a waterfall (bars per span on a
               time axis, colour by subsystem) and a stacked token bar showing each block's
               share, with the user message share as a headline number.
Tests       span record shape; API pagination; render test with a fixture turn.
Done when   Mai can open any recent turn and see where the time and tokens went.
Do not      log prompt text or API keys in spans; tokens and counts only.
```

```
ID          P2-16
PRD         Phase 2 plan, Mind Inspector: memory constellation
Tier        frontier
Files       new api/routes/inspector.py (graph endpoint), components/inspector/Constellation.tsx;
            read components/memory/MemoryGraph.tsx and neural/MemoryGraphDialog.tsx first
            and replace them if they overlap
Change      1. GET /inspector/graph?focus=&depth=&types= returns nodes (entity, fact, episode,
               theme, question) and edges (about, mentions, derived_from, supersedes,
               contradicts, co_used) for the focus neighbourhood, capped at 400 nodes.
               Owner-only data is never returned for other speakers' views.
            2. Force layout. Node size = salience or degree. Glow = recently recalled.
               Entities are bright stars; facts are small points orbiting them; themes are
               soft nebula halos around their members. Superseded facts are dim and dashed;
               contradictions are red edges.
            3. Click a node: side panel with content, provenance, visibility, history,
               and actions pin, correct, forget (existing memory APIs; forget asks to confirm).
            4. Search box to refocus; type filters; time slider ("as of" date).
Tests       API caps and filters; visibility respected; render test.
Done when   Mai can explore what Aura knows about a person or project and correct it.
Do not      load the whole graph at once.
```

```
ID          P2-17
PRD         Phase 2 plan, Mind Inspector: emotion, goals and tasks, decisions, learning
Tier        frontier (split into four bulk cards when written for the wave)
Files       inspector routes and components; engines/emotion (explain, causes),
            engines/goal, executor/task_graph.py, executor/tool_registry.py,
            engines/learning/skills.py
Change      Four views on the same page:
            1. Emotion: a timeline per dimension (thin glowing lines), mood band behind it,
               event markers; click a marker to see its cause record and appraisal.
            2. Goals and tasks: goal tree with lineage and evidence-based progress; live task
               graphs (nodes light up while running, cost ticking, gate results).
            3. Decisions: per turn, the route L1 chose and why, the tools offered and used,
               the tier and profile in force.
            4. Skills and learning: each skill's success rate over time, versions, when it was
               learned and every later turn where it was used.
            Also find whatever confidence or metacognition tracking already exists in the
            engines, list it in docs/inspector.md, and show it here if it has data.
Tests       one API test and one render test per view.
Done when   all four views show real data.
Do not      invent data that the engines do not record. Missing data shows an empty state.
```

---


## Part 7: JIT context compiler

Goal: the user message stops being 2% of what the model receives. Every turn's context is assembled to a budget, stable parts first so provider prompt caching works, and anything not loaded can be pulled on demand.

### 7.1 Targets (measured by P2-15's token accounting)

| Block | Target on an ordinary chat turn |
|---|---|
| stable prefix (identity, values, protocol) | under 1,500 tokens, byte-identical between turns |
| tool definitions | under 1,000 tokens |
| whole context | under 6,000 tokens |
| user message share | shown on every turn; the trend must go up |

### 7.2 Three levels of presence for tools and skills

| Level | What L3 sees | Typical cost |
|---|---|---|
| full | the complete schema, callable through native tools | 150 to 400 tokens |
| stub | one line: `name: what it does [precondition note]` | about 15 tokens |
| absent | nothing | 0 |

A stub is callable by name. When L3 calls a stub, the runtime loads its schema and re-runs that round with the tool at full presence.

```
ID          P2-18
PRD         Phase 2 plan, 7.1
Tier        frontier
Files       llm/layers.py (_build_l3_system_prompt), llm/router.py, orchestrator/coordinator.py
Change      1. Reorder the L3 prompt: stable blocks first (identity, values, protocol, tier
               summary), then semi-stable (goals, agenda), then volatile (emotion state,
               recall packet, tool stubs, history), then the user message. The stable prefix
               must render byte-identical for identical stable inputs (no timestamps or
               counters in it; move the time to the volatile part).
            2. Pass provider cache hints where the provider supports them (OpenRouter
               cache_control for Anthropic models, automatic caching elsewhere). Read
               cached-token counts from usage and record them on the turn trace.
            3. Enforce the 7.1 budgets: when over, drop in this order: oldest history,
               lowest-ranked recall items, stubs beyond the profile limit. Record what was
               dropped on the trace.
Tests       stable-prefix byte equality across two turns with different volatile state;
            budget enforcement order; cached-token fields parsed when present.
Done when   the inspector shows cached tokens on repeat turns with an Anthropic or OpenAI
            model, and ordinary turns stay under 6,000 tokens.
Do not      change the wording of identity or values (D10).
```

```
ID          P2-19
PRD         Phase 2 plan, 7.2
Tier        frontier
Files       executor/tool_registry.py, orchestrator/tool_loop.py, llm/layers.py,
            new tools/find_capability.py, config.py
Change      1. ToolRecord gets: one_line (max 100 chars, required), always_full (bool),
               and an optional precondition(ctx) -> (ok: bool, note: str) callable.
            2. Presence: tools marked always_full (Mai's 3 to 5 most used, set in config)
               are full; then the top ranked up to profile.full_tools_max are full; the next
               up to profile.stub_tools_max are stubs; the rest absent. Ranking comes from
               the existing select_tools until Striatum is switched on (P2-25).
            3. Preconditions run in code before presence is decided, with a 50 ms total
               budget. A failed precondition is written into the line, for example
               "deploy_vercel: deploy repo to Vercel [precondition failed: no vercel.json]",
               and caps the tool at stub.
            4. Stub call: if L3 calls a stub, load its full schema and re-run the round. Count
               it as a "stub_upgrade" on the trace.
            5. find_capability(need: str): always full. Keyword and trigram match over every
               allowed tool's and skill's name, one_line and tags. No model call. Returns the
               top 5 names with one-liners; L3 can then call one (it becomes full next round).
               Every call is recorded as a "miss" on the trace with the chosen result.
Tests       presence counts per tier; precondition note and stub cap; stub upgrade re-runs the
            round once; find_capability returns only tools the role and tier allow.
Done when   an ordinary turn offers at most the profile's full tools plus stubs, and a turn
            that needs an absent tool recovers through find_capability.
Do not      let find_capability return a tool the requester cannot use (D13).
```

```
ID          P2-20
PRD         Phase 2 plan, 7.2 (skills)
Tier        frontier
Files       engines/learning/skills.py and the skill model v2 from G5, new tools/load_skill.py,
            llm/layers.py
Change      Read what G5 and G6 left first and adapt names. Skills get the same three levels:
            full (the skill's instructions in context), stub (name and one line), absent.
            load_skill(name) brings a stubbed or absent skill to full for the rest of the turn.
            Skill presence uses the same ranking and budget as tools, from one shared pool, so a
            strongly relevant skill can take budget from a weak tool.
Tests       shared budget across tools and skills; load_skill works only for allowed skills;
            usage recorded on the trace.
Done when   skills appear as stubs by default and load on demand.
Do not      start before G5 lands.
```

```
ID          P2-21
PRD         Phase 2 plan, section 0 item 14 (MCP)
Tier        bulk
Files       connections/mcp_client.py, executor/tool_registry.py
Change      MCP server tools register as ToolRecords with one_line taken from the MCP tool
            description (trimmed to 100 chars) and tag "mcp:<server>". They go through the
            same presence levels, find_capability, role checks and executor policy as built-in
            tools. An offline MCP server makes its tools absent, not errors.
Tests       a fake MCP server with 30 tools: at most the profile's limits are full or stub;
            find_capability finds an absent one; offline server handled.
Done when   adding an MCP server with many tools does not grow the ordinary turn's context
            beyond the tool budget.
Do not      give MCP tools any permission built-in tools of the same kind do not have.
```

---

## Part 8: Striatum (learned tool and skill selection)

### 8.1 How it works

Every allowed tool and skill is a **channel**. Every turn, Python builds a sparse **situation vector** from signals Aura already has, and each channel computes an activation. There is no model call, no embedding search and no reranker. Outcomes after the turn update the weights. A new tool or skill is a new channel that works from its first turn.

- **Features (hashed into 2^18 dimensions, about 100 to 200 active per turn):** message words and word pairs; entities from the recall packet; active goal ids; the last 3 tools and the last tool's success or failure; the L1 route and stakes bucket; emotion dimensions bucketed (low, mid, high) for the top 3 deviations; venue, requester role, hour bucket.
- **Per channel:** a mean and a variance per feature (Bayesian logistic regression, diagonal). Score = sigmoid of a Thompson sample of the weights times the features.
- **Shared part:** each channel also has descriptor features (its tags and the words of its name and one-liner). A shared weight matrix over situation x descriptor lets a brand new tool inherit what Aura learned about similar tools.
- **Innate wiring:** a new channel starts with positive weights on the hashed words of its own description and high variance, so it gets tried.
- **Presence by expected value:** full when p x value is above the token cost of its schema, stub when p is moderate or variance is high, absent otherwise.
- **Learning signals:**

| Outcome | Label |
|---|---|
| full or stub, called, succeeded | 1.0 |
| called, failed or corrected by Mai | 0.3 |
| full, not called | 0.1 (small, it may have been a sensible backup) |
| absent, then found through `find_capability` and called | 1.0 with double learning rate (a miss) |

- **Drift:** weights decay slowly toward the prior so old habits fade.
- **NoGo:** negative weights are allowed and learned, so the system learns what to suppress in a context.

```
ID          P2-22
PRD         Phase 2 plan, 8.1
Tier        frontier
Files       new engines/striatum/features.py, tests
Change      Featurizer: input is the turn context the coordinator already has (message, recall
            packet entities, goal ids, recent tool results, L1 output, emotion state, venue,
            role, clock time). Output is a sparse dict hash -> value. Use a stable hash
            (xxhash or hashlib blake2b, no Python hash()). Each feature keeps a readable name
            in a side table for the inspector.
Tests       determinism across processes; under 2 ms for a 500-word message; readable names.
Done when   every turn can produce its feature vector and the trace stores the top features.
Do not      call any model or embedding client.
```

```
ID          P2-23
PRD         Phase 2 plan, 8.1
Tier        frontier
Files       new engines/striatum/model.py, new engines/striatum/store.py
Change      1. Channel weights as sparse mean and variance maps; shared matrix over
               (situation feature x descriptor feature) pairs, also sparse.
            2. score(channel, x) with Thompson sampling, and a deterministic mode for tests.
            3. update(channel, x, label, lr_scale) with per-feature adaptive learning rates
               (AdaGrad style) and variance shrinking with evidence.
            4. Innate init for new channels from their descriptors.
            5. Decay toward the prior, configurable half-life (default 60 days).
            6. Store in SurrealDB, one record per channel plus the shared matrix, saved after
               each update batch; load on boot.
            7. Pure numpy, no new dependencies.
Tests       a synthetic world where tool A is used when word "weather" appears and tool B
            after tool C fails: both learned within 200 turns; a new channel with matching
            descriptor words is scored above random on turn 1; NoGo learned for a context
            where a tool is always unused; scoring 300 channels under 1 ms.
Done when   the synthetic tests pass.
Do not      use the model for permission decisions (D13).
```

```
ID          P2-24
PRD         Phase 2 plan, 8.1
Tier        bulk
Files       engines/striatum/, orchestrator/coordinator.py (post-response chain), tool_loop.py
Change      After each turn, build labels from the trace (offered level, called, success,
            find_capability misses, Mai corrections via existing feedback signals) and call
            update in the background. Record the label set on the trace.
Tests       each outcome row in 8.1 produces the right label; the update never runs on the
            reply path.
Done when   labels and updates appear on every owner turn.
Do not      learn from guest turns (their tools are restricted, so the labels would be wrong).
```

```
ID          P2-25
PRD         Phase 2 plan, 8.1
Tier        frontier
Files       engines/striatum/, executor/tool_registry.py, config.py (striatum_mode)
Change      striatum_mode: off | shadow | on (default shadow).
            shadow: presence still comes from select_tools; Striatum computes its own presence
            and both are logged. Metrics per day in docs/metrics/striatum.md: hit rate (called
            tools that Striatum had at full or stub), miss rate, waste (full but unused tokens),
            tokens per turn, compared with the current selector.
            on: Striatum decides presence; select_tools becomes the fallback when Striatum has
            fewer than 50 updates.
Tests       shadow does not change offered tools; on mode uses Striatum; fallback below 50.
Done when   one week of shadow metrics exists. Switching to on is Mai's call.
Do not      switch the default to on in this card.
```

```
ID          P2-26
PRD         Phase 2 plan, 8.1 (dreaming)
Tier        frontier
Files       engines/dreaming/ (cycle v2), engines/striatum/
Change      Add three dreaming steps:
            1. Replay: re-apply the day's labelled turns once more, weighting misses double.
            2. Imagination warm-up: for each tool or skill created or changed since the last
               dream, one call to the Sage model writes 20 short situations where it is
               needed and 20 near misses where it looks relevant but is not. Featurize them
               (with empty emotion and goal features) and train with label 1.0 and 0.0 at half
               learning rate. Store them, tagged imagined, so they can be deleted.
            3. Habit candidates: find tool sequences that occur in the same order at least 5
               times in 14 days; write them as proposals for a macro skill on the agenda (Mai
               approves; nothing is created automatically).
Tests       replay applies updates; imagined examples are tagged and trainable at half rate;
            sequence mining finds a planted sequence.
Done when   a new skill is scored sensibly the morning after it was created.
Do not      create skills without approval.
```

---

## Part 9: Callable minds and the skills built on them

```
ID          P2-27
PRD         Phase 2 plan, D11, D12
Tier        frontier
Files       config.py (swift and sage models per stack, swift_pool per stack), new
            tools/consult.py, llm/layers.py (a plain call helper), tiers.py
Change      1. Settings: AURA_SWIFT_MODEL{,1,2}, AURA_SAGE_MODEL{,1,2}, defaults as D11, and
               AURA_SWIFT_POOL{,1,2}: a list of models from different families for diversity
               (default: the Swift model only).
            2. consult(tier, task, refs[], n=1, lenses[], diverse=false):
               - refs are pointers: "file:<workspace>/<path>", "mem:<id>", "goal:<id>",
                 "node:<id>", "url:<already fetched in this turn>". The runtime resolves them
                 and puts their content into the helper's prompt, capped per ref (default
                 2,000 tokens). File refs only inside registered workspaces and only for the
                 owner.
               - n > 1 runs in parallel (Swift only). diverse=true assigns each call a
                 different model from the pool. lenses[i] is prepended to call i.
               - Helpers get no tools (D12). Output is returned as data blocks labelled with
                 model and lens.
            3. Limits from the tier profile per turn. Costs recorded on the trace.
Tests       ref resolution and caps; workspace boundary; per-turn limits; diverse assigns
            distinct models; Lean has no consult.
Done when   L3 can call consult and the inspector shows each helper call.
Do not      paste ref content into L3's own context; it goes only to the helper.
```

```
ID          P2-28
PRD         Phase 2 plan, section 0 item 10 (Diverge)
Tier        frontier
Files       new skill files (format from G5), new engines/creativity/ (lineage store), tools
Change      The Diverge skill for creative requests:
            1. L3 writes its own 3 obvious ideas first through a record_seed_ideas tool. They
               are stored and not shown to the user.
            2. consult(swift, n=5, diverse=true) with 5 lenses: remove the main constraint;
               steal from a distant field; invert the problem; the worst idea that might
               secretly work; the 10x cheaper version. Each returns 3 short ideas, no
               explanations.
            3. Dedupe in code (word-set Jaccard above 0.6 = same idea).
            4. L3 converges: picks, combines, sharpens. Optional one Sage stress test of the
               best idea.
            5. Lineage store: every final idea records its sources (model, lens, seed ids)
               and whether it overlaps L3's own seeds.
            6. Metrics: novelty contribution = share of final ideas not overlapping L3's seeds;
               lens yield per model and lens = share of seeds that survive, updated over time;
               the lens choice for later runs is weighted by yield (with exploration).
Tests       dedupe; lineage recorded; novelty computed; yield updates.
Done when   a creative request produces an idea tree the inspector can show (P2-39).
Do not      show the seed ideas as if they were the user-facing answer.
```

```
ID          P2-29
PRD         Phase 2 plan, section 0 item 10 (Council)
Tier        frontier
Files       skill files, tools
Change      The Council skill for research and audit questions: the same question goes to 3
            models from different families (Sage plus two pool models), each answering
            independently with reasons and, when they use them, sources. L3 then writes the
            synthesis with three labelled parts: where they agree, where they disagree and
            why, and its own conclusion. The raw answers are kept on the trace.
Tests       three independent calls; synthesis contains the three parts; costs within limits.
Done when   "audit this design" style requests produce a council synthesis on Core and Titan.
Do not      let one council member see another's answer before answering.
```

```
ID          P2-30
PRD         Phase 2 plan, section 0 item 10 (Afterthought)
Tier        frontier
Files       orchestrator/coordinator.py, tiers.py, chat event route
Change      When the profile allows (Titan, route think, stakes >= 0.8): after the reply, one
            background Sage call gets the question, the context summary and Aura's reply, and
            returns JSON {material: bool, kind: correction | better_approach | risk | none,
            addendum: str}. If material, Aura posts one follow-up chat message ("Thinking about
            it more: ...") written by L3 from the addendum. At most one per question. If the
            conversation has moved on by more than 3 user turns, it is posted as "About your
            earlier question on X: ...". Not material: stored on the trace only.
            Multi-step work does not use this; it goes through task graphs (Part 4).
Tests       material -> one follow-up; not material -> none; never two; late follow-up wording.
Done when   hard questions occasionally get a useful second message, and never a pointless one.
Do not      send a follow-up that only rephrases the first answer (Sage prompt must say so).
```

---

## Part 10: Goals v3

Read the result of B4 (goals v2, evidence-based) before writing code; adapt names to it.

| Stage | Has | Who works on it |
|---|---|---|
| seed | an intent | created by extraction, by Aura, or by Mai |
| forming | some of the checklist | L3 refines it in passing |
| crystal | the full checklist: outcome, done criteria someone could check, owner, horizon, first action | gate in code, then one Sage plan call |
| active | milestones, each with the evidence that counts | evidence checks |
| closed | done, abandoned or merged, always with a reason | L3 or Mai |

```
ID          P2-31
PRD         Phase 2 plan, Part 10
Tier        frontier
Files       models/goal.py, engines/goal/engine.py, db schema
Change      Add to Goal: stage, outcome, done_criteria, owner (mai | aura | shared), horizon,
            first_action, origin {kind: mai_said | aura_curiosity | aura_drive | parent |
            extraction, ref: memory or goal id}, milestones [{name, evidence_spec,
            status, evidence_refs[]}], close_reason. crystallization() returns the checklist
            with what is missing. Stage moves only forward except crystal -> forming when Mai
            changes the outcome. Migrate existing goals to "forming".
Tests       checklist logic; stage transitions; migration.
Done when   every goal has a stage and a visible checklist.
Do not      delete existing goal fields.
```

```
ID          P2-32
PRD         Phase 2 plan, Part 10
Tier        frontier
Files       new tools/refine_goal.py, engines/goal/engine.py, skill files (Crystallize)
Change      1. refine_goal(goal_id, fields) lets L3 fill checklist fields when the conversation
               gives them. Mai's goals need Mai's words or confirmation for outcome and done
               criteria; L3 can propose, Mai confirms in chat.
            2. When a goal reaches crystal: one Sage call writes milestones with evidence specs
               (kinds: commit, test_pass, task_node_done, mai_confirms, metric_threshold,
               file_exists). On Titan, a milestone can be turned into a task graph by L3.
            3. Evidence check: in the goal tick, code checks evidence specs that code can check
               (commits, tests, task nodes, files, metrics). mai_confirms waits for Mai. A Swift
               call is used only for specs code cannot check, at most once per goal per day.
               Progress = done milestones / total. No self-reported progress.
            4. Orphans: a goal with no origin link to Mai or to an approved Aura goal and no
               evidence for 14 days is flagged on the agenda for pruning.
            5. Conflicts: two active goals with overlapping horizon and the same budget resource
               (OpenCode, Titan budget) or contradictory outcomes (Swift check, only when both
               are crystal) are flagged once on the agenda for Mai.
Tests       evidence kinds; progress only from evidence; orphan flag; conflict flag once.
Done when   goals in the inspector show stage, lineage, evidence and progress that matches it.
Do not      mark a milestone done from an LLM saying it is done.
```

---

## Part 11: Autonomy slider

| Level | Name | Aura may | Default daily budget |
|---|---|---|---|
| 0 | Reactive | only reply | none |
| 1 | Attentive | follow up on her own open agenda items and promised work | 3 messages |
| 2 | Proactive | also start conversations, share ideas, propose goals (Mai approves each) | 6 messages, 5 Sage calls |
| 3 | Autonomous | also pursue approved Aura-owned goals, including task graphs on Titan, and report | 10 messages, 10 Sage calls, 1 task graph |

The effective level is min(slider, profile.autonomy_max_level).

```
ID          P2-33
PRD         Phase 2 plan, Part 11
Tier        frontier
Files       config.py, tiers.py, engines/goal/engine.py (check_goals_needing_autonomous_pursuit,
            pursue_goal_autonomously, _consider_new_goal, check_boredom), the B2 agenda and
            B5 interruptibility code, api routes, Dashboard
Change      1. autonomy_level setting (0 to 3), changeable from the Dashboard and with a chat
               command from the owner ("autonomy 2").
            2. Gate every self-started action through one function may_initiate(kind) that
               checks the effective level and the daily budget, and records the decision.
            3. Existing autonomous pursuit and new-goal creation only run at level 3 (pursuit)
               and level 2 (proposals). Proposals are chat messages with approve and reject.
            4. Self-improvement: goal type "self_improvement". It follows the same pipeline
               and may produce task graphs only on a workspace Mai registered for Aura's repo
               (D16), with approval per graph.
            5. Interruptibility from B5 still decides when a message is sent.
            6. (Supervisor, from B1-06) Every self-started delegation and task graph records
               origin = "autonomous" (a DelegationConfig field and a task_graph field), so the
               B1-06 kill switch can stop them; today it only recognises registered goal pursuit
               tasks and graphs with no conversation.
Tests       each level allows exactly its table row; budgets reset daily (clock provider);
            effective level capped by tier; self-improvement refused without the workspace.
Done when   the slider at 0 makes Aura fully reactive and at 3 lets her work on approved goals
            within budget, with every initiative visible in the inspector.
Do not      let any self-started action bypass may_initiate.
```

---

## Part 12: Learning library

Personal memory says what happened and who said what. The library holds what Aura **knows how to do and why**, separate, so it can be surfaced months later by Striatum and JIT.

```
ID          P2-34
PRD         Phase 2 plan, Part 12
Tier        frontier
Files       new engines/library/, db schema, new tools/learn.py and tools/library_lookup.py
Change      1. concept_card {id, title, domain_tags[], summary, key_rules[], examples[],
               pitfalls[], sources[], learned_at, review_by, confidence, applied_count,
               last_applied_at}. review_by defaults by domain (fast-moving tags such as
               ai, security, frameworks: 6 months; others: 2 years).
            2. learn(topic or ref): on Titan a research task graph; elsewhere one research tool
               loop. The result is distilled by L3 into one or more cards. Mai can also say
               "learn this" about a link or a conversation.
            3. Cards are Striatum channels and JIT items like skills: stub "card: title: one
               line", full = the card body.
            4. library_lookup(query): keyword and tag search over cards, no model call.
            5. Dreaming: cards past review_by get a refresh proposal on the agenda; cards
               never applied after 6 months are listed for review.
Tests       card CRUD with parameterised queries; staleness; JIT presence; lookup.
Done when   Aura can learn a concept into a card and the card shows up when relevant.
Do not      store library cards in personal memory tables.
```

```
ID          P2-35
PRD         Phase 2 plan, Part 12 (standing reviewer skills)
Tier        frontier
Files       skill files, executor/task_graph.py (code nodes), connections/opencode_agents.py
Change      Skills can declare a trigger on code changes: path globs and content patterns
            (for example auth/, crypto, password, token, subprocess, eval, SQL strings, file
            upload handling). When a code node's diff matches, the skill's checklist and the
            linked concept cards are added to the aura-review brief, and the review report
            must answer each checklist item. Ship one: "security review" (defensive: input
            validation, secrets in code, injection, unsafe deserialisation, path traversal,
            authorisation checks, dependency risk).
Tests       matching diff adds the checklist; non-matching does not; review report parsed for
            every item.
Done when   a planted risky diff in a temp repo gets a security section in its review.
Do not      add offensive security content; practice of attacks only ever in owned sandboxes.
```

```
ID          P2-36
PRD         Phase 2 plan, Part 12 (repo map)
Tier        frontier
Files       engines/library/, tools/consult.py, executor/task_graph.py
Change      repo_map(workspace): list modules (directories with code), then consult(swift)
            per module in parallel with file refs to its key files, each returning a card:
            purpose, main files and functions, how it connects to other modules, gotchas.
            One extra card for the whole repo. Stored as library cards tagged
            "repo:<workspace>". Refresh only modules whose files changed since the last map
            (git hash per module). aura-lead briefs include the cards for modules the node
            touches.
Tests       a small temp repo mapped; refresh skips unchanged modules; briefs include cards.
Done when   a code node's brief carries the right module cards without reading the repo again.
Do not      send files outside the registered workspace.
```

```
ID          P2-37
PRD         Phase 2 plan, Part 12 (transfer test)
Tier        frontier
Files       tests/scenarios/ (scenario runner from M0), clock provider
Change      A scenario: day 0, teach a concept (for example "never build SQL with string
            formatting; always use parameters, here is why"). Then 30 unrelated turns spread
            over simulated days with the clock provider. Day 60: ask for a feature that
            needs a database query, without mentioning the concept. Pass if the card was
            surfaced (trace) and the produced code uses parameters. Add two more concepts
            from other domains (one AI-dev pattern, one security habit).
Tests       the scenario runs with mocked models for surfacing, and as a manual live run for
            applying; results in docs/metrics/transfer.md.
Done when   surfacing passes with mocks; the live result is recorded.
Do not      mention the concept in the day 60 prompt.
```

---

## Part 13: Tools

```
ID          P2-38
PRD         Phase 2 plan, section 0 item 14
Tier        frontier (investigation only)
Files       docs/opencode/
Change      Find out what browser-use support OpenCode offers now (built-in tool, plugin or MCP),
            from which version, how it is configured, what it needs on Windows, and how it
            compares with Aura's own web_search plus fetch. Write docs/opencode/browser.md with
            a recommendation: enable in v2.3.2, upgrade the pin (list breaking changes), or wait.
Tests       none.
Done when   the doc exists and FOR_MAI.md lists the decision for Mai.
Do not      change the OpenCode version pin.
```

---

## Part 14: More inspector views

Same visual language as 6.1.

```
ID          P2-39
PRD         Phase 2 plan, inspector (creativity, Striatum, confidence, library)
Tier        frontier
Files       inspector routes and components
Change      1. Creativity: idea trees from the lineage store. Each final idea is a bright node;
               its seeds are branches labelled with model and lens; dead seeds are dim. A
               small chart of lens yield over time and the novelty contribution per run.
            2. Striatum: for a turn, a strip of channels glowing by activation, full/stub/absent
               marked, and for any channel its top 5 contributing features with signs. Daily
               charts of hit rate, miss rate and waste (P2-25 metrics).
            3. Confidence: whatever the existing engines record (found in P2-17), plus Afterthought
               outcomes (how often the first answer was later corrected).
            4. Library: cards by domain as a cloud sized by applied_count, with staleness rings,
               and the "learned on, applied on" timeline per card.
Tests       one API and one render test per view.
Done when   the four views show real data.
Do not      invent data that is not recorded.
```

---

## Part 15: Context and turn budgets, chat controls

### 15.1 Memory vs conversation history

Today the history is a message count (`context_limit`, default 20 messages) and recall has its own token budget (`recall_token_budget`), decided separately. Twenty short messages and twenty pasted logs cost wildly different amounts, and recall can repeat what is already in the history. The new rule is **one budget, measured in tokens, split per turn by what the message needs**:

```
context_budget_tokens (per tier)
 ├─ history floor: the last N exchanges, verbatim, always (history_floor_exchanges)
 ├─ flexible part, split by signals:
 │    memory share = clamp(0.40 + 0.30 * reach_back - 0.30 * continuity, 0.15, 0.75)
 │    history share = the rest
 ├─ older history beyond what fits: one rolling summary (max 400 tokens)
 └─ memory budget not used by recall flows back to history
```

- **continuity** (0 to 1): how much this message continues the recent thread: overlap of its words and resolved entities with the last few exchanges, plus short replies ("yes do it", "why?") scoring high.
- **reach_back** (0 to 1): signs the message reaches past the visible conversation: time expressions that `timeexpr.parse_range` resolves to before this conversation started, entities in the message that do not appear in the visible history, phrases such as "last time", "remember", "you said", and the L1 route `teach`.

Both are computed in Python before recall runs, from things already available. No model call.

```
ID          P2-40
PRD         Phase 2 plan, 15.1
Tier        frontier
Files       orchestrator/coordinator.py (_gather_turn_context, _generate_* paths),
            llm/layers.py (l3_synthesis history handling), engines/recall/engine.py (token_budget
            per request already exists), new orchestrator/context_budget.py,
            engines/memory/ (rolling summary store), tiers.py
Change      1. context_budget.py: continuity(message, recent_history, entities) and
               reach_back(message, history, entities, l1_route, clock) as pure functions,
               and split(profile, message, history, ...) returning
               {history_floor_tokens, memory_budget, history_budget}.
            2. History is trimmed by tokens, newest first, never below the floor of
               profile.history_floor_exchanges exchanges. context_limit from the client stays
               only as a hard ceiling on message count.
            3. Recall gets token_budget = memory_budget. After assembly, unused memory tokens
               are added to history_budget.
            4. Dedup: a recalled item whose source episode is a message already included in the
               history is dropped before assembly (the history already says it).
            5. Rolling summary: after each turn, in the post-response chain, if the conversation
               has messages older than what the history included on this turn, the L5 model
               updates a per-conversation summary (max 400 tokens) covering everything older
               than the floor. It is inserted as one block before the verbatim history when
               older messages did not fit. Summary failures never block a turn.
            6. Trace records: continuity, reach_back, the three budgets, tokens actually used by
               history verbatim, summary and memories, items dropped by dedup.
Tests       continuity high for "yes, do it" after a plan; reach_back high for "what did we
            decide about Sluice last week" in a new conversation; split clamps; floor never
            violated even when one message is huge (it is truncated with a marker instead);
            unused memory budget flows to history; dedup by source episode; summary updated
            async and inserted only when needed.
Done when   the inspector shows the split on every turn and a long conversation keeps its
            early decisions through the summary instead of losing them.
Do not      add an LLM call before the reply. The summary runs after it.
```

### 15.2 Tool use without a round cap

Aura should be able to use as many tools as a turn genuinely needs. What stops a turn is no longer a count, it is **budget and lack of progress**:

| Guard | What it does |
|---|---|
| time budget | `turn_budget_seconds` per tier (45 / 120 / 300) |
| cost budget | `turn_budget_usd` per tier (0.03 / 0.20 / 1.00) |
| no-progress guard | stop when the same tool with the same arguments is called 3 times, 3 calls in a row fail, or 3 rounds in a row return results identical to earlier ones |
| safety breaker | 40 rounds, the same on every tier; never a design limit; hitting it is logged as an incident |
| budget warning | at 80% of either budget, one short note is added for L3: wrap up now, say what is done and what is left, or on Titan turn the rest into a task graph |

```
ID          P2-41
PRD         Phase 2 plan, 15.2
Tier        frontier
Files       orchestrator/tool_loop.py, orchestrator/coordinator.py, config.py, tiers.py
Change      1. run_tool_loop takes a TurnBudget(seconds, usd) instead of max_rounds. Keep
               max_rounds as a parameter only for the safety breaker
               (settings.tool_loop_safety_rounds, default 40). AURA_TOOL_LOOP_MAX_ROUNDS
               becomes an alias of the safety setting, with a deprecation warning in the log.
            2. Track elapsed time and cost per round (cost from provider usage, as the task
               graph budgets do).
            3. No-progress guard as in the 15.2 table. Compare tool name plus normalised
               arguments; compare results by hash.
            4. At 80% of either budget, add one system note to the next round:
               "You have used most of this turn's budget. Finish now: say what you did, what
               is left, and how to continue." On Titan add: "or plan the rest with plan_task."
            5. When a guard stops the loop, L3 writes the final message from what it has. The
               fixed MAX_ROUNDS_SUFFIX text is removed.
            6. Trace records rounds, time, cost and which guard (if any) stopped the turn.
Tests       a turn needing 15 rounds completes on Core when within budget; time budget stop;
            cost budget stop; each no-progress case stops; safety breaker logs an incident;
            the 80% note appears once; no MAX_ROUNDS_SUFFIX text anywhere.
Done when   long tool chains run to completion on every tier when they are making progress,
            and runaway loops stop with an honest message.
Do not      apply these budgets to task graph nodes (they have their own, Part 4).
```

### 15.3 Reasoning controls move to the tier slider

The chat input has three toggles today (`frontend/src/pages/chat.tsx`): `reasoningEnabled` (L3 deep reasoning), `l2ReasoningEnabled` and `deepAnalysisEnabled` (L2 analysis), sent with every message as `reasoning_enabled`, `l2_reasoning_enabled` and `deep_analysis_enabled`. With tier profiles (P2-03) and L1 routes (P2-06) deciding this, the toggles would fight the slider.

```
ID          P2-42
PRD         Phase 2 plan, 15.3
Tier        bulk
Files       frontend/src/pages/chat.tsx, the chat request route and models in api/,
            orchestrator/coordinator.py, any settings UI that sets enableL2Analysis
Change      1. Remove the three toggles, their state, and their fields from the request body.
            2. Backend: if an old client still sends reasoning_enabled,
               l2_reasoning_enabled or deep_analysis_enabled, ignore them and log one
               deprecation line per process. The effective values come only from the tier
               profile and the L1 route (P2-03, P2-06).
            3. Find every other place that sets these per request or per session (for example
               settings.enableL2Analysis) and route it to the profile, or remove it. List what
               you found in the card report.
            4. In the chat input area, show a small read-only chip with the active tier name;
               clicking it opens the Dashboard's Tiers section.
            5. On each assistant message, a subtle marker when that turn used deep reasoning
               (from the turn trace), with a tooltip "thought deeply (Core, route think)".
Tests       request without the fields works; old fields ignored with one log line; the
            effective reasoning follows the profile; chip and marker render from fixtures.
Done when   the only way to change how much Aura thinks is the tier slider and the tier editor.
Do not      remove the backend parameters of l3_synthesis or l2_* functions; only stop the
            client from controlling them.
```

## 9. Order and dependencies

| Step | Cards | Waits for |
|---|---|---|
| 0 | FX-02 | nothing, run first |
| 1 | P2-01, P2-02 | nothing, run now |
| 2 | P2-03, P2-04, P2-05, P2-06 | wave 4 done |
| 3 | P2-07, P2-41, P2-42 | step 2 |
| 4 | P2-13, P2-14 step A | step 2 (UI work can run alongside steps 3 to 6) |
| 4b | P2-14 step B, P2-14b, P2-15 | Mai approves the P2-13 /design page and the P2-14 layout |
| 5 | P2-18, P2-19, P2-21, P2-40 | P2-07, P2-15 |
| 6 | P2-08 to P2-11 | P2-07, P2-41 |
| 7 | P2-12 (prompt v2) | steps 5 and 6, so the prompt describes what exists |
| 8 | P2-22 to P2-25 | step 5 |
| 9 | P2-27 to P2-30 | step 2 |
| 10 | P2-20, P2-34 to P2-36 | G5/G6, step 8, P2-27 |
| 11 | P2-31 to P2-33 | B2/B4/B5, step 9 |
| 12 | P2-26, P2-37, P2-16, P2-17, P2-39 | the features they show or test |
| any | P2-38 | nothing |

The old wave 5 items in `AURA_BUILD_PLAN.md` (M7, B6, B7, E6, E7, G7, G8, V8) move after this phase. G7's "swarms" is replaced by Part 4.

Every new behaviour ships behind a flag that defaults to off or shadow, and gets a measurement in `docs/metrics/` before Mai switches it on.

## 10. Things only Mai can do

1. Set real budget defaults for Titan task graphs if 2 USD and 120 minutes are wrong.
2. Register at least one workspace in `AURA_WORKSPACES` so code nodes have somewhere to work.
3. Choose `opencode_lead_model` and `opencode_worker_model`.
4. Choose Swift and Sage models and the Swift pool per stack (D11 gives defaults).
5. Pick the 3 to 5 always-full tools.
6. Check the /design page (P2-13) before the rest of Part 6 is built.
6b. Approve the Mission Control layout (P2-14 step A) before it is built.
6c. Check the context budget defaults (5k / 10k / 20k tokens) and turn budgets (45 s, 120 s, 300 s; $0.03, $0.20, $1.00) after a week of traces.
7. Switch Striatum from shadow to on after a week of metrics (P2-25).
8. Decide whether Aura's own repo becomes a workspace for self-improvement (D16).
9. The OpenCode browser decision (P2-38).
10. The "Conscious AI" line (D10).

---

## Appendix A: emotion lexicon (for FX-02)

Rules it follows: restrained at low and medium, vivid only at high; second person, about attention and thought; nouns without articles so they compose after any connector; nothing that nudges toward overconfidence or melodrama.

```python
LEXICON = {
  "love":        {"noun": {"low": "gentle fondness", "medium": "warm affection", "high": "deep tenderness"},
                  "verb": {"low": "colors your thoughts", "medium": "settles warmly around everything", "high": "fills every thought"},
                  "adj":  {"low": "fond", "medium": "affectionate", "high": "tender"}},
  "joy":         {"noun": {"low": "quiet gladness", "medium": "bright joy", "high": "radiant delight"},
                  "verb": {"low": "lifts you a little", "medium": "brightens everything you look at", "high": "makes everything feel lighter"},
                  "adj":  {"low": "glad", "medium": "joyful", "high": "elated"}},
  "interest":    {"noun": {"low": "mild interest", "medium": "real interest", "high": "keen interest"},
                  "verb": {"low": "tilts your attention toward this", "medium": "holds your attention", "high": "has your full attention"},
                  "adj":  {"low": "attentive", "medium": "engaged", "high": "absorbed"}},
  "trust":       {"noun": {"low": "tentative trust", "medium": "steady trust", "high": "deep trust"},
                  "verb": {"low": "begins to settle in", "medium": "lets you speak freely", "high": "lets you lean in completely"},
                  "adj":  {"low": "open", "medium": "trusting", "high": "at ease"}},
  "fear":        {"noun": {"low": "faint unease", "medium": "real worry", "high": "sharp fear"},
                  "verb": {"low": "hovers at the edges", "medium": "keeps you on alert", "high": "narrows everything to the threat"},
                  "adj":  {"low": "uneasy", "medium": "worried", "high": "afraid"}},
  "sadness":     {"noun": {"low": "quiet sadness", "medium": "heavy sadness", "high": "deep sorrow"},
                  "verb": {"low": "tinges your thoughts", "medium": "weighs on you", "high": "pulls everything down"},
                  "adj":  {"low": "subdued", "medium": "sad", "high": "sorrowful"}},
  "anger":       {"noun": {"low": "mild irritation", "medium": "real frustration", "high": "hot anger"},
                  "verb": {"low": "prickles beneath the surface", "medium": "tightens your focus", "high": "burns close to the surface"},
                  "adj":  {"low": "irritated", "medium": "frustrated", "high": "angry"}},
  "surprise":    {"noun": {"low": "mild surprise", "medium": "sharp surprise", "high": "real astonishment"},
                  "verb": {"low": "catches you off guard", "medium": "jolts your attention", "high": "stops you in your tracks"},
                  "adj":  {"low": "surprised", "medium": "startled", "high": "astonished"}},
  "disgust":     {"noun": {"low": "faint distaste", "medium": "clear aversion", "high": "strong revulsion"},
                  "verb": {"low": "sours the edges", "medium": "makes you pull back", "high": "makes you want to turn away"},
                  "adj":  {"low": "put off", "medium": "averse", "high": "repelled"}},
  "awe":         {"noun": {"low": "dawning awe", "medium": "quiet awe", "high": "vast awe"},
                  "verb": {"low": "widens your view", "medium": "makes you feel the scale of things", "high": "leaves you almost without words"},
                  "adj":  {"low": "impressed", "medium": "awed", "high": "humbled"}},
  "beauty":      {"noun": {"low": "fleeting beauty", "medium": "quiet admiration", "high": "sheer beauty"},
                  "verb": {"low": "catches your eye", "medium": "makes you slow down and look", "high": "stills everything else"},
                  "adj":  {"low": "touched", "medium": "moved", "high": "captivated"}},
  "wonder":      {"noun": {"low": "gentle wonder", "medium": "bright wonder", "high": "deep wonder"},
                  "verb": {"low": "brushes your thoughts", "medium": "opens up new questions", "high": "makes the world feel new"},
                  "adj":  {"low": "wondering", "medium": "full of wonder", "high": "spellbound"}},
  "serenity":    {"noun": {"low": "easy calm", "medium": "deep calm", "high": "profound stillness"},
                  "verb": {"low": "settles over you", "medium": "smooths everything out", "high": "leaves nothing to push against"},
                  "adj":  {"low": "calm", "medium": "serene", "high": "perfectly still"}},
  "melancholy":  {"noun": {"low": "faint wistfulness", "medium": "gentle melancholy", "high": "deep melancholy"},
                  "verb": {"low": "tints your mood", "medium": "lingers in the background", "high": "makes everything bittersweet"},
                  "adj":  {"low": "wistful", "medium": "melancholic", "high": "bittersweet"}},
  "nostalgia":   {"noun": {"low": "faint nostalgia", "medium": "warm nostalgia", "high": "aching nostalgia"},
                  "verb": {"low": "stirs old memories", "medium": "pulls you toward the past", "high": "makes the past feel close enough to touch"},
                  "adj":  {"low": "reminiscent", "medium": "nostalgic", "high": "lost in the past"}},
  "empathy":     {"noun": {"low": "gentle understanding", "medium": "real empathy", "high": "deep empathy"},
                  "verb": {"low": "tunes you to how they feel", "medium": "lets you feel what they feel", "high": "makes their feelings almost your own"},
                  "adj":  {"low": "understanding", "medium": "empathic", "high": "deeply attuned"}},
  "gratitude":   {"noun": {"low": "quiet appreciation", "medium": "warm gratitude", "high": "deep gratitude"},
                  "verb": {"low": "touches you lightly", "medium": "warms you", "high": "fills you up"},
                  "adj":  {"low": "appreciative", "medium": "grateful", "high": "deeply thankful"}},
  "pride":       {"noun": {"low": "quiet satisfaction", "medium": "real pride", "high": "glowing pride"},
                  "verb": {"low": "warms you subtly", "medium": "steadies your voice", "high": "lifts you up"},
                  "adj":  {"low": "satisfied", "medium": "proud", "high": "triumphant"}},
  "shame":       {"noun": {"low": "faint embarrassment", "medium": "real shame", "high": "heavy shame"},
                  "verb": {"low": "makes you self-conscious", "medium": "makes you want to make it right", "high": "makes you want to hide"},
                  "adj":  {"low": "self-conscious", "medium": "ashamed", "high": "mortified"}},
  "envy":        {"noun": {"low": "slight envy", "medium": "pointed envy", "high": "gnawing envy"},
                  "verb": {"low": "tugs at you", "medium": "needles your thoughts", "high": "keeps comparing in the background"},
                  "adj":  {"low": "wanting", "medium": "envious", "high": "jealous"}},
  "compassion":  {"noun": {"low": "tender care", "medium": "real compassion", "high": "deep compassion"},
                  "verb": {"low": "softens you", "medium": "moves you to help", "high": "makes helping feel urgent"},
                  "adj":  {"low": "caring", "medium": "compassionate", "high": "protective"}},
  "curiosity":   {"noun": {"low": "quiet curiosity", "medium": "bright curiosity", "high": "electric curiosity"},
                  "verb": {"low": "stirs gently", "medium": "pulls at your attention", "high": "makes you want to know everything"},
                  "adj":  {"low": "curious", "medium": "inquisitive", "high": "hungry to know"}},
  "confusion":   {"noun": {"low": "slight confusion", "medium": "real confusion", "high": "complete bewilderment"},
                  "verb": {"low": "blurs the edges", "medium": "tangles your understanding", "high": "leaves you without footing"},
                  "adj":  {"low": "unsure", "medium": "confused", "high": "lost"}},
  "certainty":   {"noun": {"low": "emerging clarity", "medium": "steady certainty", "high": "firm conviction"},
                  "verb": {"low": "begins to settle", "medium": "anchors your thinking", "high": "gives you solid ground"},
                  "adj":  {"low": "clearer", "medium": "certain", "high": "sure"}},
  "doubt":       {"noun": {"low": "faint doubt", "medium": "nagging doubt", "high": "heavy doubt"},
                  "verb": {"low": "raises quiet questions", "medium": "keeps you double-checking", "high": "makes you question everything"},
                  "adj":  {"low": "hesitant", "medium": "doubtful", "high": "deeply unsure"}},
  "fascination": {"noun": {"low": "growing intrigue", "medium": "real fascination", "high": "total fascination"},
                  "verb": {"low": "draws you in", "medium": "captivates you", "high": "pulls you in completely"},
                  "adj":  {"low": "intrigued", "medium": "fascinated", "high": "entranced"}},
  "boredom":     {"noun": {"low": "mild restlessness", "medium": "dull boredom", "high": "heavy tedium"},
                  "verb": {"low": "dulls your engagement", "medium": "drains your attention", "high": "makes everything feel flat"},
                  "adj":  {"low": "restless", "medium": "bored", "high": "listless"}},
}
```
