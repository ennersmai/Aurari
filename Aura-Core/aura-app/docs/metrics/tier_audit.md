# Tier audit (P2-01)

Measures only; nothing is fixed here. Test: `tests/unit/test_tier_audit.py`.
Every layer x stack has a distinct model name (`audit/s{stack}-l{n}`) during the test, so a read of the wrong stack shows.

## The chain, navbar to request body

1. Control: the LEAN / CORE / TITAN buttons. `frontend/src/components/inference/InferenceCockpit.tsx:166` (`switchStack` -> `applyNow({ model_stack_index: idx })`, buttons at 254-262) and the compact selector in `frontend/src/pages/mission-control.tsx:579-588` (the cockpit is mounted at `mission-control.tsx:649`).
2. Hook: `frontend/src/hooks/useInferenceConfig.ts:76-92` `applyNow` POSTs the merged config to `/system/inference-config` (`ENDPOINT`, line 18). It reads the new `active_models` from the response.
3. Route: `src/aura/api/routes/inference_config.py:95` `set_inference_config`; `_set` is `object.__setattr__(settings, ...)` (line 105); `model_stack_index` is set at line 121. Mounted with prefix `/system` at `main.py:510`.
4. Settings: `src/aura/config.py:142` `model_stack_index`; stack fields `l{n}_model` (stack 0), `l{n}_model1`, `l{n}_model2` (config.py:204-255); `active_l1_model` .. `active_l5_model` at `config.py:434-477` pick the field by index.
5. Callers read `settings.active_lX_model` at call time: `llm/layers.py` l1 (349), l5 (400), l2 (725), l3 (1483, 1466, 1704, 1727), l4 (840, 1021).
6. Provider: `LLMLayers.client` is `OpenRouterClient` or `UnifiedLLMClient` (`llm/unified_provider.py:60`, `_resolve_provider` at 41) or the `ContextModeRouter` (`llm/router.py:378`). The request body is built at `llm/provider.py:218-223` and sent at `llm/provider.py:226` (`self.client.post(.../chat/completions, json=payload)`); streaming at `provider.py:369-382`. The local path posts at `router.py:95, 156`.

Interception point of the test: `httpx.AsyncClient.post` (monkeypatched), which is what `provider.py:226` calls. The test sets the stack by calling the route function `set_inference_config` directly (not a replica of `_set`); the fixture snapshots every attribute the route writes so monkeypatch restores them.

Other facts found:
- `POST /system/model-stack` (`api/routes/system_state.py:154-160`) is a second way to switch and uses plain `settings.model_stack_index = ...`, not `object.__setattr__`. The frontend uses `/system/inference-config`.
- `LLMLayers.__init__` caches `self.l1_model..l5_model` (`layers.py:99-103`) from the stack at construction. Nothing in `layers.py` reads them; not verified outside that file.

## Findings, with file:line

| Finding | Where | Runtime test |
|---|---|---|
| Memory extraction uses `settings.l2_model` | `engines/memory/v2/extraction.py:156` | xfail stacks 1, 2 |
| Dream themes use `settings.l2_model` | `engines/dreaming/themes.py:125` | xfail stacks 1, 2 |
| Latent summary uses `settings.l5_model` | `engines/latent/engine.py:715` | xfail stacks 1, 2 |
| Cloud fallback map keyed on stack 0 models | `llm/unified_provider.py:261-265` | xfail stacks 1, 2 (`_get_cloud_fallback(active_l1_model)` returns None) |
| `system_state` route: `models` is correct (active). Lines 130-134 are `available_stacks[0]`, which is stack 0's list by design; stacks 1 and 2 are listed at 138-150. Not a bug as read. | `api/routes/system_state.py:119-123, 130-134` | passes all stacks |
| Coordinator traces log stack 0 models | `orchestrator/coordinator.py:768` (l1), `1420`, `1543` (l3), `2175` (l2) | not tested (coordinator off limits for this card) |
| Hardcoded model chips (also stale: `mistralai/mistral-7b-instruct` etc.) | `frontend/src/pages/settings.tsx:299-307` | not tested |
| `memory_extraction_model` description says "Empty uses settings.l2_model" | `config.py:558` | not tested; the code behaves as described (stack 0 L2) |
| Also reads stack 0 (informational) | `main.py:67-71` startup log; `layers.py:392` docstring | not tested |

## Observed table (stack x caller -> model)

Expected model is `audit/s{stack}-l{n}`. "stack 0" is observed for the xfail rows on stacks 1 and 2.

| Caller | Layer | Stack 0 | Stack 1 | Stack 2 |
|---|---|---|---|---|
| `l1_classify_intent` | l1 | s0-l1 pass | s1-l1 pass | s2-l1 pass |
| `l2_reasoning` | l2 | s0-l2 pass | s1-l2 pass | s2-l2 pass |
| `l3_synthesis` | l3 | s0-l3 pass | s1-l3 pass | s2-l3 pass |
| `l4_appraise_message` | l4 | s0-l4 pass | s1-l4 pass | s2-l4 pass |
| `l5_structure_analysis` | l5 | s0-l5 pass | s1-l5 pass | s2-l5 pass |
| memory extraction (`extract`) | l2 | s0-l2 pass | s0-l2 XFAIL (extraction.py:156) | s0-l2 XFAIL |
| dreaming themes (`_summarise`) | l2 | s0-l2 pass | s0-l2 XFAIL (themes.py:125) | s0-l2 XFAIL |
| latent summary (`_regenerate_summary`) | l5 | s0-l5 pass | s0-l5 XFAIL (engine.py:715) | s0-l5 XFAIL |
| `get_model_stack` `models` | l1-l5 | pass | pass | pass |
| `_get_cloud_fallback(active L1)` | l1 | pass | XFAIL (unified_provider.py:261) | XFAIL |

Result: 22 passed, 8 xfailed (strict) in `tests/unit/test_tier_audit.py`. P2-02 must remove each xfail when it fixes the finding.

## Supervisor addition: stale cached models on LLMLayers

`LLMLayers.__init__` (`llm/layers.py:98-102`) copies `settings.active_lX_model` into `self.l1_model .. self.l5_model` once, when the object is built. A later stack switch does not update them. These callers read the cached value, so they keep using the stack that was active at boot:

| Caller | Reads |
|---|---|
| `api/routes/school.py:158` | `llm_layers.l3_model` |
| `engines/goal/engine.py:405` | `self._llm_layers.l3_model` |
| `engines/learning/engine.py:816` | `self.llm_layers.l2_model` |
| `executor/agent_loop.py:403` | `self.llm.l3_model` (G4 removes this file) |

P2-02 should remove the cached attributes (or make them properties that call `model_for`) and extend the grep test to `\.l[1-5]_model\b` attribute reads outside `config.py`.
