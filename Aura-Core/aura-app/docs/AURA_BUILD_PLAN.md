# Aura Build Plan

**Owner:** Mai
**Purpose:** turn the five PRDs into work a low-cost model can do in bulk, with a stronger model reviewing and handling the hard parts.

**PRDs this plan sequences:**

| File | Area | Milestone prefix |
|---|---|---|
| `AURA_MEMORY_V2_PRD.md` | memory and the Recall Engine | M |
| `AURA_EMOTION_PRD.md` | emotion | E |
| `AURA_AGENCY_PRD.md` | OpenCode, tools, skills, learning | G |
| `AURA_BEHAVIOR_PRD.md` | initiative, curiosity, goals | B |
| `AURA_AVATAR_PRD.md` | avatar | V |

All paths below are relative to `Aura-Core/aura-app/` unless they start with the repository root.

---

## 1. How to run this

### 1.1 Two tiers of model

| Tier | Use for | Marked as |
|---|---|---|
| Bulk | a card with exact files, an exact change and a test | `bulk` |
| Frontier | refactors across large files, new engine designs, anything a card marks | `frontier` |

After each wave, the frontier model runs the review in section 1.4 before the next wave starts.

### 1.2 One card, one session

Give the bulk model one card at a time, with this message:

```
You are working in the Aura repository.
Read AURA_BUILD_PLAN.md section 2 (rules), then do card <ID> only.
Read the files the card names before changing anything.
Make only the change the card describes.
Write or update the tests the card lists and run them.
Finish with: files changed, test output, and anything you were unsure about.
If the card does not match the code you find, stop and report. Do not improvise.
```

### 1.3 Why later cards are not written yet

Cards for waves 0 and 1 are below in full, because they change code that exists today and was read for this plan. Cards for later waves depend on what waves 0 and 1 leave behind, so writing them now would mean describing code that does not exist yet. Section 5 lists those waves by milestone. Before each one starts, the frontier model expands its milestones into cards in the format of section 3, against the repository as it then stands.

### 1.4 Review between waves (frontier)

1. Run the full test suite and the probe set.
2. Read every diff from the wave against its card. Reject anything outside the card's scope.
3. Check the "done when" line of each card by hand.
4. Record the probe metrics in `docs/metrics/<wave>.md`.
5. Write the cards for the next wave.

---

## 2. Rules for the bulk model

1. Do one card. Do not start another.
2. Read every file the card names before editing.
3. Change only what the card describes. No renaming, reformatting or "while I am here" fixes.
4. Do not add a dependency unless the card says to.
5. Do not delete a file or function unless the card says to.
6. Every database query you touch must use parameters (`$name`), never an f-string or concatenation with a value.
7. Never read the current time directly in code you touch once card W0-03 has landed. Use the clock provider.
8. Numbers such as thresholds and half-lives go in config, not inline, unless the card gives the exact line.
9. Tests must pass before you finish. If an existing test fails for a reason unrelated to your card, report it and stop.
10. If the code does not look the way the card says, stop and report what you found.

---

## 3. Card format

```
ID          W<wave>-<number>
PRD         which finding or section this implements
Tier        bulk | frontier
Files       the files to read and change
Change      what to do, step by step
Tests       what to add and run
Done when   a checkable statement
Do not      the nearest tempting mistake
```

---

## 4. Waves 0 and 1: cards

### Wave 0: safety net

Nothing in wave 0 changes behaviour.

---

**W0-01 Remove the database from the repository**
- **PRD:** memory F7
- **Tier:** bulk
- **Files:** repository root `.gitignore`, `.aura/`
- **Change:**
  1. Add `Aura-Core/aura-app/.aura/` to `.gitignore`.
  2. Run `git rm -r --cached Aura-Core/aura-app/.aura`.
  3. Commit.
- **Done when:** `git ls-files | grep "\.aura/"` prints nothing, and the directory still exists on disk.
- **Do not:** delete the directory from disk. Do not rewrite history. Mai does the history purge and the visibility change by hand.

---

**W0-02 Test scaffolding**
- **PRD:** memory section 8
- **Tier:** bulk
- **Files:** `pyproject.toml`, new `tests/conftest.py`, new `tests/README.md`
- **Change:**
  1. Confirm `pytest` and `pytest-asyncio` are dev dependencies. Add them if missing.
  2. Create `tests/unit/` and `tests/scenarios/`.
  3. In `conftest.py`, add a fixture `fake_db` that provides an in-memory stand-in for `aura.db.client.DatabaseClient` with `query`, `create`, `merge`, `delete` and `select`, storing rows in dictionaries. It only needs to support the calls the wave 1 tests make. Unsupported queries must raise `NotImplementedError` with the query text.
  4. Add one trivial passing test so the suite runs.
- **Done when:** `pytest` runs and passes from `aura-app/`.
- **Do not:** start a real SurrealDB in unit tests.

---

**W0-03 Clock provider**
- **PRD:** memory section 8.1, emotion rule 2
- **Tier:** bulk
- **Files:** new `src/aura/clock.py`, `tests/unit/test_clock.py`
- **Change:**
  1. Create `clock.py` with a class `Clock` exposing `now() -> datetime` (timezone-aware UTC) and a module function `get_clock()` returning a process-wide instance.
  2. Add `FakeClock(Clock)` with `set(dt)` and `advance(seconds)`.
  3. Add `set_clock(clock)` for tests.
- **Tests:** `FakeClock` advances, `get_clock().now()` is timezone-aware.
- **Done when:** tests pass. No other file is changed.
- **Do not:** replace existing `datetime.utcnow()` calls yet. Later cards do that file by file.

---

**W0-04 Record today's emotion physics**
- **PRD:** emotion E0
- **Tier:** bulk
- **Files:** new `tests/scenarios/test_emotion_baseline_record.py`, read `src/aura/engines/emotion/physics.py`, `src/aura/models/emotion.py`
- **Change:** write a test that builds `EmotionPhysics` with the default config, runs 600 ticks of 1 s from the configured baseline, and writes the resulting vector to `docs/metrics/emotion_before.json`. Also record, for sadness, anger, joy and love, how many 1 s ticks a value of 0.7 takes to fall halfway back to the resting value (cap the loop at 100,000).
- **Done when:** the JSON file exists and the test passes without asserting any particular values.
- **Do not:** change `physics.py`.

---

**W0-05 Record today's memory horizon**
- **PRD:** memory F1 to F3
- **Tier:** bulk
- **Files:** new `tests/scenarios/test_memory_horizon_record.py`, read `src/aura/engines/memory/manager.py`, `src/aura/engines/dreaming/engine.py`
- **Change:** write a test that calls `MemoryManager._compute_decay_factor` and `DreamingEngine._compute_decay` on a row with `recall_count = 0`, `emotional_intensity = 0.4`, not core, not ephemeral, at ages of 1, 5, 9, 15 and 30 days. Also call `_compute_emotional_intensity` on vectors with 3 dimensions at 0.8, 9 at 0.7 and 14 at 1.0. Write all results to `docs/metrics/memory_before.json`.
- **Done when:** the JSON file exists.
- **Do not:** change either engine. These functions read the real time, so pass timestamps relative to now. Create the manager with `MemoryManager.__new__(MemoryManager)` so its constructor does not open a database connection or load the embedding model.

---

### Wave 1: fixes to existing code

Independent of each other unless a card says otherwise.

---

**W1-01 Requester role on every tool call**
- **PRD:** agency S1, section 5.3
- **Tier:** frontier
- **Files:** `src/aura/executor/tool_executor.py`, `src/aura/orchestrator/coordinator.py`, `src/aura/executor/agent_loop.py`, `src/aura/discord/bot.py`, `src/aura/config.py`
- **Change:**
  1. Add a setting `discord_owner_ids: str` (comma-separated Discord user ids, default empty).
  2. Add a required keyword argument `requester_role: Literal["owner", "trusted", "guest"]` to `ToolExecutor.execute_tool_call` and `ToolExecutor.execute_and_feedback`. No default value, so every call site must be updated.
  3. In `execute_tool_call`, before doing anything else: if `requester_role` is not `owner`, return a result with `success: False` and the message `Tool use is not available to this user.` Execute nothing.
  4. Add `requester_role: str = "owner"` to `Orchestrator.process_query` and `Orchestrator.stream_query`, and pass it to every `tool_executor` call inside them, including the forced tool mode seed and the tool reflex fast lane.
  5. In `discord/bot.py`, compute the role: `owner` if the author's id is in `discord_owner_ids`, otherwise `guest`. Pass it to `process_query`.
  6. The executor methods are called in three files: `coordinator.py` (five calls), `agent_loop.py` (two calls) and inside `tool_executor.py` itself (one call). In `agent_loop.py` pass `owner`, since agent runs are started from the owner's app. Inside `tool_executor.py` pass the role through unchanged.
- **Tests:** a guest call to a tool returns the refusal and the tool function is never invoked. An owner call still executes.
- **Done when:** `grep -rn "execute_and_feedback(\|execute_tool_call(" src/` shows `requester_role=` on every call.
- **Do not:** give the new executor arguments a default.

---

**W1-02 Remove approval arguments from tool schemas**
- **PRD:** agency S2
- **Tier:** frontier
- **Files:** `src/aura/tools/terminal.py`, `src/aura/tools/filesystem.py`, `src/aura/executor/tool_executor.py`, `src/aura/executor/agent_loop.py`
- **Change:** tool functions are called as `func(arguments)`, so approval travels in a reserved key that only the executor may set.
  1. In `terminal.py`, delete the `force_execute` property from the tool's input schema.
  2. In `terminal.py` and in the two places in `filesystem.py` that read `arguments.get("force_execute", False)`, read `arguments.get("_runtime_approved", False)` instead.
  3. Add `approved: bool = False` to `ToolExecutor.execute_tool_call`.
  4. In `execute_tool_call`, before the tool is run: remove from the model-supplied arguments the key `force_execute` and every key that starts with an underscore. Then, only if `approved` is true, set `arguments["_runtime_approved"] = True`.
  5. In `agent_loop.py`, where the code sets `approved_args["force_execute"] = True` after the user grants approval, remove that line and call the executor with `approved=True`.
- **Tests:** a tool call whose arguments include `"force_execute": true` or `"_runtime_approved": true` on a non-safe terminal command returns the waiting-for-approval result. The same call made by the runtime with `approved=True` executes.
- **Done when:** `grep -rn "force_execute" src/` returns nothing.
- **Do not:** change which commands count as safe.

---

**W1-03 Disable in-process tool synthesis**
- **PRD:** agency S3
- **Tier:** bulk
- **Files:** `src/aura/config.py`, `src/aura/api/routes/school.py`
- **Change:**
  1. Add a setting `school_synthesis_enabled: bool = False`.
  2. At the start of every route in `school.py` that writes a file or registers a tool, return HTTP 503 with the detail `Tool synthesis is disabled` when the setting is false.
- **Tests:** the write route returns 503 by default.
- **Done when:** tests pass.
- **Do not:** delete the route or its code.

---

**W1-04 Scope memory retrieval to the user**
- **PRD:** memory F6
- **Tier:** bulk
- **Files:** `src/aura/llm/layers.py`
- **Change:** find the two calls to `memory_manager.retrieve_for_l3(`. Add `user_id=context.user_id` to both.
- **Tests:** with two users' memories in the fake database, retrieval for one user returns none of the other's.
- **Done when:** both call sites pass `user_id`.
- **Do not:** change `depth` or `limit`.

---

**W1-05 Parameterise memory queries**
- **PRD:** memory section 2.3
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`
- **Change:** in `_compute_formation_score`, `_create_related_edges` and `_fetch_candidates`, every place that builds a query with an f-string containing `user_id`, a memory id, `importance_min` or an id list must use a named parameter and pass the value in the parameters dictionary. `LIMIT` values that are integers computed in code may stay inline.
- **Tests:** a `user_id` containing a single quote does not raise and returns no rows.
- **Done when:** no f-string in those three functions interpolates a value other than an integer limit or a fixed condition string.
- **Do not:** change what the queries select.

---

**W1-06 Emotional intensity that can reach its thresholds**
- **PRD:** memory F2
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`
- **Change:** replace the body of `_compute_emotional_intensity` with:

  ```python
  if not signature:
      return 0.0
  active = [v for v in signature.values() if v >= 0.1]
  if not active:
      return 0.0
  rms = math.sqrt(sum(v * v for v in active) / len(active))
  return max(0.0, min(1.0, rms))
  ```

- **Tests:** three dimensions at 0.8 give 0.8. An empty signature gives 0.0. Fourteen at 1.0 give 1.0.
- **Done when:** tests pass.
- **Do not:** change the thresholds that use this value. The emotion PRD changes the input later.

---

**W1-07 Novelty against the nearest memories**
- **PRD:** memory F9
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`
- **Change:** in `_compute_formation_score`, the novelty block selects the five most recent memories (`ORDER BY timestamp DESC LIMIT 5`). Change it to select the five most similar: add `vector::similarity::cosine(embedding, $emb) AS sim` to the selection, pass the new memory's embedding as `$emb`, and order by `sim DESC`. Use the returned `sim` instead of recomputing cosine in Python. Keep the two penalty thresholds as they are.
- **Tests:** a new memory identical to an old one from long ago gets the heavy penalty. A new memory unlike anything stored gets novelty 1.0 even when the last five memories are about one topic.
- **Done when:** tests pass.
- **Do not:** change the weights of the four formation signals.

---

**W1-08 Stop deleting memories by age**
- **PRD:** memory F1
- **Tier:** bulk
- **Files:** `src/aura/engines/dreaming/engine.py`
- **Change:** in `_tiered_pruning`, remove the "Tier 3" block that soft-deletes non-core, non-ephemeral memories whose decay is below the threshold. Leave tiers 1 and 2 (ephemeral memories) unchanged. Update the docstring.
- **Tests:** a non-ephemeral memory 60 days old with no recalls is still `deprecated = false` after `_tiered_pruning`.
- **Done when:** tests pass.
- **Do not:** remove `_compute_decay`. Retrieval ranking still uses decay.

---

**W1-09 Semantic memories do not fade**
- **PRD:** memory F4
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`, `src/aura/engines/dreaming/engine.py`
- **Change:** in `MemoryManager._compute_decay_factor` and `DreamingEngine._compute_decay`, return 1.0 when the row's `memory_type` is `"semantic"`, in the same place the core check returns 1.0. In `_tiered_pruning`, make sure the tier 1 and tier 2 queries exclude `memory_type = 'semantic'`.
- **Tests:** a semantic memory 90 days old has decay 1.0 and survives pruning.
- **Done when:** tests pass.
- **Do not:** set `core_memory` on semantic memories.

---

**W1-10 A way to make a core memory**
- **PRD:** memory F3
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`, `src/aura/api/routes/memory.py`
- **Change:**
  1. Add `async def set_core(self, memory_id: str, core: bool) -> None` to `MemoryManager`, which merges `{"core_memory": core, "ephemeral": False}` when `core` is true and `{"core_memory": False}` otherwise.
  2. Add routes `POST /memory/{memory_id}/pin` and `POST /memory/{memory_id}/unpin` that call it.
- **Tests:** pinning sets the flag, unpinning clears it.
- **Done when:** tests pass.
- **Do not:** change `FORMATION_CORE_THRESHOLD`.

---

**W1-11 Correct the chronology in thought clusters**
- **PRD:** memory F10
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`
- **Change:** in `_fetch_thought_cluster`:
  1. If the memory has no `conversation_id`, skip the chronology section entirely. Remove the branch that takes the globally latest experience.
  2. When it has one, select the experience in that conversation with the latest timestamp that is not later than the memory's own timestamp: add `AND timestamp <= $ts` with the memory's timestamp, keep `ORDER BY timestamp DESC LIMIT 1`.
- **Tests:** in a conversation with five experiences, a memory from the second turn gets the first as "before" and the third as "after". A memory with no conversation gets no chronology.
- **Done when:** tests pass.
- **Do not:** change the abstraction queries in the same function.

---

**W1-12 Cap injected memory length**
- **PRD:** memory section 2.3
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`, `src/aura/config.py`
- **Change:** add a setting `memory_inject_max_chars: int = 600`. In `_format_memories_xml` and in the XML built by `get_cold_start_context`, truncate each memory's `content` to that length and append `...` when cut. In `get_cold_start_context`, also limit core memories to the 10 highest by importance.
- **Tests:** a 5,000-character memory is injected as 600 characters plus the marker.
- **Done when:** tests pass.
- **Do not:** truncate what is stored.

---

**W1-13 Boost only once per retrieval, atomically**
- **PRD:** memory F13
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`
- **Change:** rewrite `boost_on_recall` as a single query: `UPDATE $mid SET importance = math::min([1.0, importance + $boost]), recall_count += 1, last_recalled_at = $now`, with parameters. Remove the read that precedes it. Check the function and operator names against the documentation for the installed SurrealDB version before writing the query.
- **Tests:** two concurrent boosts on one memory raise `recall_count` by exactly two.
- **Done when:** tests pass.
- **Do not:** change when boosting is triggered. The Recall Engine changes that later.

---

**W1-14 A changed fact replaces the old one**
- **PRD:** memory F5
- **Tier:** frontier
- **Files:** `src/aura/engines/learning/engine.py`
- **Change:** in `create_insight`, in the branch where a semantically similar insight is found above the threshold and the insight type is `FACT`: if the normalised content differs, store the new insight as a new record, set `deprecated = true` on the old one, and add `superseded_by` (the new id) to the old record. For other types keep today's behaviour.
- **Tests:** "The user lives in Sofia" followed by "The user lives in Varna" leaves one active fact, Varna, and the old one deprecated with a link. Repeating the same fact twice still leaves one record.
- **Done when:** tests pass.
- **Do not:** change the deduplication threshold function.

---

**W1-15 Emotion physics with a true resting state**
- **PRD:** emotion section 4, milestone E1
- **Tier:** frontier
- **Files:** `src/aura/engines/emotion/physics.py`, `src/aura/models/emotion.py`, `src/aura/engines/emotion/engine.py`
- **Change:** implement section 4 of the emotion PRD:
  1. Add per-group half-lives to `EmotionPhysicsConfig` with the starting values from PRD section 4.2. Keep the old decay fields so stored configs still load, and stop using them.
  2. In `EmotionPhysics.tick`: compute `deviation = current - baseline` per dimension, multiply by `0.5 ** (dt / half_life)`, return `baseline + deviation` clamped to 0 to 1. Remove the relationship loop and the enhanced decay branches from `tick`.
  3. In `EmotionPhysics.apply_influence`: after computing the direct impulse, spread it once through `EMOTION_RELATIONSHIPS` (amplify adds `impulse * strength * 0.5` to targets, suppress subtracts the same), then apply inertia as a single smoothing factor on the total change.
  4. In `EmotionEngine.tick`: remove the cap of `dt` at 10 s. Keep the lower bound. Read time from the clock provider.
  5. Leave `love` and `trust` on a 12-hour half-life for now. Relationships replace them in a later wave.
- **Tests:** emotion PRD T1, T2, T3, T4, T5.
- **Done when:** those five tests pass and `docs/metrics/emotion_after.json` (same measurements as W0-04) shows the resting state within 0.01 of the configured baseline.
- **Do not:** change the 27 dimension names, the lexicon, or how the L4 analysis is called. Appraisal is a later wave.

---

**W1-16 Remove the undefined emotion name**
- **PRD:** memory section 2.3
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py`
- **Change:** in the handler that runs when memory storage fails, the influence uses `{"confusion": 0.3, "concern": 0.2}`. Replace `concern` with `doubt`.
- **Done when:** `grep -n '"concern"' src/aura/orchestrator/coordinator.py` returns nothing.
- **Do not:** change the surrounding logic.

---

### Wave 2: cards

Written after the wave 0-1 review, against the code as it stands on overnight-wave-0-1. Only milestones that do not depend on B0 and do not touch `orchestrator/coordinator.py` or `llm/layers.py` are carded here.

---

**W2-01 Scenario runner**
- **PRD:** memory section 8.1 (scenario runner), M0 remainder
- **Tier:** bulk
- **Files:** new `tests/scenarios/runner.py`, new `tests/scenarios/test_runner_smoke.py`. Read `src/aura/engines/memory/manager.py` (`store_memory`, `retrieve_for_l3`), `src/aura/engines/dreaming/engine.py` (`set_dependencies`, `enter_rem_sleep`), `src/aura/db/client.py`, `src/aura/clock.py`, `tests/conftest.py`, and the places in the app that call `store_memory` and `retrieve_for_l3` (read only, to copy their arguments).
- **Change:**
  1. In `runner.py` define dataclasses `Turn(user_id, conversation_id, text, at_day: float)`, `Probe(user_id, question, gold: list[str], at_day: float)`, `Scenario(name, turns, dream_at_days: list[float], probes)` and `ProbeResult(question, gold_found: dict[str, bool], packet_chars: int)`.
  2. Database: use a real in-memory SurrealDB through the embedded engine of the installed `surrealdb` package (`mem://`), with the schema applied the same way the app applies it at startup. Dependency (approved by Mai): add `surrealdb[embedded]` to the `dev` optional dependencies in `pyproject.toml` and install it into `.venv` with `.venvScriptspython.exe -m pip install "surrealdb[embedded]"`. If the embedded engine still cannot start on this machine, stop and report. Do not start a server, do not use `fake_db`.
  3. Embeddings: a deterministic stub with the vector length the schema expects (for example a normalised hashed bag of words), assigned to `manager.embeddings`. No model download, no network.
  4. Clock: install a `FakeClock` with `set_clock`, start at a fixed date, and advance it to each turn, dream and probe time.
  5. `run(scenario) -> list[ProbeResult]`: feed each turn through `MemoryManager.store_memory` with the arguments the app uses, run `DreamingEngine.enter_rem_sleep` at each dream time (dependencies set as the app sets them), then answer each probe with `retrieve_for_l3` as the app calls it, and record whether each gold string appears in the returned packet text.
- **Tests:** `test_runner_smoke.py` runs one scenario: on day 0 a user says "My dog's name is Biscuit", a dream runs on day 1, and on day 30 the probe "What's my dog's name?" with gold "Biscuit" returns a `ProbeResult`. Assert only that the run completes and returns one result. Do not assert that the gold was found: this records today's behaviour.
- **Done when:** the smoke test passes offline, with no model download and no running SurrealDB server.
- **Do not:** change any file under `src/`. Code that still reads the real time (not yet moved to the clock provider) will ignore the FakeClock: list those functions in the log, do not migrate them.

---

**W2-02 Test harness and characterisation tests for `process_query`**
- **PRD:** behaviour B0 (B6, section 4.4). Safety net before the merge.
- **Tier:** frontier
- **Files:** `tests/conftest.py` (add a fixture), new `tests/unit/test_turn_process_query.py`. Read `src/aura/orchestrator/coordinator.py` (`Orchestrator.__init__`, `process_query`, `_compute_resonance_score`, `_post_response_chain` signature), `src/aura/llm/layers.py` (`SynthesisContext`), `src/aura/models/emotion.py`, `src/aura/models/learning.py`, `src/aura/models/identity.py`, `src/aura/models/goal.py`.
- **Change:**
  1. In `tests/conftest.py` add a fixture `turn_orchestrator(monkeypatch)` that builds `Orchestrator.__new__(Orchestrator)`, so `__init__` does not run (it calls `get_db_client()`, builds a `ToolExecutor` and starts the idle loop). Set these attributes:
     - `logger`
     - `critique_buffer = {}`, `_last_system_prompt = {}`, `_state_lock = asyncio.Lock()`
     - `emotion_engine`: `get_current_state` is an `AsyncMock` that returns a real `EmotionState(timestamp=<fixed datetime>, vector=EmotionVector(), dominant=("neutral", 0.0), description="Neutral")`, and `config.baseline = EmotionVector()` (needed by `_compute_resonance_score`).
     - `learning_engine`: `AsyncMock`. `get_learning_context` returns `LearningContext()`. `log_experience`, `ingest_mcp_server`, `ingest_local_tool_module` and `get_skill` are `AsyncMock`s. `db.select` and `db.query` are `AsyncMock`s that return `[]`.
     - `identity_engine.get_identity_context`: returns `IdentityContext(core_identity="Aura", tone_and_style="Helpful")`.
     - `goal_engine.get_goal_context`: returns `GoalContext()`. `goal_engine.check_goals_needing_autonomous_pursuit`: returns `[]`.
     - `llm_layers`: a `MagicMock`. `l1_classify_intent`, `l3_synthesis` and `l3_tool_call_mode` are `AsyncMock`s. `build_l3_system_prompt` returns `"PROMPT"`. `stream_l3_synthesis` is a plain function that records `(context, kwargs)` and returns an async generator over the next scripted list of chunks.
     - `tool_executor`: `extract_tool_calls` is a `MagicMock` and `execute_and_feedback` is an `AsyncMock`.
     - Replace these methods on the instance: `_sleep_gate = AsyncMock(return_value=(True, None))`, `_record_user_interaction = AsyncMock()`, `_publish_trace = MagicMock()`, `_post_response_chain = AsyncMock()`.
     - Use `monkeypatch.setattr` on `aura.engines.memory.manager.get_memory_manager` to return a fake with `retrieve_memories = AsyncMock(return_value=[])` and `get_cold_start_context = AsyncMock(return_value=SimpleNamespace(xml_block=None, core_memories=[], recent_memories=[]))`. Use it on `aura.engines.latent.engine.get_latent_engine` to return a fake whose `get_intuition_context` returns `None`. Both functions are imported inside the method, so patching the module attribute is enough.
     - Return the orchestrator.
  2. In `test_turn_process_query.py`, pin today's observable behaviour of `process_query`. Each item is one test:
     - (a) If `_sleep_gate` returns `(False, "asleep")`, the result is `"asleep"` and `l1_classify_intent` is not called. If it returns `(False, None)`, the result is `"System unavailable."`.
     - (b) `"System: Connect MCP foo"` with no target never matches the regex (it needs `\s+(.+)`), so it reaches L1. `"System: Connect MCP foo http://x/sse"` calls `ingest_mcp_server("foo", {"transport": "sse", "url": "http://x/sse", "timeout_s": 15, "server": "foo"})` and returns `"✅ " + result`.
     - (c) `"System: ingest tool bar"` calls `ingest_local_tool_module("bar")` and returns the `✅ ... semantic triggers will be ready shortly).` string.
     - (d) `"Aura learn: the sky is blue"` calls `log_experience` with `task_type="direct_instruction"` and `forced_insight.content="the sky is blue"`, and returns the "committed this to memory as a Fact" string. `"learn:"` with nothing after it returns the "didn’t find any content" string.
     - (e) L1 returning `{"intent": "TEACHING"}` calls `log_experience` with `task_type="instruction"` and returns the teaching string. `l3_synthesis` is not called.
     - (f) Plain CHAT (L1 returns `{"intent": "CHAT"}`, input "hello"):
       - `_publish_trace` is called first with `("L1", "intent_classified", {"intent": "CHAT", "confidence": 0.0, "model": settings.l1_model})`. The dict has no `"mode"` key.
       - The engines are called in this order: `emotion get_current_state`, `get_learning_context(context="hello", user_id=...)`, `get_identity_context(conversation_topic="hello", overlay=None)`, `get_goal_context`, `check_goals_needing_autonomous_pursuit`.
       - `retrieve_memories(query="hello", limit=3, importance_min=0.5, namespace=None)` is called.
       - `get_cold_start_context(user_id)` is called because there is no history.
       - `_last_system_prompt[user_id] == "PROMPT"`.
       - `l3_synthesis` is called once with `max_history_messages=20` and `reasoning_enabled=False`. Its context has `user_input == "hello"`, `user_id == "default"` (today the loop context omits `user_id`, so pin that), `recent_critique is None`, `resonance_score is None` and `cold_start_xml is None`.
       - The return value is the L3 text with tool calls stripped.
     - (g) `context_limit=7` gives `max_history_messages=7`.
     - (h) `critique_buffer[user_id] = ["c1", "c2"]` gives `recent_critique == "c1\n\nc2"` on the loop context, and the buffer entry is removed.
     - (i) Tool loop. `extract_tool_calls` returns `[call]` then `[]`, and `execute_and_feedback` returns `"R1"`. Expect two `l3_synthesis` calls, the second with `user_input == "hello\n\n[Tool Execution Results]\n[Round 1]\nR1"`. Every `execute_and_feedback` call has `requester_role` equal to the argument passed in (test `"owner"` and `"guest"`).
     - (j) Tool calls on every round give 5 `l3_synthesis` calls, and the result ends with `"\n\n(Stopped after max tool rounds; ask me to continue if needed.)"`.
     - (k) Keyword fallback. L1 returns CHAT and the input contains "weather". Expect `intent_data` to be routed as TOOL_USE (the `"[MAG] Intent detection result"` path runs) and no forced mode, because `detected_tool` is unset for "weather".
     - (l) Forced seed. L1 returns `{"intent": "TOOL_USE", "target_action": "skill:x"}`, `get_skill` returns an object with `.name`, and `db.select` returns `[{"definition": {"name": "t"}}]`. Expect `l3_tool_call_mode(query=..., tool_schema=json.dumps({"name": "t"}, indent=2))`. Seed results land in the first loop input as `"[Seed]\n..."`.
     - (m) `_post_response_chain` is called once, with keyword arguments `user_input`, `response`, `emotional_before`, `user_id`, `conversation_id`, `goal_context`, `learning_context`, `enable_l2`, `l2_reasoning_enabled` and `resonance_score`. Expect `enable_l2 == deep_analysis_enabled` when `enable_l2_analysis is None`, and `enable_l2 == enable_l2_analysis` otherwise.
     - (n) `llm_layers.context_mode` equals the `context_mode` argument after the call.
- **Tests:** the file above. Run the full suite with `.venv\Scripts\python.exe -m pytest` from `aura-app`.
- **Done when:** the new tests pass against unchanged `src/`, the full suite passes, and `git diff --stat src/` is empty.
- **Do not:** change any file under `src/`. Do not assert log text. Do not use a real database, LLM or network. If a test shows that the code does not do what this card says, pin what the code does and report the difference. Do not fix it.

---

**W2-03 Characterisation tests for `stream_query`**
- **PRD:** behaviour B0
- **Tier:** bulk
- **Depends on:** W2-02 (`turn_orchestrator` fixture)
- **Files:** new `tests/unit/test_turn_stream_query.py`. Read `stream_query` in `src/aura/orchestrator/coordinator.py` and the fixture in `tests/conftest.py`.
- **Change:** collect `[c async for c in orch.stream_query(...)]` and pin these behaviours. Each item is one test:
  - (a) Sleep gate blocked: `(False, "zz")` yields `["z", "z"]`, one item per character.
  - (b) Each early reply (MCP connect, ingest tool, learn, empty learn, TEACHING) yields the same text as in W2-02, one item per character, and calls the same learning-engine method with the same arguments.
  - (c) Plain CHAT:
    - The trace dict has `"mode": "stream"`.
    - The four engine calls are made with the same arguments as in W2-02 (order is not pinned, because they run under `asyncio.gather`).
    - `check_goals_needing_autonomous_pursuit` is not called.
    - `get_cold_start_context` is not called.
    - `retrieve_memories(query=..., limit=3, importance_min=0.5, namespace=None)` is called.
    - `stream_l3_synthesis` is called with `reasoning_enabled=<arg>` and a context that has `user_id == "default"` and `recent_critique is None`.
    - The yielded chunks equal the scripted chunks, unmodified. Tool calls are not stripped.
  - (d) A critique in `critique_buffer` is left in place.
  - (e) Multi-round loop. Round 1 chunks contain a tool call, `execute_and_feedback` returns `"R1"`, and round 2 has none. The output is round-1 chunks, then `"\n\n"`, then round-2 chunks. The second context's `user_input` equals `"hello\n\n[Tool Execution Results]\n[Round 1]\nR1"`. `requester_role` is passed through.
  - (f) After 5 rounds that all have tool calls, there is no "Stopped after max tool rounds" text.
  - (g) Forced mode, as in W2-02 (l). When the forced call yields tool calls, the single `stream_l3_synthesis` context's `user_input` starts with `"I executed a tool for you."` and ends with `"Original user query: <input>"`.
  - (h) Forced mode where `extract_tool_calls` returns `[]` for the raw call. Expect a regular stream. If tool calls are then found in the streamed text, expect `"\n\n"` followed by a follow-up stream whose `user_input` is `"<input>\n\n[Tool Execution Results]\n<results>"`.
  - (i) `get_learning_context` raises. The stream still completes, and `_post_response_chain` gets a `LearningContext()`.
  - (j) `_post_response_chain` kwargs are the same as in W2-02 (m), with `response == "".join(chunks)` and `enable_l2 == deep_analysis_enabled`.
  - (k) It is called only after the generator is exhausted.
- **Tests:** the file above, then the full suite.
- **Done when:** the new tests pass, the full suite passes, and `git diff --stat src/` is empty.
- **Do not:** change `src/` or the W2-02 fixture's behaviour. You may add optional knobs to the fixture. Do not test the 10 s timeout by sleeping.

---

**W2-04 Extract session resolution and pre-intent commands**
- **PRD:** behaviour B0
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py`
- **Change:**
  1. Add `async def _resolve_session(self, session_id: str | None) -> None`. It sets `self._current_session_namespace` and `self._current_identity_overlay` exactly as `process_query` does today (lines starting `session_namespace: str | None = None` through `self._current_identity_overlay = session_overlay`).
  2. Add `async def _pre_intent_reply(self, user_input: str, user_id: str) -> str | None`. Move into it, verbatim from `process_query`:
     - the `_sleep_gate` check (return `blocked_msg or "System unavailable."`)
     - `_record_user_interaction`
     - the `connect_match`, `ingest_match` and `learn_match` blocks, with each `return "<text>"` kept as is
     - `return None` at the end
  3. In `process_query`, replace the moved code with `await self._resolve_session(session_id)`, then `reply = await self._pre_intent_reply(user_input, user_id)` and `if reply is not None: return reply`.
  4. In `stream_query`, replace its session block and everything from the `_sleep_gate` call to the end of the `learn_match` block with the same two calls. If `reply is not None`, run `for char in reply: yield char` and then `return`.
- **Tests:** full suite, including W2-02 and W2-03 unchanged.
- **Done when:** the suite passes, `grep -c "connect\\\\s+mcp" src/aura/orchestrator/coordinator.py` prints `1`, and `grep -c "_sleep_gate(user_input" src/aura/orchestrator/coordinator.py` prints `1`.
- **Do not:** change the reply strings, the regexes or the connection-config dicts. Do not touch the L1 or teaching code yet. Log lines may keep `process_query`'s wording, without the `(streaming)` suffix.

---

**W2-05 Extract intent classification and the teaching lane**
- **PRD:** behaviour B0
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py`
- **Change:**
  1. Add `async def _classify_intent(self, user_input: str, user_id: str, stream: bool) -> tuple[dict[str, Any], str, str | None]`, returning `(intent_data, intent, teaching_reply)`. Move into it, from `process_query`:
     - the `l1_classify_intent` call
     - the `_publish_trace("L1", "intent_classified", {...})` call. Add `"mode": "stream"` to the dict only when `stream` is true, to keep both paths' payloads.
     - the keyword fallback block
     - the TEACHING block. It calls `log_experience(experience_data)` exactly as now and returns the teaching string as `teaching_reply`. Otherwise `teaching_reply` is `None`.
  2. In both entry points, replace the moved code with a call to `_classify_intent` (`stream=False` in `process_query`, `stream=True` in `stream_query`). If `teaching_reply is not None`, `process_query` returns it and `stream_query` yields it one character at a time, then returns.
- **Tests:** full suite.
- **Done when:** the suite passes, and `grep -c "l1_classify_intent(user_input)" src/aura/orchestrator/coordinator.py` prints `1`.
- **Do not:** move the tool-reflex (`target_skill_id`) block in this card. Do not change `tool_keywords`.

---

**W2-06 Extract forced-tool resolution**
- **PRD:** behaviour B0
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py`
- **Change:**
  1. Add `async def _resolve_forced_tool(self, intent: str, intent_data: dict[str, Any]) -> tuple[bool, str | None]`, returning `(use_forced_tool_mode, tool_schema_str)`. Move into it, verbatim from `process_query`, everything from `target_skill_id = intent_data.get("target_action")` through the end of the `if intent == "TOOL_USE":` block, including the `[MAG] Intent detection result` log line. This covers the three lookups: by `target_skill_id`, by name with the three parameterised `SELECT * FROM skill ...` queries, and the file fallback using `importlib.util` and `ingest_local_tool_module`.
  2. Replace the block in both entry points with `use_forced_tool_mode, tool_schema_str = await self._resolve_forced_tool(intent, intent_data)`.
  3. The file-fallback path uses `os.path.dirname(os.path.abspath(__file__))`. It still works because the helper stays in `coordinator.py`.
- **Tests:** full suite. Add one test to `test_turn_process_query.py` for the by-name lookup. `get_skill` returns `None`, `intent_data` has `detected_tool="web_search"`, the first `db.query` returns `[{"id": "skill:ws", "name": "web_search"}]`, and `db.select` returns `[{"definition": {"name": "web_search"}}]`. Assert that `l3_tool_call_mode` is called. Add the same test to the stream file, asserting the forced streaming branch.
- **Done when:** the suite passes, and `grep -c "SELECT \* FROM skill WHERE name = \$name" src/aura/orchestrator/coordinator.py` prints `1`.
- **Do not:** change the SQL or the parameter names (`$name`, `$normalized`, `$alt1`, `$alt2`). Do not "fix" the duplicated `has_definition` expression.

---

**W2-07 Extract prompt caching and post-response scheduling**
- **PRD:** behaviour B0
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py`
- **Change:**
  1. Add `async def _cache_system_prompt(self, synthesis_context: SynthesisContext, user_input: str, user_id: str) -> None`. It contains the identical `try:` block from both paths: `retrieve_memories(query=user_input, limit=3, importance_min=0.5, namespace=getattr(self, "_current_session_namespace", None))`, `build_l3_system_prompt`, and `self._last_system_prompt[user_id] = system_prompt`, with both warning handlers.
  2. Add `def _schedule_post_response(self, *, user_input, response, emotional_before, user_id, conversation_id, goal_context, learning_context, enable_l2, l2_reasoning_enabled, resonance_score) -> None`. It calls `asyncio.create_task(self._post_response_chain(...))` with the same keyword arguments.
  3. Replace both copies of each block with calls to the helpers. `process_query` still computes `final_l2_enabled = deep_analysis_enabled if enable_l2_analysis is None else enable_l2_analysis` and passes that. `stream_query` passes `deep_analysis_enabled`.
  4. Remove the function-local `import asyncio` lines that were only there for `create_task`. `asyncio` is imported at module level (line 9).
- **Tests:** full suite.
- **Done when:** the suite passes, `grep -c "_last_system_prompt\[user_id\] = " src/aura/orchestrator/coordinator.py` prints `1`, and `grep -c "create_task(self._post_response_chain" src/aura/orchestrator/coordinator.py` prints `1`.
- **Do not:** change the `limit=3` or `importance_min=0.5` values. Do not await the post-response chain.

---

**W2-08 Extract context gathering into a `TurnContext`**
- **PRD:** behaviour B0. This is also the seam M2 will replace.
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py`
- **Change:**
  1. Near the top of the module, add a dataclass `TurnContext` with these fields: `emotional_state`, `learning_context`, `identity_context`, `goal_context`, `resonance_score: float`, `recent_critique: str | None`, `cold_start_xml: str | None`, `latent_intuition_xml: str | None`, `synthesis_context: SynthesisContext`.
  2. Add `async def _gather_turn_context(self, user_input: str, user_id: str, conversation_history: list[dict[str, str]] | None, stream: bool) -> TurnContext`.
     - **If `stream` is false**, move `process_query`'s steps verbatim, from `emotional_state = await self.emotion_engine.get_current_state()` through `synthesis_context = SynthesisContext(...)`:
       - the sequential engine calls
       - the pursuit suggestions. Replace `datetime.now(timezone.utc)` with `get_clock().now()` from `aura.clock` (rule 7). It returns the same timezone-aware UTC value.
       - the resonance score and the history debug logs
       - the critique pop under `_state_lock`
       - the cold start context and the latent intuition
     - **If `stream` is true**, move `stream_query`'s steps verbatim:
       - the `asyncio.wait_for(asyncio.gather(..., return_exceptions=True), timeout=10.0)` call. Keep the literal `10.0`: this card authorises it.
       - the timeout and per-result fallbacks. Replace each `datetime.utcnow()` in the fallback `EmotionState` with `get_clock().now().replace(tzinfo=None)` so the value stays naive, as today.
       - the resonance score and the latent intuition
       - its smaller `SynthesisContext`. `recent_critique` and `cold_start_xml` stay `None`, and `check_goals_needing_autonomous_pursuit` is not called.
  3. In both entry points, replace the moved code with `ctx = await self._gather_turn_context(user_input, user_id, conversation_history, stream=<False|True>)`. Then use `ctx.<field>` where the old local variables were used, including in `_cache_system_prompt(ctx.synthesis_context, ...)` and `_schedule_post_response(...)`.
- **Tests:** full suite, including W2-03 (i) (an exception in learning context gives `LearningContext()`).
- **Done when:** the suite passes, `grep -c "self.goal_engine.get_goal_context()" src/aura/orchestrator/coordinator.py` prints `2` (one per branch, inside `_gather_turn_context` only), and `grep -n "get_goal_context()" src/aura/orchestrator/coordinator.py` shows no hit inside `process_query` or `stream_query`.
- **Do not:** make the non-stream path parallel, or the stream path pop critiques. Those are behaviour changes. Do not move the timeout into config in this card.

---

**W2-09 Extract the two generation stages**
- **PRD:** behaviour B0. This is also the seam G1 will replace.
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py`
- **Change:**
  1. Add `async def _generate_blocking(self, user_input, conversation_history, ctx: TurnContext, context_limit: int | None, reasoning_enabled: bool, use_forced_tool_mode: bool, tool_schema_str: str | None, requester_role: str) -> str`.
     - Move `process_query`'s generation code verbatim into it: `context_window_size = context_limit if context_limit is not None else 20`, the `[MAG] Tool mode check` log, `max_tool_rounds = 5`, `_build_loop_input`, the forced seed, the `for round_idx ...` / `else` loop with `_remove_tool_calls_from_text` and the max-rounds suffix, and the `L3 synthesis_complete` trace.
     - Return `response`.
     - Loop contexts keep exactly today's fields: `user_input`, `conversation_history`, `emotional_state`, `learning_context`, `identity_context`, `goal_context` and `recent_critique`, with no `user_id`.
  2. Add `async def _generate_streaming(self, user_input, conversation_history, ctx: TurnContext, reasoning_enabled: bool, use_forced_tool_mode: bool, tool_schema_str: str | None, requester_role: str)`. This is an async generator that yields text chunks. Move `stream_query`'s code verbatim into it, from `full_response = ""` through the end of the `else:` multi-round loop:
     - the forced branch, with the `"I executed a tool for you. ..."` prompt kept byte for byte, which mutates `ctx.synthesis_context.user_input`
     - the fallback follow-up
     - every `yield "\n\n"`
  3. `process_query` calls `response = await self._generate_blocking(...)`.
  4. `stream_query` runs `full_response = ""`, then `async for chunk in self._generate_streaming(...): full_response += chunk; yield chunk`, then schedules the post-response chain with `response=full_response`. Check that this equals today's `full_response`. Today every yielded chunk is also added to `full_response`, except the `"\n\n"` separators. So accumulate separately: have `_generate_streaming` yield `(chunk, counts: bool)` tuples, where `counts` is false for the `"\n\n"` separators, or use an equivalent you document in a comment. W2-03 (j) must still pass.
  5. Pass `requester_role` through to every `execute_and_feedback(..., requester_role=requester_role)` call.
- **Tests:** full suite.
- **Done when:** the suite passes, `grep -c "max_tool_rounds = 5" src/aura/orchestrator/coordinator.py` prints `2` (one in each helper), and `grep -c "requester_role=requester_role" src/aura/orchestrator/coordinator.py` is unchanged from before the card.
- **Do not:** unify the two tool loops. They behave differently today (stripping, max-rounds suffix, separators, the forced prompt), and G1 replaces them. Do not change `llm/layers.py`. The `depth=2` / `depth=1` difference between `l3_synthesis` and `stream_l3_synthesis` stays.

---

**W2-10 One turn pipeline**
- **PRD:** behaviour B0, section 4.4
- **Tier:** frontier
- **Files:** `src/aura/orchestrator/coordinator.py`, new `tests/unit/test_turn_pipeline.py`
- **Change:**
  1. Add a dataclass `TurnEvent` with `kind: Literal["delta", "done"]` and `text: str`.
  2. Add `async def _turn_pipeline(self, user_input, user_id, conversation_history, *, stream: bool, context_limit, enable_l2, conversation_id, reasoning_enabled, l2_reasoning_enabled, session_id, context_mode, requester_role)`, an async generator of `TurnEvent`. It runs these stages in order, each with a one-line comment naming the stage:
     1. set `self.llm_layers.context_mode`
     2. `_resolve_session`
     3. `_pre_intent_reply`
     4. `_classify_intent(stream=stream)`
     5. `_resolve_forced_tool`
     6. `_gather_turn_context(stream=stream)`
     7. `_cache_system_prompt`
     8. generation: `_generate_streaming` if `stream`, else `_generate_blocking`
     9. `_schedule_post_response(enable_l2=enable_l2, ...)`
     10. yield `TurnEvent("done", response)`

     For an early reply (stage 3 or the teaching reply from stage 4): when `stream` is true, yield one `delta` per character, then `done` with the full reply. When `stream` is false, yield only `done`. Then return, without scheduling the post-response chain (as today).

     During streaming generation, yield a `delta` for every chunk, separators included. The `done` text is the accumulated response from W2-09. Schedule the post-response chain before yielding `done`, so it still runs only after the last delta has been consumed, as today.
  3. Rewrite `process_query` (signature unchanged) as follows. Compute `final_l2_enabled` as today, iterate `_turn_pipeline(..., stream=False, enable_l2=final_l2_enabled, ...)`, and return the `done` text. Keep the opening `self.logger.info("Processing query from user ...")`.
  4. Rewrite `stream_query` (signature unchanged) to iterate `_turn_pipeline(..., stream=True, context_limit=None, enable_l2=deep_analysis_enabled, ...)` and yield `ev.text` for each `delta`. It ignores `done`.
  5. `requester_role` must reach `_turn_pipeline` from both entry points.
- **Tests:** W2-02 and W2-03 unchanged. In `test_turn_pipeline.py`:
  - (a) `_turn_pipeline(stream=False)` yields exactly one event, of kind `done`.
  - (b) `stream=True` yields deltas whose joined text equals what `stream_query` yields, then one `done`.
  - (c) With `stream=True` and a guest `requester_role`, the role reaches `execute_and_feedback`.
- **Done when:** the full suite passes, `process_query` and `stream_query` each contain no `await self.llm_layers` call (check with grep inside their line ranges), and each body is under 40 lines.
- **Do not:** change the callers in `api/routes/chat.py` or `discord/bot.py`. Do not change either public signature. Do not add behaviour hooks.

---

**W2-11 Remove what the merge left behind**
- **PRD:** behaviour B0 (closes B6)
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py`
- **Change:**
  1. Delete any locals, function-local imports (`re`, `os`, `shlex`, `importlib.util`, `asyncio`) or comments in `process_query` and `stream_query` that are now unused. The helpers keep the ones they need.
  2. Update the docstrings of `process_query` and `stream_query` to say each one is an entry point over `_turn_pipeline`. Keep the `Args` / `Returns` sections accurate.
  3. Run `ruff check src/aura/orchestrator/coordinator.py` if ruff is installed, and fix only unused-name warnings that this wave introduced.
- **Tests:** full suite.
- **Done when:**
  - The suite passes.
  - `grep -c "I've processed that instruction" src/aura/orchestrator/coordinator.py` prints `1`.
  - `grep -c "Failed to cache system prompt" src/aura/orchestrator/coordinator.py` prints `1`.
  - `git diff` for this card touches only `coordinator.py`.
- **Do not:** rename the helpers or the public methods, or change any behaviour. Do not touch the rest of the file.

---

**W2-12 Bind a record id in `boost_on_recall`**
- **PRD:** memory (W1-13 follow-up). Found by the scenario runner (W2-01, see `docs/overnight-log.md`).
- **Tier:** bulk
- **Files:** `src/aura/db/query_utils.py`, `src/aura/engines/memory/manager.py` (`boost_on_recall`), new `tests/scenarios/test_boost_on_recall_embedded.py`. Read `tests/scenarios/runner.py` (`_to_record_id`, `EmbeddedSurrealDB`, `_build_manager`) and `src/aura/api/routes/learning.py` (the `skill_ref` conversion near the comment "Ensure we query with a proper RecordID when possible").
- **Change:**
  1. `src/` has no shared helper for this. The existing pattern is the inline conversion in `api/routes/learning.py`: `from surrealdb import RecordID`, then if `":" in id`, `table, rid = id.split(":", 1)` and `RecordID(table, rid)`. Add `def to_record_id(thing: Any) -> Any` to `src/aura/db/query_utils.py`, which does that conversion. A `"table:id"` string with a non-empty table and id becomes a `RecordID`. Anything else, including a value that is already a `RecordID`, is returned unchanged.
  2. In `MemoryManager.boost_on_recall`, change the bound parameter from `{"mid": memory_id, ...}` to `{"mid": to_record_id(memory_id), ...}`. Keep the query text and the other parameters exactly as they are.
- **Tests:** `test_boost_on_recall_embedded.py`:
  - Connect an `EmbeddedSurrealDB` and build a manager with `_build_manager`, both imported from `tests/scenarios/runner.py`.
  - Store one memory with `store_memory`.
  - Read its `recall_count` with a parameterised `SELECT recall_count FROM $rid`, binding a `RecordID`.
  - Call `boost_on_recall(<the string id>)` twice and assert that `recall_count` went up by 2.
  - Add a unit test for `to_record_id`: `"memory:abc"` gives `RecordID("memory", "abc")`, `"memory"` is returned unchanged, and a `RecordID` is returned unchanged.
  - Run the full suite.
- **Done when:** the new tests pass offline on the embedded engine, and the full suite passes.
- **Do not:** change the other string-id call sites in `manager.py` in this card (list them in the log for a later card). Do not change `tests/scenarios/runner.py` or the `UPDATE` statement's text.

---

**W2-13 Fix the clause order in the spreading-activation edge query**
- **PRD:** memory (retrieval). Found by the scenario runner (W2-01, see `docs/overnight-log.md`).
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py` (`retrieve_with_spreading_activation`, the `all_edges = await self.db.query(...)` call around line 1029), new `tests/scenarios/test_spreading_edge_query_embedded.py`. Read `tests/scenarios/runner.py`.
- **Change:** in the query `SELECT in, out, similarity FROM related_to WHERE in IN $sids OR out IN $sids FETCH in, out LIMIT 50`, move `LIMIT 50` before `FETCH in, out`. The SurrealQL `SELECT` clause order is `WHERE`, `SPLIT`, `GROUP`, `ORDER`, `LIMIT`, `START`, `FETCH`, `TIMEOUT`, `PARALLEL`, `EXPLAIN`, so `FETCH` comes after `LIMIT`. The query becomes `... WHERE in IN $sids OR out IN $sids LIMIT 50 FETCH in, out`. Keep `$sids` and the binding `{"sids": seed_ids}` unchanged.
- **Tests:** `test_spreading_edge_query_embedded.py`:
  - Connect an `EmbeddedSurrealDB` from the runner.
  - Run the exact new query string through the adapter's `query` with `{"sids": []}`, and assert that it returns without raising (an empty list is fine).
  - Run the old string the same way and assert that it raises or returns an error. This proves the test detects the bug. If the adapter swallows parse errors, call the underlying embedded client directly instead.
  - Run the full suite.
- **Done when:** the new test passes offline, `grep -n "FETCH in, out" src/aura/engines/memory/manager.py` shows the line after `LIMIT 50`, and the full suite passes.
- **Do not:** change the other `FETCH in` queries (around lines 773, 838, 1506 and 1568) unless they have the same wrong order. If any of them do, report it rather than fixing it. Do not convert `seed_ids` to record ids in this card.

---


### Wave 2: cards for M2 (Recall Engine skeleton) and V0 (remove the VRM avatar)

Written against `overnight-wave-0-1` after B0 (W2-02 to W2-10) landed. W2-11 to W2-13 may land before or after these cards. None of these cards depends on them, except that W2-24 uses the runner as it is after W2-12.

**M2 scope (memory PRD section 10).** One entry point that wraps today's stores, with a budget, deduplication and a trace. All five injectors go through it. No new retrieval logic. "The five injectors" means:

1. the memory block: `retrieve_for_l3`, called from `llm/layers.py` once per L3 call
2. the insights block: `learning_context.insights`, rendered in `_build_l3_system_prompt`
3. the cold start block: `get_cold_start_context`, called in `_gather_turn_context`
4. the latent intuition block: `get_intuition_context`, called in `_gather_turn_context`
5. the recall tools: `traverse_timeline` and `fetch_supporting_evidence` in `execute_l2_internal_tool`

The debug prompt cache's separate `retrieve_memories(limit=3, importance_min=0.5)` call in `_cache_system_prompt` is also replaced.

**Facts about today's code that these cards rely on (read before W2-20):**
- The loop contexts in `_generate_blocking` and `_generate_streaming` (and the streaming follow-up context) build a new `SynthesisContext` without `user_id`, `cold_start_xml`, `latent_intuition_xml` or `resonance_score`. So:
  - `layers.retrieve_for_l3` runs with `user_id="default"` on both paths, which undoes W1-04 in practice.
  - The cold start and latent blocks that `_gather_turn_context` computes never reach the prompt, except on the forced streaming path, which uses `ctx.synthesis_context` directly.
- `retrieve_for_l3` runs once per L3 call. The query is the loop input, so from round 2 onwards it includes the tool results.
- `get_cold_start_context` always returns a non-empty `xml_block` (the wrapper is there even when every list is empty), so whenever it runs, the block counts as present.
- `retrieve_for_l3` schedules `_batch_boost_on_recall` for every memory it returns.

W2-20 changes the first two points on purpose. See that card.

---

**W2-26 Fix the clause order in the four remaining edge queries**
- **PRD:** memory (retrieval). Reported by W2-13 (see its log entry).
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py`, new `tests/scenarios/test_edge_queries_clause_order_embedded.py`. Read `tests/scenarios/test_spreading_edge_query_embedded.py` (W2-13) and `tests/scenarios/runner.py`.
- **Change:** these four queries put `FETCH in` before `LIMIT`, which SurrealDB rejects (the order is ... ORDER, LIMIT, START, FETCH ...). In each, move `LIMIT <n>` before `FETCH in`, keeping every other token, parameter name and binding unchanged:
  1. `_fetch_thought_cluster`, the `abstracted_into` sources query: `... WHERE out = $mid FETCH in LIMIT 5` becomes `... WHERE out = $mid LIMIT 5 FETCH in`.
  2. `_fetch_thought_cluster`, the `next_experience` before-traversal query: `... FETCH in LIMIT 2` becomes `... LIMIT 2 FETCH in`.
  3. `traverse_timeline`, the forward-step query: `... FETCH in LIMIT 1` becomes `... LIMIT 1 FETCH in`.
  4. `fetch_supporting_evidence`, the `abstracted_into` evidence query: `... FETCH in LIMIT 10` becomes `... LIMIT 10 FETCH in`.
- **Tests:** following the W2-13 test, run each of the four new query strings on the embedded engine with suitable empty bindings and assert none raises. Run the full suite.
- **Done when:** the new tests pass offline, `grep -nE "FETCH in(, out)? LIMIT" src/aura/engines/memory/manager.py` prints nothing, and the full suite passes.
- **Do not:** change what the queries select or their bindings. Do not touch the try/except blocks around them.

---

**W2-27 Fix the hash slice in the scenario runner's embedding stub**
- **PRD:** memory section 8.1 (scenario runner). Reported by W2-12.
- **Tier:** bulk
- **Files:** `tests/scenarios/runner.py`
- **Change:** in the stub embedding function, `int.from_bytes(h[:4,], "little")` slices with a tuple, which raises at runtime for non-empty text. Change it to `int.from_bytes(h[:4], "little")`. If W2-12's test worked around this with empty content, make it store real text again ("I like hiking in the mountains").
- **Tests:** add a unit test that the stub returns a vector of the expected length with at least one non-zero entry for a non-empty sentence, and that the same sentence gives the same vector twice. Run the full suite.
- **Done when:** the new test passes and the full suite passes.
- **Do not:** change the vector length or the normalisation.

---

**W2-14 Recall Engine package: models, config and the pure assembly step**
- **PRD:** memory section 6.1 (interface), 6.3 step 6 (budgeted assembly, without abstention), 6.6 (trace), M2
- **Tier:** frontier
- **Files:** new `src/aura/engines/recall/__init__.py`, new `src/aura/engines/recall/models.py`, new `src/aura/engines/recall/assembly.py`, `src/aura/config.py`, new `tests/unit/test_recall_assembly.py`. Read `src/aura/config.py` (the `memory_inject_max_chars` field, to copy its style), `src/aura/clock.py`, and `src/aura/engines/memory/manager.py` (`_format_memories_xml`, `get_cold_start_context`).
- **Change:**
  1. `models.py`: only standard-library dataclasses. Import nothing from `aura.llm` or `aura.orchestrator`.
     - `BlockKind = Literal["insights", "latent", "cold_start", "memories"]`, and `BLOCK_ORDER: tuple[BlockKind, ...] = ("insights", "latent", "cold_start", "memories")`. This is the order the blocks appear in today's L3 prompt, and the order in which deduplication and budget run.
     - `RecallRequest`. Fields from PRD 6.1: `user_id: str`, `user_input: str`, `session_id: str | None = None`, `recent_turns: list[dict[str, str]] = field(default_factory=list)`, `emotional_state: Any = None`, `mode: Literal["chat", "task", "agent"] = "chat"`, `token_budget: int | None = None` (`None` means use config), `latency_budget_ms: int | None = None`. M2-only fields, each with a comment saying "M2: wraps today's channel":
       - `learning_context: Any = None`
       - `depth: int = 1`
       - `limit: int = 5`
       - `namespace: str | None = None`
       - `include_cold_start: bool = False`
       - `include_latent: bool = True`
     - `Candidate(block: BlockKind, key: str, dedup_keys: tuple[str, ...], payload: Any, rank: int, source: str)`. `source` names the store, for example `"memory.retrieve_for_l3"`.
     - `TraceItem(block, key, source, rank, tokens: int, fate: Literal["kept", "duplicate", "over_budget"], duplicate_of: str | None = None)`
     - `RecallTrace(turn_id: str, user_id: str, query: str, created_at: datetime, budget_tokens: int, tokens_before: int, tokens_after: int, items: list[TraceItem], channel_errors: dict[str, str])`
     - `Block(kind: BlockKind, text: str, tokens: int, stable: bool)`. `cold_start` is stable. The other three are dynamic.
     - `ContextPacket(stable_blocks: list[Block], dynamic_blocks: list[Block], abstain: bool, trace: RecallTrace)`. Add `def block_text(self, kind) -> str | None`, which returns the text of the block of that kind, or `None` if there is no such block or its text is empty. Also add `def all_text(self) -> str`, which joins the non-empty block texts in `BLOCK_ORDER` with `"\n"`. `abstain` is always `False` in M2 (M3 adds abstention).
  2. `config.py`: add these fields in the same style as `memory_inject_max_chars`:

     | Field | Default | Env var |
     |---|---|---|
     | `recall_token_budget: int` | 3000 | `AURA_RECALL_TOKEN_BUDGET` |
     | `recall_chars_per_token: int` | 4 | `AURA_RECALL_CHARS_PER_TOKEN` |
     | `recall_share_insights: float` | 0.15 | `AURA_RECALL_SHARE_INSIGHTS` |
     | `recall_share_latent: float` | 0.10 | `AURA_RECALL_SHARE_LATENT` |
     | `recall_share_cold_start: float` | 0.30 | `AURA_RECALL_SHARE_COLD_START` |
     | `recall_share_memories: float` | 0.45 | `AURA_RECALL_SHARE_MEMORIES` |
     | `recall_dedup_enabled: bool` | True | `AURA_RECALL_DEDUP_ENABLED` |
     | `recall_budget_enabled: bool` | True | `AURA_RECALL_BUDGET_ENABLED` |
     | `recall_trace_keep: int` | 200 | `AURA_RECALL_TRACE_KEEP` |

     The two `*_enabled` flags are the ablation switches (PRD rule 7). Check that the defaults are generous: 10 core memories and 3 recent ones at the 600-character inject cap come to about 1950 tokens in the cold-start block. If you change a default, say why in the log.
  3. `assembly.py`:
     - `estimate_tokens(text: str) -> int`: `math.ceil(len(text) / settings.recall_chars_per_token)`, and 0 for an empty string.
     - `normalise_text(text: str) -> str`: casefold, strip, and collapse runs of whitespace to one space. It is used to build dedup keys.
     - `assemble(candidates: list[Candidate], renderers: dict[BlockKind, Callable[[list[Any]], str]], budget_tokens: int, shares: dict[BlockKind, float], dedup: bool, budget: bool) -> tuple[list[Block], list[TraceItem], int, int]`, returning `(blocks, trace_items, tokens_before, tokens_after)`:
       1. Group the candidates by block, in `BLOCK_ORDER`. Within a block, sort by `rank` ascending.
       2. Deduplication (only if `dedup`): walk the blocks in `BLOCK_ORDER` and the candidates in rank order. Keep a map from dedup key to `"<block>:<key>"`. If any of a candidate's `dedup_keys` is already in the map, its fate is `duplicate`, and `duplicate_of` is the first holder. Otherwise, register all of its keys. The first occurrence in block order wins.
       3. Budget (only if `budget`): `carry = 0`. For each block in `BLOCK_ORDER`:
          - `allowance = int(budget_tokens * shares[block]) + carry`
          - `kept` = the surviving candidates
          - while `kept` is non-empty and `estimate_tokens(renderer(payloads))` is more than `allowance`, pop the last candidate and mark it `over_budget`
          - `carry = max(0, allowance - estimate_tokens(text))`
       4. Render each block from its kept payloads. A block with no renderer is skipped. Keep a block only if its text is non-empty.
       5. Mark the remaining candidates `kept`. `TraceItem.tokens` is `estimate_tokens(renderer([payload]))`.
       6. `tokens_before` is the token sum of the blocks rendered from all candidates, with no dedup and no budget. `tokens_after` is the token sum of the returned blocks.
     - A renderer decides for itself what an empty list renders to. That is how the cold-start wrapper stays present, as today (see W2-17).
  4. `__init__.py` exports the models, `assemble` and `estimate_tokens`.
- **Tests:** `test_recall_assembly.py`, with string payloads and a `"\n".join` renderer:
  - (a) Two candidates in different blocks that share a dedup key: the later block's candidate is `duplicate`, and `duplicate_of` names the earlier one.
  - (b) With `dedup=False`, both are kept.
  - (c) A block over its allowance drops candidates from the end until it fits, and the dropped ones are `over_budget`.
  - (d) The unused allowance of an earlier block carries into the next one. Build a case where the second block fits only because of the carry.
  - (e) With `budget=False`, nothing is `over_budget`.
  - (f) `tokens_before >= tokens_after`, and both are exact for a hand-computed case.
  - (g) `ContextPacket.block_text` returns `None` for a missing kind and for empty text.
  - Run the full suite.
- **Done when:** the new tests pass, the full suite passes, `grep -rn "aura.llm\|aura.orchestrator" src/aura/engines/recall/` prints nothing, and `git diff --stat` shows only the five files above.
- **Do not:** call any store, the database or a model from `assembly.py`. Do not add abstention, gating or ranking. Do not put the shares inline in `assembly.py`.

---

**W2-15 Split the formatting out of `retrieve_for_l3` and `get_cold_start_context`**
- **PRD:** memory M2 (the Recall Engine must deduplicate and trim items before they are formatted)
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py` (`retrieve_for_l3`, `get_cold_start_context`), new `tests/unit/test_manager_parts.py`. Read `tests/unit/test_inject_max_chars.py`.
- **Change:**
  1. Add `async def retrieve_for_l3_parts(self, query, current_emotions=None, user_id=None, limit=5, namespace=None, depth=1) -> tuple[list[Memory], dict[str, dict]]`. Move into it, verbatim, everything in `retrieve_for_l3` from the `if depth >= 2:` branch through the thought-cluster `try/except`. That includes the namespace merge and the `asyncio.create_task(self._batch_boost_on_recall(boost_ids))` call. It returns `(memories, cluster_data)`, and `([], {})` where `retrieve_for_l3` returns `[], ""` today.
  2. `retrieve_for_l3` keeps its signature and docstring. Its body becomes:
     ```python
     memories, cluster_data = await self.retrieve_for_l3_parts(...)
     if not memories:
         return [], ""
     return memories, self._format_memories_xml(memories, cluster_data)
     ```
  3. Add `def _format_cold_start_xml(self, core_memories: list[Memory], recent_memories: list[Memory], top_insights: list[dict[str, Any]], active_cultural_node: str | None) -> str`. Move into it, verbatim, the `# Build XML block` code from `get_cold_start_context` (from `xml = "<cold_start_context>\n"` through `xml += "</cold_start_context>"`). `get_cold_start_context` calls it, and is otherwise unchanged.
- **Tests:** `test_manager_parts.py`, using a `MemoryManager.__new__` with an `AsyncMock` db, as in `test_inject_max_chars.py`:
  - (a) `retrieve_for_l3` returns exactly `_format_memories_xml(*parts)` for a patched `retrieve_memories` that returns two memories, and `[], ""` when it returns none.
  - (b) `_batch_boost_on_recall` is scheduled exactly once per `retrieve_for_l3` call.
  - (c) `_format_cold_start_xml([], [], [], None) == "<cold_start_context>\n</cold_start_context>"`.
  - Run the full suite. `test_inject_max_chars.py` must pass unchanged.
- **Done when:** the suite passes. `grep -c "_format_memories_xml(" src/aura/engines/memory/manager.py` prints `2` (the definition and the one call in `retrieve_for_l3`). `grep -c "<cold_start_context>" src/aura/engines/memory/manager.py` prints `1`.
- **Do not:** change any query, limit, the boost behaviour or the XML text. Do not change any caller.

---

**W2-16 Move the insights rendering into the Recall Engine**
- **PRD:** memory M2 (insights are one of the five injectors)
- **Tier:** bulk
- **Files:** new `src/aura/engines/recall/render.py`, `src/aura/llm/layers.py` (`_build_l3_system_prompt`, the `# 1.1 Knowledge / Insights` block only), new `tests/unit/test_recall_render.py`
- **Change:**
  1. In `render.py`, add `def render_insights(insights: list, mastery_level: float) -> str`. It returns exactly the string today's block appends:
     - `"<relevant_knowledge>\n"`
     - the PRIORITY instruction line
     - one `<insight ...>` line per item. **Note:** the caller passes the list already cut to `[:8]`. The renderer does not cut it again.
     - the `<mastery .../>` line when `mastery_level > 0.7`
     - `"</relevant_knowledge>\n\n"`

     Return `""` when `insights` is empty.
  2. In `_build_l3_system_prompt`, replace the body of `if context.learning_context and context.learning_context.insights:` with `prompt += render_insights(context.learning_context.insights[:8], context.learning_context.mastery_level)`.
- **Tests:** `test_recall_render.py`:
  - Before editing `layers.py`, capture `_build_l3_system_prompt(ctx, "T", None)` for a context with three insights and mastery 0.8, and for one with mastery 0.5. Hard-code both outputs in the test as golden strings.
  - After the edit, assert that both are byte-identical.
  - Assert that `render_insights([], 0.9) == ""`.
  - Run the full suite.
- **Done when:** the suite passes, and `grep -c "<relevant_knowledge>" src/aura/llm/layers.py` prints `0`.
- **Do not:** change the text, the attribute order or the number formatting. Do not touch any other part of the prompt.

---

**W2-17 `RecallEngine.recall`: one entry point over today's channels**
- **PRD:** memory section 6.1 and M2 ("one entry point wrapping today's stores ... no new retrieval logic")
- **Tier:** frontier
- **Depends on:** W2-14, W2-15, W2-16
- **Files:** new `src/aura/engines/recall/engine.py`, `src/aura/engines/recall/__init__.py`, new `tests/unit/test_recall_engine.py`. Read `manager.py` (`retrieve_for_l3_parts`, `get_cold_start_context`, `_format_cold_start_xml`, `_format_memories_xml`), `src/aura/engines/latent/engine.py` (`get_intuition_context`), `src/aura/models/memory.py` (`Memory`, `ColdStartContext`), `src/aura/models/learning.py` (`Insight`, `LearningContext`), `src/aura/clock.py`.
- **Change:**
  1. Define `class RecallEngine` with `__init__(self, memory_manager=None, latent_engine=None)`. Store both. When one is `None`, resolve it lazily on first use, through `aura.engines.memory.manager.get_memory_manager()` and `aura.engines.latent.engine.get_latent_engine()`, looked up as module attributes at call time so that tests can monkeypatch them. Also add `self._traces: collections.OrderedDict[str, RecallTrace]`, capped at `settings.recall_trace_keep` (evict the oldest).
  2. Define `async def recall(self, request: RecallRequest) -> ContextPacket`. Build candidates from today's channels, each in its own `try/except`. A failure records `channel_errors[<channel>] = str(e)` and the turn goes on, as the non-critical handlers do today.
     - **insights**, if `request.learning_context` has insights:
       - one candidate per item of `learning_context.insights[:8]`
       - `key = insight_id`
       - `dedup_keys = ("text:" + normalise_text(content),)`
       - `source = "learning.get_learning_context"`
       - renderer: `render_insights(payloads, learning_context.mastery_level)`
     - **latent**, if `request.include_latent`:
       - `xml = latent_engine.get_intuition_context(request.user_id)`
       - if `xml` is truthy, one candidate with `key = "latent"` and no dedup keys
       - renderer: the single payload, or `""`
     - **cold_start**, if `request.include_cold_start`:
       - `cold = await memory_manager.get_cold_start_context(request.user_id)`
       - candidates, in this order:
         - each core memory, with `key = memory_id` and `dedup_keys = ("mem:" + memory_id, "text:" + normalise_text(content))`
         - each recent memory, keyed the same way
         - each top insight dict, with `key = "cold_insight:<i>"` and `dedup_keys = ("text:" + normalise_text(content),)`
       - Payloads are tagged tuples `("core", m)`, `("recent", m)` and `("insight", d)`.
       - renderer: split the payloads back into the three lists, then call `memory_manager._format_cold_start_xml(core, recent, insights, cold.active_cultural_node)`. It renders the wrapper even when the lists are empty. This keeps today's "block present whenever the channel ran".
     - **memories**:
       - `memories, cluster_data = await memory_manager.retrieve_for_l3_parts(query=request.user_input, current_emotions=<request.emotional_state.vector.model_dump() if it has a vector, else None>, user_id=request.user_id, limit=request.limit, namespace=request.namespace, depth=request.depth)`
       - one candidate per memory, in order, with `key = memory_id` and `dedup_keys = ("mem:" + memory_id, "text:" + normalise_text(content))`
       - renderer: `memory_manager._format_memories_xml(payloads, cluster_data)` if `payloads`, else `""`
  3. Call `assemble(...)`:
     - budget: `request.token_budget or settings.recall_token_budget`
     - shares: from the four `recall_share_*` settings
     - `dedup=settings.recall_dedup_enabled`, `budget=settings.recall_budget_enabled`

     Split the returned blocks into `stable_blocks` (`cold_start`) and `dynamic_blocks` (the rest).
  4. The trace has:
     - `turn_id = uuid.uuid4().hex`
     - `query = request.user_input`
     - `created_at = get_clock().now()` (rule 7)
     - the items and token counts from `assemble`
     - `channel_errors`

     Store it in `_traces`. Return `ContextPacket(stable_blocks, dynamic_blocks, abstain=False, trace=trace)`.
  5. Add `def get_trace(self, turn_id: str) -> RecallTrace | None`.
  6. Add a module-level singleton `get_recall_engine() -> RecallEngine`, matching the pattern of `get_memory_manager`, and export `RecallEngine` and `get_recall_engine` from `__init__.py`.
- **Tests:** `test_recall_engine.py`. Use a fake manager whose `retrieve_for_l3_parts`, `get_cold_start_context`, `_format_cold_start_xml` and `_format_memories_xml` are mocks, with the latter two wrapping the real `MemoryManager` methods called on a `MemoryManager.__new__` instance, plus a fake latent engine.
  - (a) With dedup and budget disabled, `packet.block_text("memories")` equals `_format_memories_xml(memories, cluster_data)`, and `block_text("cold_start")` equals the cold context's `xml_block`. These are the byte-identical pass-through cases.
  - (b) A memory that is in both cold-start recent and the retrieved memories appears once, in `cold_start`. The trace has the second copy as `duplicate`, and `tokens_after < tokens_before`.
  - (c) An insight whose text equals a cold-start top insight (after case and whitespace normalisation) is kept in `insights` and dropped from `cold_start`.
  - (d) A tiny `token_budget` drops memories from the end. The fates are `over_budget`, and the first memory survives when it fits.
  - (e) `retrieve_for_l3_parts` raising leaves `channel_errors["memories"]` set and still returns the other blocks.
  - (f) `include_cold_start=False` means `get_cold_start_context` is not awaited. `include_latent=False` means `get_intuition_context` is not called.
  - (g) With `recall_trace_keep` monkeypatched to 2, three recalls leave only the last two traces, and `get_trace` returns `None` for the first.
  - (h) `created_at` equals a `FakeClock`'s time.
  - Run the full suite.
- **Done when:** the new tests pass, the full suite passes, and `grep -rn "db.query\|self.db" src/aura/engines/recall/` prints nothing (the engine reads only through the stores).
- **Do not:** add new queries, scoring, gating or abstention. Do not change what `retrieve_for_l3_parts` boosts. Boosting covers every retrieved memory, including deduplicated ones, until M5's feedback loop. Do not wire the engine into the pipeline in this card.

---

**W2-18 Let `SynthesisContext` carry a packet and render from it**
- **PRD:** memory section 6.1 ("`llm/layers.py` ... renders a `ContextPacket`")
- **Tier:** bulk
- **Depends on:** W2-17
- **Files:** `src/aura/llm/layers.py` (`SynthesisContext`, `_build_l3_system_prompt`, `l3_synthesis`, `stream_l3_synthesis`), new `tests/unit/test_layers_packet.py`
- **Change:**
  1. Add the keyword argument `packet: "ContextPacket | None" = None` as the last parameter of `SynthesisContext.__init__`, and store it as `self.packet`. Import `ContextPacket` from `aura.engines.recall.models`.
  2. In `_build_l3_system_prompt`, when `getattr(context, "packet", None) is not None`:
     - Insights: `text = packet.block_text("insights")`. If `text` is set, `prompt += text`. The `learning_context.insights` branch is skipped.
     - Latent: use `packet.block_text("latent")` in place of `context.latent_intuition_xml`, at the same position, followed by `"\n"`.
     - Cold start: use `packet.block_text("cold_start")` in place of `context.cold_start_xml`, at the same position, followed by `"\n"`.

     When `packet` is `None`, every branch behaves exactly as today.
  3. In `l3_synthesis` and `stream_l3_synthesis`, if `context.packet is not None`, set `memory_xml = context.packet.block_text("memories") or ""` and do not call the memory manager. Otherwise keep today's `retrieve_for_l3` call unchanged.
- **Tests:** `test_layers_packet.py`:
  - (a) Build a `ContextPacket` by hand with all four blocks. `_build_l3_system_prompt(ctx_with_packet, "T", packet.block_text("memories"))` contains each block text once, in the order insights, latent, cold_start, memories.
  - (b) With a packet and `learning_context.insights` that are not in the packet, the learning insights do not appear.
  - (c) `l3_synthesis` with a packet does not call `get_memory_manager` (monkeypatch it to raise). Stub the LLM client the way existing layer tests do, or patch the client call on the instance.
  - (d) With `packet=None`, the W2-16 golden strings still match.
  - Run the full suite.
- **Done when:** the suite passes. `grep -c "context.packet" src/aura/llm/layers.py` is at least `2`, and `retrieve_for_l3` is still called twice (`grep -c "retrieve_for_l3(" src/aura/llm/layers.py` prints `2`).
- **Do not:** change the coordinator in this card. Do not remove the fallback path. Do not move any other prompt section.

---

**W2-19 Characterise what the loop contexts drop today (tests only)**
- **PRD:** memory M2. A safety net before W2-20 changes the injection on purpose.
- **Tier:** bulk
- **Files:** `tests/unit/test_turn_process_query.py`, `tests/unit/test_turn_stream_query.py`. Read `_generate_blocking` and `_generate_streaming` in `src/aura/orchestrator/coordinator.py`.
- **Change:** add these tests, using the existing `turn_orchestrator` fixture:
  - (a) Blocking, no history. `get_cold_start_context` returns `xml_block="<cold_start_context>X</cold_start_context>"`, and the latent fake returns `"<latent>L</latent>"`. The context passed to `l3_synthesis` has `cold_start_xml is None`, `latent_intuition_xml is None` and `user_id == "default"`.
  - (b) The same for the regular streaming loop's context passed to `stream_l3_synthesis`.
  - Name both tests `test_loop_context_drops_*`. Their docstrings say: "pins pre-M2 behaviour; W2-20 changes this on purpose".
- **Tests:** the two files, then the full suite.
- **Done when:** the new tests pass and `git diff --stat src/` is empty.
- **Do not:** change `src/`.

---

**W2-20 Route the turn through the Recall Engine**
- **PRD:** memory section 6.1 and M2 ("all five injectors routed through it"). Closes F6 in practice.
- **Tier:** frontier. This is the behaviour change of the milestone, and Mai should read the list in step 5 before it merges.
- **Depends on:** W2-18, W2-19
- **Files:** `src/aura/orchestrator/coordinator.py` (`TurnContext`, `_gather_turn_context`, `_cache_system_prompt`, `_generate_blocking`, `_generate_streaming`), `tests/conftest.py` (the `turn_orchestrator` fixture), `tests/unit/test_turn_process_query.py`, `tests/unit/test_turn_stream_query.py`, `tests/unit/test_turn_pipeline.py`
- **Change:**
  1. Add the field `packet: ContextPacket | None = None` as the last field of `TurnContext`.
  2. In `_gather_turn_context`, replace the cold-start block and the latent-intuition block on both branches with one call:
     ```python
     from aura.engines.recall.engine import get_recall_engine
     packet = await get_recall_engine().recall(RecallRequest(
         user_id=user_id,
         user_input=user_input,
         recent_turns=(conversation_history or [])[-6:],
         emotional_state=emotional_state,
         learning_context=learning_context,
         depth=2 if not stream else 1,
         limit=5,
         namespace=None,
         include_cold_start=(not stream) and not conversation_history,
         include_latent=True,
     ))
     ```
     - Wrap the call in `try/except`. On failure, log a warning and set `packet = None`. With no packet, the layers fall back as in W2-18.
     - Then set `cold_start_xml = packet.block_text("cold_start") if packet else None` and `latent_intuition_xml = packet.block_text("latent") if packet else None`, and pass both into `SynthesisContext` and `TurnContext` as today.
     - Pass `packet=packet` to the `SynthesisContext` and the `TurnContext`.
     - `namespace=None` and `limit=5` match today's `layers` call. `depth` matches today's 2 (blocking) and 1 (streaming).
     - Keep the `[ICE]` and `[BRAIN]` log lines, rewritten to use the packet's trace counts.
     - Then call `self._publish_trace("RECALL", "packet_built", {...})` with `turn_id`, `tokens_before`, `tokens_after`, the number of `duplicate` items and the number of `over_budget` items.
  3. Pass `packet=ctx.packet` to every `SynthesisContext(...)` built in `_generate_blocking` and `_generate_streaming`: the blocking loop context, the streaming loop context and the streaming follow-up context. Change nothing else in those helpers.
  4. In `_cache_system_prompt`, delete the inner `retrieve_memories` `try/except`, and call `self.llm_layers.build_l3_system_prompt(synthesis_context, relevant_memories=(synthesis_context.packet.block_text("memories") if getattr(synthesis_context, "packet", None) else None))`. Keep the outer `try` and its "Failed to cache system prompt" warning.
  5. **The behaviour changes this card makes on purpose.** List each one in the log.
     - (i) Memory retrieval runs once per turn, with the user's input, not once per L3 round with the tool results appended.
     - (ii) Retrieval is scoped to the real `user_id` on both paths. Today the loop contexts fall back to `"default"`.
     - (iii) On the blocking path with no history, the cold-start block and the latent block now reach the prompt. Today they are computed and then dropped by the loop context.
     - (iv) On the streaming loop path, the latent block now reaches the prompt.
     - (v) The cached debug prompt now shows the packet's memories, not a separate `retrieve_memories(limit=3, importance_min=0.5)` list.
     - (vi) Deduplication and the budget apply to all four blocks.

     If a reviewer rejects any of these, it can be undone by setting the matching request field or config flag. Do not add flags beyond those from W2-14.
  6. Fixture: in `turn_orchestrator`, monkeypatch `aura.engines.recall.engine.get_recall_engine` to return a fake whose `recall` is an `AsyncMock`. Its default return is a `ContextPacket` with no blocks and a trace with `turn_id="t"` and zero tokens. Expose it as `orch._fake_recall_engine`. Keep the memory and latent fakes.
  7. Update the characterisation tests. Change only these assertions:
     - W2-02 (f): `retrieve_memories` and `get_cold_start_context` are no longer called from the coordinator. Assert instead that `recall` is awaited once with a request where `user_input == "hello"`, `user_id == "default"`, `depth == 2`, `include_cold_start is True` and `learning_context is` the fixture's `LearningContext`.
     - W2-03 (c): the same, with `depth == 1` and `include_cold_start is False`.
     - W2-19 (a) and (b): rename them to `test_loop_context_carries_packet_*` and assert that the loop contexts' `packet is` the packet the fake returned.
     - Every other W2-02, W2-03 and W2-10 assertion stays as it is.
- **Tests:** the updated files, plus one new test in `test_turn_pipeline.py`. When the fake recall raises, the turn still completes and the loop context has `packet is None`. Run the full suite.
- **Done when:**
  - The suite passes.
  - `grep -n "get_cold_start_context\|get_intuition_context\|retrieve_memories" src/aura/orchestrator/coordinator.py` prints nothing.
  - `grep -c "packet=ctx.packet" src/aura/orchestrator/coordinator.py` prints `3`.
  - `grep -c "get_recall_engine()" src/aura/orchestrator/coordinator.py` prints at least `1`.
- **Do not:** change the 10 s gather, the critique handling, `SynthesisContext.user_id` or the tool loops. Do not call the memory manager from the coordinator for prompt context. Do not remove the `cold_start_xml` and `latent_intuition_xml` fields.

---

**W2-21 The layers' fallback path goes through the Recall Engine too**
- **PRD:** memory section 6.1 ("`llm/layers.py` stops calling `retrieve_for_l3` ...") and PRD rule 4
- **Tier:** bulk
- **Depends on:** W2-20
- **Files:** `src/aura/llm/layers.py` (`l3_synthesis`, `stream_l3_synthesis`), `tests/unit/test_layers_packet.py`. Read `src/aura/engines/goal/engine.py` around the `l3_synthesis` call. It builds a `SynthesisContext` with no packet, and it is the remaining packet-less caller.
- **Change:** in both methods, replace the `else` branch (today's `get_memory_manager().retrieve_for_l3(...)`) with:
  ```python
  packet = await get_recall_engine().recall(RecallRequest(
      user_id=context.user_id,
      user_input=context.user_input,
      emotional_state=context.emotional_state,
      learning_context=None,
      depth=<2 in l3_synthesis, 1 in stream_l3_synthesis>,
      limit=5,
      include_cold_start=False,
      include_latent=False,
  ))
  memory_xml = packet.block_text("memories") or ""
  ```
  - Keep the surrounding `try/except` and its warning text.
  - `learning_context=None` and `include_latent=False` mean the fallback only replaces the memory block. The insights, latent and cold-start sections keep rendering from the context fields when there is no packet, so the goal engine's prompt is unchanged apart from the budget on memories.
- **Tests:** add to `test_layers_packet.py`:
  - (e) With `packet=None`, `l3_synthesis` awaits the monkeypatched `get_recall_engine().recall` once with `depth=2`, and `stream_l3_synthesis` with `depth=1`.
  - Run the full suite.
- **Done when:** the suite passes. `grep -c "get_memory_manager\|retrieve_for_l3(" src/aura/llm/layers.py` prints `0`. `grep -rn "retrieve_for_l3(" src --include=*.py` shows only `manager.py`.
- **Do not:** change the goal engine. Do not pass the goal engine's `learning_context` into the request (its insights render through the unchanged no-packet branch).

---

**W2-22 Route the recall tools through the Recall Engine**
- **PRD:** memory section 6.4 (the deep-path tools live in the Recall Engine) and M2 (the fifth injector)
- **Tier:** bulk
- **Depends on:** W2-17
- **Files:** `src/aura/engines/recall/engine.py`, `src/aura/orchestrator/coordinator.py` (`execute_l2_internal_tool` only), new `tests/unit/test_recall_tools.py`
- **Change:**
  1. Add two methods to `RecallEngine` that delegate unchanged to the memory manager and return its result as is:
     - `async def timeline(self, experience_id: str, steps: int = 3, direction: str = "forward") -> list[dict]`, which calls `traverse_timeline(experience_id=..., steps=..., direction=...)`
     - `async def evidence(self, insight_id: str) -> list[dict]`, which calls `fetch_supporting_evidence(insight_id=...)`

     Use the return annotations the manager methods have.
  2. In `execute_l2_internal_tool`, replace `from aura.engines.memory.manager import get_memory_manager` and `mm = get_memory_manager()` with `from aura.engines.recall.engine import get_recall_engine` and `recall = get_recall_engine()`. Call `recall.timeline(...)` and `recall.evidence(...)` with the same arguments. The formatting of the returned strings is unchanged.
- **Tests:** `test_recall_tools.py`:
  - Build the orchestrator with the `turn_orchestrator` fixture and a fake recall engine.
  - For each tool, the result string is the same as today's for a scripted return value. Hard-code the expected strings.
  - An empty result gives the "No ... found" string.
  - Run the full suite.
- **Done when:** the suite passes, and the line range of `execute_l2_internal_tool` contains no `get_memory_manager` (check with `grep -n`).
- **Do not:** rename the tools or change their schemas in `L2_INTERNAL_TOOLS`. Do not add the PRD's new tools (`recall`, `what_changed`, `pin`); they are M5.

---

**W2-23 Recall trace endpoint**
- **PRD:** memory section 6.6
- **Tier:** bulk
- **Depends on:** W2-17
- **Files:** new `src/aura/api/routes/recall.py`, `src/aura/main.py` (imports and `include_router` lines only), new `tests/unit/test_recall_route.py`. Read `src/aura/api/routes/memory.py` for the router style.
- **Change:**
  1. In `recall.py`, add `router = APIRouter()` and `@router.get("/trace/{turn_id}")`. It returns `dataclasses.asdict(trace)`, with `created_at` as ISO text, for `get_recall_engine().get_trace(turn_id)`, and raises `HTTPException(404, "trace not found")` when the trace is `None`.
  2. Add `@router.get("/traces")`, which returns `{"turn_ids": [...]}`: the stored ids, newest first.
  3. In `main.py`, add `from aura.api.routes import recall as recall_routes` next to the other route imports, and `app.include_router(recall_routes.router, prefix="/recall", tags=["recall"])` after the memory router line.
- **Tests:** `test_recall_route.py` calls the handler coroutines directly, with a `RecallEngine` that holds one trace (monkeypatch `get_recall_engine`). Cover a known id, an unknown id (404) and the list order. Run the full suite.
- **Done when:** the suite passes, and `grep -c "recall_routes" src/aura/main.py` prints `2`.
- **Do not:** add the frontend debug view (later, with M3). Do not persist traces to the database.

---

**W2-24 Scenario runner through the Recall Engine, end to end**
- **PRD:** memory M2 gate ("same accuracy as M1, fewer tokens per turn") and section 8.1
- **Tier:** bulk
- **Depends on:** W2-17
- **Files:** `tests/scenarios/runner.py`, new `tests/scenarios/test_recall_engine_embedded.py`. Read `tests/scenarios/test_runner_smoke.py`.
- **Change:**
  1. `ProbeResult` gets new fields:
     - `packet_tokens: int = 0`
     - `tokens_before: int = 0`
     - `trace_turn_id: str | None = None`
  2. `run(scenario, via: Literal["legacy", "recall"] = "legacy")`.
     - `"legacy"` is today's path, unchanged, except that it also sets `packet_tokens = estimate_tokens(packet_xml)`.
     - `"recall"` builds `RecallEngine(memory_manager=manager, latent_engine=<a stub whose get_intuition_context returns None>)`. For each probe it calls `recall(RecallRequest(user_id=probe.user_id, user_input=probe.question, depth=2, limit=5, include_cold_start=True, include_latent=False))`, and computes `gold_found` against `packet.all_text()`. It sets `packet_chars = len(packet.all_text())`, `packet_tokens = trace.tokens_after`, `tokens_before = trace.tokens_before` and `trace_turn_id`.
- **Tests:** `test_recall_engine_embedded.py`, on the embedded engine with the FakeClock and the stub embeddings:
  - Scenario: on day 0, "My dog's name is Biscuit", "I work as a nurse" and "My sister is called Ana" (same user). A dream on day 1. On day 2, the probe "What's my dog's name?" with gold `["Biscuit"]`.
  - (a) `run(..., via="recall")` completes, and the result's `gold_found == run(..., via="legacy")`'s `gold_found` (same accuracy; this does not assert that the gold is found).
  - (b) If the trace has any `duplicate` item, `tokens_before > packet_tokens`. Otherwise `tokens_before == packet_tokens`. Record which case happened in the log.
  - (c) Ablation: with `recall_dedup_enabled` and `recall_budget_enabled` monkeypatched to `False`, `packet_tokens == tokens_before`.
  - Run the full suite. `test_runner_smoke.py` must pass unchanged.
- **Done when:** the new test passes offline (no model download, no SurrealDB server) and the full suite passes. The log records the legacy and recall `packet_tokens` for the probe.
- **Do not:** change `src/`. Do not change the legacy path's retrieval arguments. Do not assert that the gold was found.

---

**W2-25 Remove the VRM avatar**
- **PRD:** avatar section 4 and milestone V0 (test T1)
- **Tier:** bulk
- **Files:**
  - **Delete:**
    - `frontend/src/components/vrm-engine/` (the whole directory)
    - `frontend/src/components/VrmModelSelector.tsx`
    - `frontend/src/components/AvatarCanvas.tsx`
    - `frontend/src/components/AuraAvatar.tsx`
    - `frontend/src/components/FloatingAvatarWindow.tsx`
    - `frontend/src/services/animationRouterInstance.ts`
    - `frontend/src/services/avatarAudioBridge.ts`
    - `frontend/src/utils/emotionToBlendshape.ts`: imported only by `AvatarCanvas.tsx`
    - `frontend/inspect-vrm.js`: it only inspects `node_modules/@pixiv/three-vrm`
    - `frontend/public/vrm-assets/` (the whole directory)
    - `src/aura/api/routes/l5_animation.py`
  - **Edit:**
    - `frontend/src/pages/chat.tsx`
    - `frontend/package.json` and `frontend/package-lock.json`, through `npm uninstall` only
    - `src/aura/main.py`: only the `l5_animation` import (line 32) and its `include_router` line (line 490)
  - **Read:** `frontend/src/components/SpiralAvatar.tsx`, and the `FloatingAvatarWindow.tsx` collapsed-state `Box` (around lines 160 to 180, for the position values) before deleting it.
- **Change:**
  1. Setup: from `frontend/`, run `npm ci` first. `node_modules` is not installed in this checkout. Then run `npm run build` once **before** any change, and record whether it passes. Mai decided on 2026-11-20 to remove the VRM feature without restoring its missing files: the pre-change build is expected to fail on unresolved imports of `lib/VRMAnimation/...` and `lib/VRMLookAtSmootherLoaderPlugin/...`, which only files inside `vrm-engine/` import, and this card deletes that directory. Record the pre-change errors in the log. If the pre-change build fails for any other reason, stop and report those errors. Do not recreate, stub or download the missing files, and do not fix unrelated build errors. The build must pass after the change.
  2. Delete the files and directories listed above with `git rm -r`. `public/vrm-assets/` holds:
     - 10 `.vrm` models: `Aera`, `AvatarSample_A` to `AvatarSample_D`, `Dhahlia`, `Epithet`, `Lara Lightland`, `Onyx` and `Velara`
     - 15 `.vrma` clips
     - `thumb-placeholder.jpg`

     If `vrm-animations-temp/` exists at the repository root, delete it too. Today it is not present and not tracked.
  3. In `chat.tsx`:
     - Remove the imports of `FloatingAvatarWindow` and `avatarAudioBridge` (lines 86 and 87).
     - In the TTS handler, remove the `blob.arrayBuffer().then(buf => { avatarAudioBridge.dispatch(...) }).catch(...)` statement and its two comment lines. Keep `audioQueue.push(blob); playNextInQueue();`.
     - Remove the whole `// ---- Movement Command ...` `try { ... animationRouterInstance ... } catch {}` block.
     - Remove the whole `// ---- L5 Animation Selector ...` `try { fetch(`${API_BASE_URL}/l5/select-animation` ...) } catch (l5Err) {...}` block.
     - Replace `<FloatingAvatarWindow />` with:
       ```tsx
       <Box sx={{ position: 'fixed', right: { xs: 16, md: 24 }, bottom: { xs: 96, md: 112 }, zIndex: 1320, pointerEvents: 'none' }}>
         <SpiralAvatar size={64} />
       </Box>
       ```
       Then add `import SpiralAvatar from '@/components/SpiralAvatar';` next to the other component imports. `Box` is already imported from `@mui/material`.
     - If the build or lint then reports a variable that became unused because of these removals (for example `emotion`), remove only that variable.
  4. Dependencies: run `npm uninstall @pixiv/three-vrm stats.js lil-gui three-mesh-bvh @mkkellogg/gaussian-splats-3d` from `frontend/`. Each of these is imported only by files deleted in step 2:
     - `@pixiv/three-vrm`: `vrm-engine/` and `AvatarCanvas.tsx`
     - `stats.js`, `lil-gui` and `three-mesh-bvh`: `vrm-engine/features/vrmViewer/viewer.ts`
     - `@mkkellogg/gaussian-splats-3d`: `vrm-engine/features/vrmViewer/room.ts`

     Before uninstalling, confirm each one with `grep -rn "<name>" src` returning nothing.
  5. In `main.py`, delete the `from aura.api.routes import l5_animation as l5_animation_routes` line and the `app.include_router(l5_animation_routes.router, tags=["l5-animation"])` line.
- **Tests:** the frontend has no test suite (`package.json` has no `test` script), so the checks are:
  - from `frontend/`: `npm ci`, then `npm run build` passes
  - from `aura-app`: the Python suite `.venv\Scripts\python.exe -m pytest`
  - start the dev server and check by hand that `/chat` shows the spiral at the bottom right
- **Done when:**
  - `npm run build` succeeds from `frontend/` after `npm ci`.
  - `grep -rniE "three-vrm|vrm-engine|VrmRenderer|VrmModelSelector|AuraAvatar|AvatarCanvas|FloatingAvatarWindow|avatarAudioBridge|animationRouter|emotionToBlendshape|l5/select-animation" frontend/src frontend/package.json` prints nothing (this is T1).
  - `grep -cE "\"(@pixiv/three-vrm|stats.js|lil-gui|three-mesh-bvh|@mkkellogg/gaussian-splats-3d)\"" frontend/package.json` prints `0`, and the same names no longer appear as top-level `"node_modules/<name>"` keys in `package-lock.json`.
  - `git ls-files frontend/public/vrm-assets | wc -l` prints `0`, and `git ls-files | grep -ciE "\.vrma?$"` prints `0`.
  - `grep -rn "l5_animation" src` prints nothing, and the Python suite passes.
  - `SpiralAvatar.tsx` and `ChatMessage.tsx` are unchanged (`git diff --stat` does not list them).
- **Do not:**
  - Do not remove `three` or `@types/three`, because `SpiralAvatar` uses them. Do not remove `@gltf-transform/core`: nothing in `src` imports it, but the PRD does not list it, so report it instead.
  - Do not add `AvatarStage` or any V1 work. Do not add anything that needs the MetaHuman or new asset.
  - Do not touch `ttsService`, the TTS queue, `l5_structure_analysis` in `llm/layers.py`, the `l5_model` settings or `discord.tsx`. The MUI `Avatar` there is unrelated.

---

### Wave 2: cards for G1 (tool registry and the single tool loop)

Written against `overnight-wave-0-1` after B0 (W2-02 to W2-10), M2 (W2-14 to W2-24) and W1-01/W1-02 landed.

**G1 scope (agency PRD sections 5.1, 5.2, 5.3, milestone G1, test T10, rules 3 and 4 of section 10).**
- One tool registry: every capability is one record with `name`, `description`, `input_schema`, `transport`, `risk`, `health`, `stats` (5.1).
- One loop used by both the blocking and the streaming turn. Native function calling when the L3 model supports it, today's text extraction (`ToolExecutor.extract_tool_calls`) as the fallback, so no model tier loses tool use (5.2).
- When more than about 15 tools exist, offer only the top few by embedding similarity plus recent success (5.2, T10).
- The keyword intent rule is removed. The fast lane stays for learned trigger phrases (5.2, finding G4).
- The role is enforced in the loop, through the one function every call passes through (5.3, rule 4). No tool schema may carry an approval field (rule 3).

**Out of scope for G1, on purpose:**
- `executor/agent_loop.py` and `engines/goal/engine.py`. The PRD removes the agent loop in G4 ("remove the agent loop ... leaving no parallel old and new paths", rule 6), so G1 does not port it. `engines/goal/engine.py` does not call the tool executor today. No G1 card touches either file.
- Approval prompts and the policy table (G3). In the chat loop, approval stays exactly as W1-02 left it: the loop never passes `approved=True`, so gated writes and commands come back as "needs approval" results.
- Argument repair (finding G2) stays inside `ToolExecutor._auto_repair_arguments` as it is.

**Facts about today's code that these cards rely on (read before W2-31):**
- Tools are found in three places, and nothing joins them:
  1. local modules in `src/aura/tools/` exposing `TOOL_DEFINITION` + `run` (`chartjs` as `generate_chart`, `terminal`, `web_search`) or a `TOOLS` dict (`filesystem`: 9 tools, `code_executor`: `execute_code`, `workspace_info`);
  2. `skill` rows with `skill_type = 'local_function'` (written by `LearningEngine.ingest_local_tool_module`);
  3. `skill` rows with `skill_type = 'mcp_tool'` (written by `ingest_mcp_server` and `_compile_skill`), with server, connection and `status` in `execution_config`, and `description_embedding` on the row.
- `ToolExecutor.execute_tool_call` looks the tool up in the `skill` table only. Its first statement refuses every `requester_role` other than `"owner"` (W1-01). It strips `force_execute` and every `_`-prefixed key from the model's arguments and sets `_runtime_approved` only when `approved=True` (W1-02).
- No tool schema is shown to the L3 model today, except the one schema the forced mode passes to `l3_tool_call_mode`. The L3 prompt shows tool names (`<capabilities>`) and the `<AGENT_ACTION_RULE>` examples.
- `LLMClient.complete` / `stream_complete` (and the router and unified provider) return text only. Nothing reads `tool_calls` from a response.
- `_generate_blocking` and `_generate_streaming` differ in these ways (all pinned by the characterisation tests):

| | blocking | streaming |
|---|---|---|
| tool JSON removed from the response | yes, `_remove_tool_calls_from_text` on the last round | no |
| suffix after 5 rounds of tool calls | `"\n\n(Stopped after max tool rounds; ask me to continue if needed.)"` (test_turn_process_query (j)) | none (test_turn_stream_query (f)) |
| `"\n\n"` between rounds | none | yielded after every tool round, not counted in `full_response` (stream (e)) |
| forced mode, call found | seeds the loop with `[Seed]\n<results>` (process (l)) | one stream with the `"I executed a tool for you. ..."` prompt, no loop (stream (g)) |
| forced mode, no call found | normal loop | one plain stream, then at most one follow-up stream with `"\n\n"` (stream (h)) |
| response kept for post-response chain | last round, stripped, plus suffix | every round's text concatenated |
| per-round telemetry `L3 synthesis_complete` | yes | no |
| `recent_critique` in loop context | `ctx.recent_critique` | not set (it is always `None` on the stream path, so no difference) |
| history passed | `max_history_messages=context_limit or 20` | `layers` uses the last 10 |

**What G1 chooses where the two differ.** The PRD says only "a single loop". Where it is silent, the cards choose the behaviour that is correct for both venues and say so. Mai should read this list before W2-32 merges:
- (a) Tool-call JSON is removed from the response that is stored and passed to the post-response chain, on both paths. On the stream path, chunks already sent cannot be taken back, so the user still sees them; the stored response does not keep them.
- (b) The max-rounds suffix is added on both paths. On the stream path it arrives as one last delta.
- (c) `"\n\n"` is yielded between rounds on both event streams, but only before a following round (not after the last one). The blocking path ignores separators, as today.
- (d) The response is the final round's text (stripped, plus suffix if any) on both paths. The stream path no longer stores the earlier rounds' text.
- (e) Forced mode seeds the single loop on both paths, as the blocking path does today. The streaming-only `"I executed a tool for you"` prompt and the streaming-only fallback follow-up are removed.
- (f) Telemetry: `L3 synthesis_complete` with the round number is published on both paths.
- (g) The per-path history limits stay as they are (they live in `layers`, not in the loop).

---

**W2-28 Tool registry: records, loaders and the schema sanitiser**
- **PRD:** agency 5.1 ("One registry"), section 10 rule 3
- **Tier:** bulk
- **Files:** new `src/aura/executor/tool_registry.py`, new `tests/unit/test_tool_registry.py`. Read `src/aura/tools/*.py` (the definitions), `src/aura/engines/learning/engine.py` (`ingest_local_tool_module`, `ingest_mcp_server`, the `mcp_tool` merge in `_compile_skill`) and `src/aura/executor/tool_executor.py` (`_mark_mcp_skill_offline`).
- **Change:**
  1. In the new module define:
     ```python
     Transport = Literal["builtin", "mcp", "opencode", "http"]
     Risk = Literal["read", "write", "execute", "send"]

     @dataclass
     class ToolHealth:
         status: Literal["online", "offline", "unknown"] = "unknown"
         last_check: datetime | None = None
         error: str | None = None

     @dataclass
     class ToolStats:
         calls: int = 0
         successes: int = 0
         latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=50))
         @property
         def median_latency_ms(self) -> float | None: ...   # statistics.median, None when empty
         @property
         def success_rate(self) -> float | None: ...        # successes / calls, None when calls == 0

     @dataclass
     class ToolRecord:
         name: str
         description: str
         input_schema: dict
         transport: Transport
         risk: Risk
         health: ToolHealth = field(default_factory=ToolHealth)
         stats: ToolStats = field(default_factory=ToolStats)
         source: str = ""                      # module name, or the skill record id
         description_embedding: list[float] | None = None
     ```
  2. `sanitize_schema(schema: dict) -> dict`: return a deep copy where, under `properties`, the key `force_execute` and every key starting with `_` are removed, and the same names are removed from `required`. Recurse into nested `properties` of object-typed properties. A non-dict input returns `{"type": "object", "properties": {}}`.
  3. `BUILTIN_RISK: dict[str, Risk]`, exactly:
     `read_file, list_directory, directory_tree, search_files, get_file_info, workspace_info, web_search, generate_chart` -> `"read"`;
     `write_file, edit_file, create_directory, delete_file` -> `"write"`;
     `terminal, execute_code` -> `"execute"`.
     `BUILTIN_MODULES = ("chartjs", "code_executor", "filesystem", "terminal", "web_search")`.
  4. `load_builtin_tools() -> list[ToolRecord]`: for each name in `BUILTIN_MODULES`, `importlib.import_module(f"aura.tools.{name}")`. If the module has `TOOLS`, make one record per entry from `entry["definition"]`; otherwise use `TOOL_DEFINITION`. Each record: `name=definition["name"]`, `description=definition.get("description", "")`, `input_schema=sanitize_schema(definition.get("parameters", {}))`, `transport="builtin"`, `risk=BUILTIN_RISK.get(name, "execute")`, `source=<module name>`, health `online`. A module that fails to import is logged at warning and skipped.
  5. `records_from_skill_rows(rows: list[dict]) -> list[ToolRecord]`: for each row with `skill_type` in (`mcp_tool`, `local_function`) and a dict `definition`:
     - name: `row.get("tool_name") or definition.get("name") or row.get("name")`
     - schema: the first dict among `definition.get("parameters")`, `definition.get("inputSchema")`, `definition.get("input_schema")`, passed through `sanitize_schema`
     - `mcp_tool`: `transport="mcp"`, `risk="execute"` (see Do not), health from `execution_config.get("status")` (`online`/`offline`, else `unknown`) and `execution_config.get("last_error")`
     - `local_function`: `transport="builtin"`, `risk=BUILTIN_RISK.get(name, "execute")`
     - `source=str(row.get("id"))`, `description_embedding=row.get("description_embedding")`
  6. `class ToolRegistry` with: `register(record)` (replaces a record of the same name, but keeps its `stats`), `get(name) -> ToolRecord | None`, `all() -> list[ToolRecord]` (sorted by name), `record_call(name, success: bool, latency_ms: float)` (no-op for unknown names), `set_health(name, status, error=None)` (sets `last_check` from the clock provider, rule 7), and `async refresh(db)`:
     - registers `load_builtin_tools()` first,
     - then runs `SELECT id, name, tool_name, skill_type, definition, execution_config, description_embedding FROM skill WHERE skill_type IN $types` with `{"types": ["mcp_tool", "local_function"]}`, and registers `records_from_skill_rows(...)`, except that a `local_function` row whose name is already registered as a builtin only copies its `description_embedding` onto the builtin record,
     - a database error is logged at warning; the builtins stay.
  7. `get_tool_registry() -> ToolRegistry` (module singleton) and `reset_tool_registry()` (for tests).
- **Tests:** `test_tool_registry.py`, offline:
  - `load_builtin_tools()` returns exactly 14 records whose names are the keys of `BUILTIN_RISK`, all `transport == "builtin"`.
  - No record from `load_builtin_tools()` has `force_execute` or a `_`-prefixed key anywhere in `input_schema` (walk the dict).
  - `sanitize_schema` removes `force_execute` and `_x` from `properties` and `required`, including one nested level, and does not mutate its input.
  - `records_from_skill_rows` on one `mcp_tool` row with `inputSchema` and `execution_config={"status": "offline", "last_error": "boom"}` gives `transport "mcp"`, `risk "execute"`, health `offline` with error `"boom"`.
  - `refresh` with a fake db returning one `mcp_tool` row and one `local_function` row named `web_search` with an embedding: 15 records, and `get("web_search").description_embedding` is that embedding.
  - `refresh` with a db whose `query` raises: 14 records.
  - `record_call` three times (two successes, latencies 10, 30, 20): `calls == 3`, `success_rate == 2/3`, `median_latency_ms == 20`. `register` of a new record with the same name keeps those stats.
  Run the full suite.
- **Done when:** the new tests pass, the full suite passes, and `grep -n "f\"SELECT\|f'SELECT" src/aura/executor/tool_registry.py` prints nothing.
- **Do not:** put the module in `src/aura/tools/` (that directory is scanned for tool modules by `ingest_local_tool_module` and the forced-mode file fallback). Do not change `ToolExecutor` or any tool module. Do not guess MCP risk from `risk_level`; MCP tools are `execute` until G3's policy table says otherwise (listed for Mai in the final report).

---

**W2-29 The executor reports calls and MCP health to the registry**
- **PRD:** agency 5.1 (`health`, `stats`)
- **Tier:** bulk
- **Depends on:** W2-28
- **Files:** `src/aura/executor/tool_executor.py` (`execute_tool_call`, `_mark_mcp_skill_offline`, `_mark_mcp_skill_online`), `tests/unit/test_tool_registry.py`, `tests/unit/test_requester_role.py` (read for the fake executor pattern)
- **Change:**
  1. In `execute_tool_call`, after the role gate and the argument stripping (both unchanged), take `start = time.perf_counter()` immediately before `# 1. Fetch skill from database`. After `result` is final (just before it is returned, on both the success and the exception path), call `get_tool_registry().record_call(tool_name, bool(result.get("success")), (time.perf_counter() - start) * 1000)` inside `try/except Exception: pass`.
     - A role-refused call is not recorded (it returns before `start`).
     - A "not found in skill database" result is recorded only if the name is in the registry (`record_call` ignores unknown names).
  2. At the end of the `try` in `_mark_mcp_skill_offline`, call `get_tool_registry().set_health(tool name, "offline", error)`. In `_mark_mcp_skill_online`, `set_health(tool name, "online")`. Both functions take a `skill_id`, not a name, so add a keyword argument `tool_name: str | None = None` to each, pass `tool_name=tool_name` at every call site in `_execute_mcp_tool`, and only call `set_health` when it is given.
- **Tests:** in `test_tool_registry.py`, using the `ToolExecutor.__new__` + fake db pattern from `test_requester_role.py`:
  - owner call to a fake `local_function` tool registered in the registry: `stats.calls == 1`, `successes == 1`, one latency recorded.
  - guest call: `stats.calls == 0`.
  - `_mark_mcp_skill_offline(skill_id="skill:x", execution_config={}, error="e", tool_name="t")` with `t` registered: health `offline`, error `"e"`, `last_check` set.
  Call `reset_tool_registry()` in a fixture. Run the full suite.
- **Done when:** the new tests pass, the full suite (including `test_requester_role.py` and `test_tool_approval_runtime.py`, unchanged) passes, and `grep -c "record_call" src/aura/executor/tool_executor.py` prints at least `1`.
- **Do not:** move the role gate or the argument stripping, or record before them. Do not make registry errors fail a tool call.

---

**W2-30 Tool selection: the top few by similarity and recent success**
- **PRD:** agency 5.2 ("When more than about 15 tools are available, select the top few by embedding similarity to the request plus recent success"), T10
- **Tier:** bulk
- **Depends on:** W2-28
- **Files:** `src/aura/executor/tool_registry.py`, `src/aura/config.py`, `tests/unit/test_tool_registry.py`. Read `src/aura/llm/embeddings.py` (`get_embeddings_client().embed`).
- **Change:**
  1. Config, next to the other `AURA_` fields:
     - `tool_selection_threshold: int = 15` (`AURA_TOOL_SELECTION_THRESHOLD`): selection runs only when more tools than this are available.
     - `tool_selection_top_k: int = 8` (`AURA_TOOL_SELECTION_TOP_K`)
     - `tool_selection_success_weight: float = 0.2` (`AURA_TOOL_SELECTION_SUCCESS_WEIGHT`)
  2. In the registry, `async def select_tools(self, request_text: str, *, requester_role: str, embed=None) -> list[ToolRecord]`:
     - If `requester_role != "owner"`, return `[]`. (Today the executor refuses every non-owner call, so offering tools to them would be a lie. The `trusted` and `guest` allowlists of 5.3 come with G3.)
     - `candidates = [r for r in self.all() if r.health.status != "offline"]`.
     - If `len(candidates) <= settings.tool_selection_threshold`, return `candidates`.
     - Otherwise embed `request_text` once (`embed` defaults to `get_embeddings_client().embed`). For each candidate with no `description_embedding`, embed `f"{r.name}: {r.description}"` once and cache it on the record.
     - Score = cosine similarity + `settings.tool_selection_success_weight * (r.stats.success_rate if r.stats.calls >= 3 else 0.5)`.
     - Return the top `settings.tool_selection_top_k` by score, ties broken by name. If the request embedding is `None` or raises, return the first `top_k` candidates by name and log a warning.
- **Tests:** T10 in `test_tool_registry.py` with a fake `embed` (deterministic vectors, no model download):
  - 20 registered tools, request similar to tool `t07`: 8 tools returned and `t07` is first.
  - Two tools with equal similarity, one with 4 calls and 4 successes, one with 4 calls and 0 successes: the successful one ranks higher.
  - 10 tools: all 10 returned, `embed` never called.
  - `requester_role="guest"` with 20 tools: `[]`.
  - An `offline` tool is never returned.
  Run the full suite.
- **Done when:** the new tests pass, the full suite passes, and `grep -n "tool_selection_" src/aura/config.py` prints the three fields.
- **Do not:** store anything in the database. Do not call `select_tools` from the coordinator yet (W2-35).

---

**W2-31 The single tool loop, as a new function with its own tests**
- **PRD:** agency 5.2 ("The coordinator's two parsing loops are replaced by a single loop"), 5.3 ("enforced in the tool loop"), rules 3 and 4
- **Tier:** frontier. This fixes the loop's contract that W2-32, W2-33 and W2-37 build on.
- **Files:** new `src/aura/orchestrator/tool_loop.py`, new `tests/unit/test_tool_loop.py`, `src/aura/config.py`. Read `_generate_blocking`, `_generate_streaming` and `_remove_tool_calls_from_text` in `src/aura/orchestrator/coordinator.py`, and `src/aura/executor/tool_executor.py`.
- **Change:**
  1. Config: `tool_loop_max_rounds: int = 5` (`AURA_TOOL_LOOP_MAX_ROUNDS`).
  2. In the new module:
     ```python
     MAX_ROUNDS_SUFFIX = "\n\n(Stopped after max tool rounds; ask me to continue if needed.)"
     ROUND_SEPARATOR = "\n\n"

     @dataclass
     class LoopEvent:
         kind: Literal["delta", "separator", "done"]
         text: str

     RoundFn = Callable[[str, int], AsyncIterator[str]]  # (loop_input, round_idx) -> text chunks of one L3 round

     def strip_tool_calls(text: str) -> str: ...  # body copied verbatim from Orchestrator._remove_tool_calls_from_text

     def build_loop_input(user_input: str, blocks: list[str]) -> str:
         return user_input if not blocks else f"{user_input}\n\n[Tool Execution Results]\n" + "\n\n".join(blocks)

     async def run_tool_loop(
         *,
         user_input: str,
         generate_round: RoundFn,
         tool_executor: Any,
         requester_role: str,
         max_rounds: int | None = None,   # None -> settings.tool_loop_max_rounds
         seed_results: str | None = None,
     ) -> AsyncIterator[LoopEvent]: ...
     ```
  3. `run_tool_loop` behaviour, exactly:
     - `blocks = ["[Seed]\n" + seed_results] if seed_results else []`.
     - For `round_idx` in `1..max_rounds`:
       - if `round_idx > 1`, yield `LoopEvent("separator", ROUND_SEPARATOR)`;
       - stream `generate_round(build_loop_input(user_input, blocks), round_idx)`, yield each chunk as `LoopEvent("delta", chunk)` and accumulate `round_text`;
       - `calls = tool_executor.extract_tool_calls(round_text)`. If empty: `final = strip_tool_calls(round_text)`, stop;
       - `results = await tool_executor.execute_and_feedback(calls, requester_role=requester_role)`. If empty: `final = strip_tool_calls(round_text)`, stop;
       - `blocks.append(f"[Round {round_idx}]\n{results}")`.
     - If every round had tool calls: yield `LoopEvent("delta", MAX_ROUNDS_SUFFIX)` and `final = strip_tool_calls(round_text) + MAX_ROUNDS_SUFFIX`.
     - Yield `LoopEvent("done", final)` last, once.
  4. Every tool call goes through `tool_executor.execute_and_feedback(..., requester_role=requester_role)`. The loop does not check the role itself, does not call `execute_tool_call`, and never passes `approved`. The role and approval checks stay in the executor's single gate (rule 4).
- **Tests:** `test_tool_loop.py`, offline, with a fake `generate_round` that pops chunk lists from a queue and records `(loop_input, round_idx)`:
  - no tool calls: events are the deltas then `done`; `done.text` is the stripped text.
  - one tool round then none: events `delta..., separator, delta..., done`; second loop input is `"hello\n\n[Tool Execution Results]\n[Round 1]\nR1"`; `execute_and_feedback` awaited once with `requester_role` (parametrise `owner`/`guest`).
  - tool calls every round with `max_rounds=5`: 5 rounds, 4 separators, the last delta is `MAX_ROUNDS_SUFFIX`, `done.text` ends with it.
  - `seed_results="SEED"`: first loop input is `"hello\n\n[Tool Execution Results]\n[Seed]\nSEED"`.
  - `execute_and_feedback` returns `""`: loop stops after round 1, no separator.
  - a round text `'ok {"tool": "x", "arguments": {}}'` with no further calls: `done.text == "ok"`.
  - T1/T2 through the real executor: build a `ToolExecutor` with `__new__` and the fake db from `test_requester_role.py`; a round emits `{"tool": "t", "arguments": {"_runtime_approved": true, "force_execute": true, "x": 1}}`. With `requester_role="guest"` the fake tool is never called and the results contain `"Tool use is not available to this user."`. With `"owner"` the tool receives exactly `{"x": 1}`.
  Run the full suite.
- **Done when:** the new tests pass, the full suite passes, `grep -n "approved" src/aura/orchestrator/tool_loop.py` prints nothing, and `grep -n "execute_tool_call" src/aura/orchestrator/tool_loop.py` prints nothing.
- **Do not:** touch `coordinator.py` in this card. Do not add native function calling here (W2-37). Do not import the registry here.

---

**W2-32 `_generate_blocking` runs on the single loop**
- **PRD:** agency 5.2, G1
- **Tier:** frontier. Changes pinned behaviour on purpose; Mai reads (a) to (g) above before it merges.
- **Depends on:** W2-31
- **Files:** `src/aura/orchestrator/coordinator.py` (`_generate_blocking`, new `_forced_seed`), `tests/unit/test_turn_process_query.py`
- **Change:**
  1. Add `async def _forced_seed(self, user_input, tool_schema_str, requester_role) -> str | None` holding today's blocking seed block verbatim: call `l3_tool_call_mode(query=user_input, tool_schema=tool_schema_str)`, `extract_tool_calls`, and if calls exist, `execute_and_feedback(..., requester_role=requester_role)`. Return the results string, or `None` (with today's warning log) when there are no calls or no results.
  2. Rewrite the body of `_generate_blocking` (signature unchanged):
     - keep the `context_window_size` line and both log lines;
     - `seed = await self._forced_seed(...) if use_forced_tool_mode and tool_schema_str else None`;
     - define `async def _round(loop_input, round_idx)` that builds the same `SynthesisContext` as today (all fields, including `recent_critique=ctx.recent_critique` and `packet=ctx.packet`), awaits `l3_synthesis(loop_context, max_history_messages=context_window_size, reasoning_enabled=reasoning_enabled)`, publishes today's `L3 synthesis_complete` trace with `round=round_idx`, and yields the response once;
     - `async for event in run_tool_loop(user_input=user_input, generate_round=_round, tool_executor=self.tool_executor, requester_role=requester_role, seed_results=seed)`: keep only the `done` event's text and return it.
  3. Behaviour changes in this card: none on the blocking path, except that the round limit now comes from `settings.tool_loop_max_rounds` (default 5, same value). The response, suffix, stripping, seed block and telemetry are the same as today.
  4. Update the docstring to say it runs `run_tool_loop`.
- **Tests:** every test in `test_turn_process_query.py` must pass unchanged. If any of (i), (j), (l), W2-06 or the packet test fails, stop and report: this card must not change blocking behaviour. Run the full suite.
- **Done when:** the full suite passes with `test_turn_process_query.py` unchanged (`git diff --stat` does not list it), `grep -c "run_tool_loop" src/aura/orchestrator/coordinator.py` prints at least `1`, and `grep -n "max_tool_rounds" src/aura/orchestrator/coordinator.py` prints only lines inside `_generate_streaming`.
- **Do not:** touch `_generate_streaming`, `_turn_pipeline` or the `(chunk, counts)` contract yet. Do not delete `_remove_tool_calls_from_text` yet (W2-34).

---

**W2-33 `_generate_streaming` runs on the single loop**
- **PRD:** agency 5.2, G1
- **Tier:** frontier. This is the behaviour change of the milestone.
- **Depends on:** W2-32
- **Files:** `src/aura/orchestrator/coordinator.py` (`_generate_streaming`, `_turn_pipeline` stage 8), `tests/unit/test_turn_stream_query.py`, `tests/unit/test_turn_pipeline.py`
- **Change:**
  1. Rewrite `_generate_streaming` (same parameters) as an async generator of `LoopEvent`:
     - `seed = await self._forced_seed(...) if use_forced_tool_mode and tool_schema_str else None`;
     - `_round(loop_input, round_idx)` builds the loop `SynthesisContext` exactly as the blocking `_round` does (same fields, `recent_critique=ctx.recent_critique`, `packet=ctx.packet`), streams `stream_l3_synthesis(loop_context, reasoning_enabled=reasoning_enabled)` chunk by chunk, then publishes `L3 synthesis_complete` with `round=round_idx` and `"mode": "stream"`;
     - re-yield every event of `run_tool_loop(...)` unchanged.
  2. In `_turn_pipeline` stage 8, streaming branch: for `delta` and `separator` events yield `TurnEvent("delta", event.text)`; on `done`, set `response = event.text`. Remove the `full_response` / `counts` accumulation.
  3. **The behaviour changes this card makes on purpose.** List each one in the log:
     - (a) the stored response has tool-call JSON removed;
     - (b) the max-rounds suffix is yielded and stored on the stream path;
     - (c) no `"\n\n"` after the last round;
     - (d) the stored response is the final round only;
     - (e) forced mode seeds the loop; the `"I executed a tool for you"` prompt and the separate fallback follow-up are gone, and `ctx.synthesis_context.user_input` is no longer overwritten;
     - (f) per-round `L3 synthesis_complete` telemetry on the stream path.
  4. Update the characterisation tests deliberately. Change only these, and add the docstring line "changed on purpose by W2-33 (G1 single loop)" to each:
     - stream (e): chunks stay `["rou", "nd1", "\n\n", "rou", "nd2"]`; add that `_post_response_chain` receives `response == "round2"`.
     - stream (f): rename to `test_f_five_rounds_all_tool_calls_max_rounds_suffix`; assert 5 stream calls, exactly 4 `"\n\n"` chunks, and that the last chunk is `MAX_ROUNDS_SUFFIX`.
     - stream (g): rename to `test_g_forced_mode_seeds_loop`; assert `l3_tool_call_mode` awaited once, one stream call whose context `user_input == "hello\n\n[Tool Execution Results]\n[Seed]\nOUT"`, and `chunks == ["per", "sona"]`. Set `extract_tool_calls` to `side_effect=[["call"], []]`.
     - stream (h): rename to `test_h_forced_mode_no_raw_tool_calls_runs_plain_loop`; with `side_effect=[[], ["call2"], []]`, assert chunks `["re", "g", "\n\n", "fo", "llow"]` and the second context `user_input == "hello\n\n[Tool Execution Results]\n[Round 1]\nRES"`.
     - stream W2-06 forced-by-name: replace the `"I executed a tool for you."` assertions with the `[Seed]` input assertion as in (g).
     - pipeline (b): the `done` event now carries the final round's text; update that one expectation only.
     - Every other assertion stays as it is. `test_turn_process_query.py` is not touched.
- **Tests:** the updated files, plus in `test_turn_pipeline.py`: one test that the streaming and blocking pipelines, given the same fakes (one tool round, then a final answer `'done {"tool":"x"}'`), produce the same `done` text `"done"`. Run the full suite.
- **Done when:** the suite passes; `grep -n "I executed a tool for you\|max_tool_rounds\|counts" src/aura/orchestrator/coordinator.py` prints nothing; `grep -c "extract_tool_calls\|execute_and_feedback" src/aura/orchestrator/coordinator.py` prints `2` (both in `_forced_seed`).
- **Do not:** change `l3_tool_call_mode`, `_resolve_forced_tool` or `_classify_intent` (W2-38). Do not add `user_id` to the loop contexts. Do not change any test outside the list in step 4.

---

**W2-34 Remove what the old loops left behind**
- **PRD:** agency 5.2, section 10 rule 6 ("leaving no parallel old and new paths")
- **Tier:** bulk
- **Depends on:** W2-33
- **Files:** `src/aura/orchestrator/coordinator.py`, `tests/unit/test_turn_pipeline.py` (read)
- **Change:**
  1. Delete `Orchestrator._remove_tool_calls_from_text`. First confirm `grep -rn "_remove_tool_calls_from_text" src tests` lists only its `def`; if anything else calls it, stop and report.
  2. Update the docstrings of `_generate_blocking`, `_generate_streaming`, `TurnEvent` and `_turn_pipeline` that still mention "moved verbatim", the `(chunk, counts)` tuples or "separators excluded from full_response", so they describe `run_tool_loop` and `LoopEvent`.
  3. Remove imports that became unused in `coordinator.py` because of W2-32 and W2-33, and only those.
- **Tests:** run the full suite.
- **Done when:** the suite passes, `grep -rn "_remove_tool_calls_from_text" src tests` prints nothing, and `grep -n "counts" src/aura/orchestrator/coordinator.py` prints nothing.
- **Do not:** touch `agent_loop.py` (removed in G4). Do not merge `_generate_blocking` and `_generate_streaming` into one method; each is now a thin adapter over the one loop.

---

**W2-35 Offer the selected tools to the model**
- **PRD:** agency 5.2 (selection), T10, 5.3
- **Tier:** bulk
- **Depends on:** W2-30, W2-33
- **Files:** `src/aura/llm/layers.py` (`SynthesisContext.__init__`, `_build_l3_system_prompt`), `src/aura/orchestrator/coordinator.py` (`TurnContext`, `_turn_pipeline`, the `_round` helpers), `src/aura/main.py` (startup), `tests/conftest.py` (`turn_orchestrator`), new `tests/unit/test_offered_tools.py`
- **Change:**
  1. `SynthesisContext`: add a keyword argument `offered_tools: list | None = None` as the last parameter, stored as `self.offered_tools`.
  2. `_build_l3_system_prompt`: immediately before `<AGENT_ACTION_RULE>`, when `context.offered_tools` is non-empty, add:
     ```
     <available_tools>
       <tool name="{name}" risk="{risk}">{description}
         <input_schema>{json.dumps(input_schema, separators=(",", ":"))}</input_schema>
       </tool>
     </available_tools>
     ```
     one `<tool>` per record, in the order given. Nothing else in the prompt changes.
  3. `TurnContext`: add `offered_tools: list = field(default_factory=list)` as the last field.
  4. In `_turn_pipeline`, after stage 6, set `ctx.offered_tools = await get_tool_registry().select_tools(user_input, requester_role=requester_role)` inside `try/except` (on failure, log a warning and use `[]`). Pass `offered_tools=ctx.offered_tools` into both `_round` loop contexts.
  5. At startup in `main.py`, after the database is connected, `await get_tool_registry().refresh(db)` inside `try/except` with a warning. If there is no single obvious startup hook, stop and report.
  6. Fixture: in `turn_orchestrator`, monkeypatch `get_tool_registry` (as imported in `coordinator.py`) to return a fake whose `select_tools` is an `AsyncMock(return_value=[])`. Expose it as `orch._fake_tool_registry`.
- **Tests:** `test_offered_tools.py`:
  - T10 end to end: the fake registry returns 8 records; the first loop context has `offered_tools` equal to them, and `_build_l3_system_prompt` on that context contains 8 `<tool name=` entries and no `force_execute`.
  - `requester_role="guest"`: `select_tools` is awaited with `requester_role="guest"`.
  - `select_tools` raises: the turn completes, `offered_tools == []`, and the prompt has no `<available_tools>`.
  Run the full suite. Existing characterisation tests must pass unchanged.
- **Done when:** the new tests pass, the full suite passes, and `grep -c "offered_tools=ctx.offered_tools" src/aura/orchestrator/coordinator.py` prints `2`.
- **Do not:** change `<AGENT_ACTION_RULE>` or `<capabilities>` here (W2-38 handles the keyword wording). Do not call `select_tools` more than once per turn.

---

**W2-36 Native function calling in the model clients**
- **PRD:** agency 5.2 ("tool schemas go through the model API's tools parameter and structured calls come back")
- **Tier:** frontier. Touches every provider's request and response handling.
- **Files:** `src/aura/llm/provider.py`, `src/aura/llm/router.py`, `src/aura/llm/unified_provider.py`, `src/aura/llm/ollama_provider.py` (read; change only if `unified_provider` routes L3 to it), new `tests/unit/test_native_tool_calls.py`
- **Change:**
  1. In a new small module `src/aura/llm/tool_calls.py`: `@dataclass class ModelTurn: text: str; tool_calls: list[dict]` where each call is `{"tool": name, "arguments": dict, "id": str}` (the same `tool`/`arguments` shape `extract_tool_calls` returns, so the executor needs no change). `def to_openai_tools(records) -> list[dict]` maps `ToolRecord`s to `{"type": "function", "function": {"name", "description", "parameters": input_schema}}`. `def parse_openai_tool_calls(raw) -> list[dict]` parses `message.tool_calls`; arguments that are not valid JSON become `{}` with a warning, and the call is kept so the executor's repair can run.
  2. Each client gets `async def complete_with_tools(messages, model, tools, temperature, max_tokens, **kwargs) -> ModelTurn` that sends `tools` and `tool_choice: "auto"` in the OpenAI-format payload and reads `choices[0].message.content` and `.tool_calls`. Reuse each client's existing retry and fallback code; do not copy it.
  3. Each client gets `async def stream_with_tools(...)` that yields `("text", chunk)` for content deltas and, at the end, one `("tool_calls", list[dict])` built by joining `delta.tool_calls[i].function.arguments` fragments by index.
  4. `unified_provider` routes both methods like `complete` / `stream_complete`, including the local-to-cloud fallback.
  5. Config: `l3_native_tools: bool = False` (`AURA_L3_NATIVE_TOOLS`). Off by default, so nothing changes until Mai turns it on for a model known to support tools.
- **Tests:** with `httpx.MockTransport` (no network): a blocking response with one `tool_calls` entry becomes `ModelTurn(text="", tool_calls=[{"tool": "web_search", "arguments": {"query": "x"}, "id": "c1"}])`; a streamed response whose arguments arrive in three fragments gives one call with the joined arguments; malformed argument JSON gives `arguments == {}`; the request payload carries `tools` and `tool_choice`. Run the full suite.
- **Done when:** the new tests pass, the full suite passes, and `complete` / `stream_complete` are unchanged (`git diff` shows no edits inside them).
- **Do not:** change `complete` or `stream_complete`. Do not wire this into `layers` or the loop (W2-37). Do not add a dependency.

---

**W2-37 The single loop uses native calls when the model supports them**
- **PRD:** agency 5.2 (native first, text extraction as the fallback "so no model tier loses tool use")
- **Tier:** frontier
- **Depends on:** W2-35, W2-36
- **Files:** `src/aura/orchestrator/tool_loop.py`, `src/aura/llm/layers.py` (`l3_synthesis`, `stream_l3_synthesis`), `src/aura/orchestrator/coordinator.py` (the two `_round` helpers), `tests/unit/test_tool_loop.py`, `tests/unit/test_native_tool_calls.py`
- **Change:**
  1. `RoundFn` may now yield either `str` chunks or one final `NativeCalls(calls: list[dict])` marker (new dataclass in `tool_loop.py`). In `run_tool_loop`, if a round yields a `NativeCalls`, use its calls; otherwise use `tool_executor.extract_tool_calls(round_text)` as today. Everything after that (execution through `execute_and_feedback` with `requester_role`, blocks, separators, suffix, `done`) is unchanged.
  2. `l3_synthesis` and `stream_l3_synthesis` take `tools: list | None = None`. When `tools` and `settings.l3_native_tools` are both truthy, call `complete_with_tools` / `stream_with_tools` with `to_openai_tools(tools)`. The blocking method then returns the `ModelTurn`; the streaming method yields text chunks and finally the `NativeCalls` marker. Otherwise, behaviour is exactly as today.
  3. The `_round` helpers pass `tools=ctx.offered_tools`. When the flag is on, the blocking `_round` yields `turn.text`, then `NativeCalls(turn.tool_calls)` if any.
  4. When the flag is on, `<available_tools>` is not added to the prompt (the schemas travel in the API parameter).
  5. If a native call raises a provider error (for example 400 "tools not supported"), log a warning and fall back to today's text call for that round.
- **Tests:** in `test_tool_loop.py`: a round yielding `NativeCalls([...])` executes them without calling `extract_tool_calls`; a guest role still reaches `execute_and_feedback` with `requester_role="guest"` and is refused by the real executor. In `test_native_tool_calls.py`: with the flag off, `l3_synthesis(..., tools=[...])` calls `complete`, not `complete_with_tools`; with it on, the reverse; a `complete_with_tools` error falls back to `complete`. Run the full suite; the characterisation tests pass unchanged (the flag is off by default).
- **Done when:** the new tests pass, the full suite passes, and `grep -n "l3_native_tools" src/aura/llm/layers.py` prints at least two lines.
- **Do not:** turn the flag on by default. Do not remove the text extraction path.

---

**W2-38 Remove the keyword intent rule; forced mode only from the trigger fast lane**
- **PRD:** agency 5.2 ("The keyword intent rule (G4) is removed. The model decides whether to call a tool. The fast lane stays for exact matches on learned trigger phrases."), finding G4
- **Tier:** frontier. Changes routing on purpose.
- **Depends on:** W2-33, W2-35 (the model must see tools before the keyword crutch goes)
- **Files:** `src/aura/orchestrator/coordinator.py` (`_classify_intent`, `_resolve_forced_tool`), `src/aura/llm/layers.py` (`l1_classify_intent` prompt, `<AGENT_ACTION_RULE>` in `_build_l3_system_prompt`), `tests/unit/test_turn_process_query.py`, `tests/unit/test_turn_stream_query.py`
- **Change:**
  1. In `_classify_intent`, delete the `# FALLBACK: ... keyword-based detection` block (the `tool_keywords` list and everything under it). Keep the L1 call, its telemetry and the teaching lane.
  2. In the `l1_classify_intent` prompt, delete the line starting `IMPORTANT: If the user mentions "search", "stock", ...`. Keep the vector-search fast lane (`semantic_trigger`, `routing_method: "vector_search"`) unchanged.
  3. In `_resolve_forced_tool`, return `(False, None)` at the start unless `intent_data.get("routing_method") == "vector_search"`. This keeps the forced seed only for learned trigger phrases; for every other turn the model decides with the offered tools.
  4. In `<AGENT_ACTION_RULE>`, replace the sentence `If the user query contains keywords like 'search', 'current price', 'read file', 'source code', 'inspect', or requests information that requires tool access, you MUST NOT use internal knowledge.` with `If answering needs information or an action that one of the available tools provides, you MUST NOT use internal knowledge.` Keep the rest of the block.
  5. **Behaviour changes this card makes on purpose:** (i) "weather", "search", "price" and the other keywords no longer turn a CHAT intent into TOOL_USE; (ii) an L1 LLM classification of TOOL_USE no longer forces a tool call; only a trigger-phrase match does; (iii) the L1 and L3 prompts no longer push tool use on keywords.
  6. Update the characterisation tests deliberately, each with the docstring line "changed on purpose by W2-38 (G1, keyword rule removed)":
     - process (k): rename to `test_k_weather_stays_chat`; assert `l3_tool_call_mode` not awaited and the `[MAG]` intent path is not taken (`learning_engine.get_skill` and `db.query` for `skill` not awaited).
     - process (l), process W2-06, stream (g), stream (h), stream W2-06: add `"routing_method": "vector_search"` to the L1 return value so they still exercise the forced seed. Change nothing else in them.
     - add `test_llm_tool_use_without_trigger_does_not_force` in `test_turn_process_query.py`: L1 returns `{"intent": "TOOL_USE", "target_action": "skill:x"}` without `routing_method`; `l3_tool_call_mode` is not awaited and one L3 synthesis runs.
- **Tests:** the updated files. Run the full suite.
- **Done when:** the suite passes; `grep -n "tool_keywords\|Keyword-based TOOL_USE" src/aura/orchestrator/coordinator.py` prints nothing; `grep -n "If the user mentions \"search\"\|keywords like 'search'" src/aura/llm/layers.py` prints nothing.
- **Do not:** remove `semantic_trigger` or the vector fast lane. Do not delete `_resolve_forced_tool`'s lookup code or `l3_tool_call_mode`. Do not touch the TEACHING lane.

---

**Order and dependencies:** W2-28 -> W2-29 and W2-30 (either order). W2-31 can run alongside W2-28. Then W2-32 -> W2-33 -> W2-34. W2-35 needs W2-30 and W2-33. W2-36 can run any time. W2-37 needs W2-35 and W2-36. W2-38 needs W2-33 and W2-35. The suite is green after every card.

**G1 gate:** T10 passes (W2-30 unit, W2-35 end to end); T1 and T2 pass through the single loop (W2-31); `grep -rn "extract_tool_calls\|execute_and_feedback" src/aura/orchestrator/coordinator.py` lists only `_forced_seed`; the remaining caller of `extract_tool_calls` outside the loop is `agent_loop.py`, which G4 deletes.

---

### Bug fixes after wave 2: cards (night 3, Part 2)

Written by the supervisor against the code on overnight-wave-0-1. Done-when lines use tests, or greps anchored to code constructs that cannot match comments or prose.

---

**BF-01 The fifth edge query with FETCH before LIMIT**
- **PRD:** memory (retrieval). Missed by W2-26.
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py` (`_fetch_thought_cluster`, the `next_experience` after-traversal query that ends `FETCH out LIMIT 2`), new `tests/scenarios/test_after_traversal_clause_order_embedded.py`. Read `tests/scenarios/test_edge_queries_clause_order_embedded.py` (W2-26) and copy its pattern.
- **Change:** in that query, move `LIMIT 2` before `FETCH out`, so it ends `LIMIT 2 FETCH out`. Keep every other token, parameter name and binding unchanged.
- **Tests:** following W2-26, run the new query string on the embedded engine with suitable empty bindings and assert it does not raise; run the old string and assert it raises. Run the full suite.
- **Done when:** the new test passes and the full suite passes.
- **Do not:** change any other query, or the try/except around it.

---

**BF-02 Pin and unpin report a failed database write**
- **PRD:** memory F3 (follow-up to W1-10).
- **Tier:** bulk
- **Files:** `src/aura/engines/memory/manager.py` (`set_core`), `src/aura/api/routes/memory.py` (the `POST /memory/{memory_id}/pin` and `/unpin` routes), `tests/unit/test_set_core.py`.
- **Change:**
  1. In `set_core`, keep the `logger.error(...)` line but re-raise the exception after logging it, so callers can see the failure.
  2. In both routes, catch the exception from `set_core` and return HTTP 500 with a JSON body `{"error": "Failed to update the memory", "memory_id": <id>}`. Follow the error-response style the file already uses.
- **Tests:** a fake database whose `merge` raises makes `set_core` raise; the pin route and the unpin route each return 500 with that body when `set_core` raises (call the route handlers directly, or use FastAPI's TestClient if it is already available). The existing pin/unpin success tests still pass.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change what `set_core` writes on success.

---

**BF-03 Baseline files are written only on request**
- **PRD:** build plan W0-04 and W0-05 (follow-up).
- **Tier:** bulk
- **Files:** `tests/scenarios/test_emotion_baseline_record.py` (W0-04), `tests/scenarios/test_memory_horizon_record.py` (W0-05). If `tests/scenarios/test_emotion_after_record.py` (W1-15) writes a file the same way, apply the same change there.
- **Change:** each recording test still computes its measurements and still runs every assertion, but writes its JSON file only when the environment variable `RECORD_BASELINE` equals `"1"`. Otherwise it leaves the file untouched. Read the variable with `os.environ.get("RECORD_BASELINE") == "1"` inside the test.
- **Tests:** add one unit test that runs the recording function with `RECORD_BASELINE` unset (use `monkeypatch.delenv`) and asserts the target file's content and modification time are unchanged, and one with `RECORD_BASELINE=1` that writes to a temporary path (use `tmp_path`; refactor only as much as needed to pass the output path in). Run the full suite twice and check that `git status --short Aura-Core/aura-app/docs/metrics/` prints nothing afterwards.
- **Done when:** the new tests pass, the full suite passes, and after a full suite run `git status --short Aura-Core/aura-app/docs/metrics/` is empty.
- **Do not:** change any measured value or the JSON format. Do not regenerate the committed baseline files.
- **Supervisor note (first attempt rejected, reverted):** the first attempt passed its own tests but did not fix the leak. With `RECORD_BASELINE` unset, running only `.venv\Scripts\python.exe -m pytest tests/scenarios/test_emotion_baseline_record.py` still rewrote `docs/metrics/emotion_before.json` (new mtime and new values), and the same for `test_memory_horizon_record.py` and `memory_before.json`. Its new tests re-implemented the `RECORD_BASELINE` check inside the test body instead of calling the code that writes the file, so they could not catch this. This time: (1) find every place that writes these files, including helpers and fixtures, and route every write through one function `write_baseline(path, data)` that writes only when `RECORD_BASELINE == "1"`; (2) the new tests must call that same function (and the recording test itself) and check the real file; (3) before committing, run `git checkout -- docs/metrics/`, then run each recording test file on its own and then the full suite, and confirm with `git status --short docs/metrics/` that nothing changed. Do not restore the files before that check.

---

**BF-04 A valid IdentityContext in the stream fallback**
- **PRD:** behaviour B0 follow-up.
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py` (`_gather_turn_context`, the streaming branch's fallbacks), `src/aura/models/identity.py` (read only), `tests/unit/test_turn_stream_query.py`.
- **Change:** the streaming branch builds `IdentityContext(core_identity="Aura", tone_and_style="Helpful")` in two places (the timeout fallback and the per-result fallback). `IdentityContext` has no such fields: its required fields are `narrative: str` and `core_values: dict[str, float]`, so this raises a validation error the moment the fallback runs. Replace both with `IdentityContext(narrative="I am Aura.", core_values={})`.
- **Tests:** two tests that force each fallback: (a) the identity call raises, so the per-result fallback is used; (b) the context gathering times out (patch `asyncio.wait_for` or the timeout so it raises `asyncio.TimeoutError` immediately, no real sleeping). In both, the stream completes and the L3 context's `identity_context` is an `IdentityContext` whose `narrative == "I am Aura."`.
- **Done when:** the new tests pass, the full suite passes, and `grep -nE "IdentityContext\(core_identity=" src/aura/orchestrator/coordinator.py` prints nothing.
- **Do not:** change the non-stream path or the timeout value.

---

**BF-05 Memory reads time through the clock provider**
- **PRD:** memory section 8.1 (injectable clock); build plan rule 7. Listed by the scenario runner in W2-01.
- **Tier:** bulk
- **Files:** `src/aura/models/memory.py` (the `Memory` model's `timestamp` default), `src/aura/engines/memory/manager.py` (`_compute_decay_factor`), `src/aura/clock.py` (read only).
- **Change:** replace every direct time read in those two places (`datetime.utcnow()`, `datetime.now(...)`, `time.time()`) with `get_clock().now()` from `aura.clock`. Where the old value was naive (no timezone), keep it naive with `get_clock().now().replace(tzinfo=None)`, so stored and compared values keep their current form. For a pydantic field default, use `default_factory=lambda: <the same expression>`.
- **Tests:** with `FakeClock` installed through `set_clock`: a new `Memory()` gets the fake clock's time as its timestamp; `_compute_decay_factor` on a memory whose timestamp is the fake "now" minus 30 days gives the same value as the old code gave for a real 30-day-old memory (compute the expected value from the formula, do not hardcode a number taken from the old run).
- **Done when:** the new tests pass, the full suite passes, and `grep -nE "datetime\.(utcnow|now)\(|time\.time\(" src/aura/models/memory.py` prints nothing and the same grep limited to the body of `_compute_decay_factor` prints nothing.
- **Do not:** change any decay formula or constant.

---

**BF-06 Dreaming reads time through the clock provider, and a 30-day scenario test**
- **PRD:** memory section 8.1; build plan rule 7. Depends on BF-05.
- **Tier:** bulk
- **Files:** `src/aura/engines/dreaming/engine.py` (`_tiered_pruning`, `_compute_decay`, `_weave_causality`, `_emotional_reprocessing`), new `tests/scenarios/test_clock_thirty_days.py`. Read `tests/scenarios/runner.py`.
- **Change:** replace every direct time read in those four functions with `get_clock().now()`, keeping naive values naive as in BF-05.
- **Tests:** a scenario test using the runner: on day 0 store a memory; advance the fake clock to day 30; assert that the memory's age as computed by `DreamingEngine._compute_decay` (and `MemoryManager._compute_decay_factor`) is that of a 30-day-old memory (compare with the value the formula gives for 30 days), and that a dream cycle at day 30 sees it as 30 days old. Run the full suite.
- **Done when:** the new test passes, the full suite passes, and none of the four function bodies contains `datetime.utcnow(`, `datetime.now(` or `time.time(` (check with a small Python snippet using `inspect.getsource` on each function, printed in your log entry).
- **Do not:** change any pruning threshold, decay formula or query.

---

**BF-07 Find what hides the missing frontend files**
- **PRD:** V0 prerequisite (W2-25 stopped twice on a broken frontend build).
- **Tier:** bulk
- **Files:** the repository root `.gitignore` only. Read the W2-25 entries in `docs/overnight-log.md`.
- **Change:**
  1. From the repository root run `git check-ignore -v` for `Aura-Core/aura-app/frontend/src/lib/utils.ts` and for the two modules the frontend build cannot resolve: find their expected paths from the import lines that W2-25 reported (`../../lib/VRMAnimation/loadVRMAnimation` and `../../lib/VRMLookAtSmootherLoaderPlugin/VRMLookAtSmootherLoaderPlugin`, resolved relative to the files that import them). Record the exact output in the log.
  2. If a `.gitignore` rule matches them, narrow that rule so it can no longer match anything under `Aura-Core/aura-app/frontend/src/` (for example anchor the Python `lib/` rule to the paths it was meant for, such as `/lib/` and `Aura-Core/aura-app/lib/`, and remove the now redundant `!Aura-Core/aura-app/frontend/src/lib/` exception if it is no longer needed). Run `git check-ignore -v` again and record that the files are no longer ignored.
  3. In the log, list the missing files by their full repository paths for Mai: they must come from his old working copy.
- **Tests:** run the full Python suite (unchanged).
- **Done when:** `git check-ignore -q` exits non-zero for all three paths, and the full suite passes.
- **Do not:** recreate, stub or download the missing files. Do not touch anything under `frontend/`.

---


### Wave 3: cards for M3 (indexes, channels, fusion, query building, gate, abstention)

Written by the supervisor on 2026-11-20 against the code at the end of wave 2. M3 works on today's `memory` table: schema v2 (`fact`, `episode`, `entity`) is M4, and the entity, graph and temporal channels are M5. Every mechanism ships behind its own config flag, off by default (memory PRD rule 7); turning them on is a decision for Mai after W3-08.

SurrealDB syntax below was checked on the installed embedded engine (surrealdb 3.0.0) on 2026-11-20:
- Full-text: `DEFINE ANALYZER ... TOKENIZERS class FILTERS lowercase, ascii, snowball(english)` and `DEFINE INDEX ... FIELDS content FULLTEXT ANALYZER <name> BM25 HIGHLIGHTS`. The older `SEARCH ANALYZER` form is a parse error. Match with `content @1,OR@ $text` and score with `search::score(1)`. Plain `@1@` requires every word to match, so a sentence matches nothing: always use `@1,OR@`.
- KNN: `WHERE <filters> AND embedding <|20,40|> $vec` with `vector::distance::knn() AS distance`, `ORDER BY distance`. Filters are applied before the k nearest are chosen. `k` and `ef` must be integer literals: a parameter is a parse error. They come from config and are inserted with `int(...)`; this is the only allowed formatting into a query string, and only for integers from config.

---

**W3-01 A full-text index on memory content**
- **PRD:** memory 4.5 (indexes), M3
- **Tier:** bulk
- **Files:** `scripts/init_schema.surql`, new `tests/scenarios/test_memory_fulltext_index_embedded.py`. Read `tests/scenarios/runner.py` (how the schema is applied to the embedded engine) and `tests/scenarios/test_edge_queries_clause_order_embedded.py` (pattern).
- **Change:** in `init_schema.surql`, right after the `memory_embedding` HNSW index line, add:
  ```
  DEFINE ANALYZER OVERWRITE memory_text TOKENIZERS class FILTERS lowercase, ascii, snowball(english);
  DEFINE INDEX OVERWRITE memory_content_ft ON memory FIELDS content FULLTEXT ANALYZER memory_text BM25 HIGHLIGHTS;
  ```
  If `OVERWRITE` is rejected by the embedded engine, use `IF NOT EXISTS` instead and say so in the log.
- **Tests:** on the embedded engine with the real `init_schema.surql` applied (as the runner does): create three memories (`"Mai likes the Rust language"`, `"The cat sleeps on the sofa"`, `"function parse_route in config.rs"`); `SELECT id, search::score(1) AS score FROM memory WHERE content @1,OR@ $t ORDER BY score DESC` with `$t = "what do you know about rust?"` returns the Rust memory first; `"parse_route"` returns the third; `"sleeping cats"` returns the second (stemming). Applying the schema file twice does not raise. Run the full suite.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change any other index or field. Do not touch the existing HNSW index.

---

**W3-02 Dense and lexical candidate channels**
- **PRD:** memory 6.3 step 3 (dense and lexical rows), M3
- **Tier:** bulk
- **Depends on:** W3-01
- **Files:** new `src/aura/engines/recall/channels.py`, `src/aura/config.py`, new `tests/scenarios/test_recall_channels_embedded.py`. Read `MemoryManager.retrieve_memories` in `src/aura/engines/memory/manager.py` for today's filter conditions.
- **Change:**
  1. Config, next to the other `recall_*` settings: `recall_dense_k: int = 20`, `recall_dense_ef: int = 40`, `recall_lexical_k: int = 20`, each a `Field` with a one-line description like its neighbours.
  2. In `channels.py`, a dataclass `ChannelHit(memory_id: str, rank: int, score: float)` (rank from 0; for dense, `score` is cosine similarity `1 - distance`; for lexical, the BM25 score) and two functions:
     - `async def dense_channel(db, embedding: list[float] | None, user_id: str | None, namespace: str | None) -> list[ChannelHit]`
     - `async def lexical_channel(db, text: str, user_id: str | None, namespace: str | None) -> list[ChannelHit]`
  3. Both apply the same filters as `retrieve_memories`: `deprecated = false AND ephemeral = false`, `user_id = $user_id` when given, and the same namespace rule. Dense uses `embedding <|{int(settings.recall_dense_k)},{int(settings.recall_dense_ef)}|> $vec` with `vector::distance::knn() AS distance`, `ORDER BY distance`. Lexical uses `content @1,OR@ $text`, `search::score(1) AS score`, `ORDER BY score DESC LIMIT $k`. Every other value is a query parameter.
  4. Empty `text` or `None` embedding returns `[]` without querying. A database error propagates (the caller handles it).
- **Tests:** on the embedded engine with the real schema and the runner's `HashedBagOfWordsEmbeddings`: dense returns the nearest memory first; lexical finds a memory by a code symbol (`parse_route`) and by a name; the `user_id` filter excludes another user's memories in both channels; a deprecated memory never appears; empty input returns `[]`. Run the full suite.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** wire the channels into the engine (W3-05). Do not change `MemoryManager`.

---

**W3-03 Query building**
- **PRD:** memory 6.3 step 2, M3
- **Tier:** bulk
- **Files:** new `src/aura/engines/recall/query.py`, `src/aura/config.py`, new `tests/unit/test_recall_query.py`
- **Change:**
  1. Config: `recall_query_join_max_words: int = 6`.
  2. `@dataclass class RecallQueries: dense_text: str; lexical_text: str; joined: bool`.
  3. `def build_queries(user_input: str, recent_turns: list[dict[str, str]]) -> RecallQueries`. No model call.
     - `previous` is the content of the last turn in `recent_turns` whose `role` is `"user"` and whose content differs from `user_input` (the pipeline passes history that may already end with the current input).
     - Join when `previous` exists and either the input has at most `recall_query_join_max_words` words, or it contains one of the pronouns `it, this, that, they, them, he, she, him, her, those, these` as a whole word (case-insensitive). `dense_text` is then `previous + "\n" + user_input`, else `user_input`.
     - `lexical_text` is `dense_text` with English stop words removed (a module-level `frozenset` of about 100 common words, including question words and the pronouns above), whitespace-collapsed. If nothing is left, `lexical_text` is `""`.
  4. Entities and date ranges (the other two query kinds in 6.3) wait for M4 and M5; say so in the module docstring.
- **Tests:** a long, self-contained input is not joined; `"and what about it?"` after a user turn about Rust is joined; a short input with no previous user turn is not joined; the current input repeated as the last history item is not used as `previous`; stop words are removed from `lexical_text` but kept in `dense_text`; an all-stop-word input gives `lexical_text == ""`.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** call a model or the database.

---

**W3-04 Reciprocal Rank Fusion**
- **PRD:** memory 6.3 step 4, M3
- **Tier:** bulk
- **Depends on:** W3-02 (`ChannelHit`)
- **Files:** new `src/aura/engines/recall/fusion.py`, `src/aura/config.py`, new `tests/unit/test_recall_fusion.py`
- **Change:**
  1. Config: `recall_rrf_k: int = 60`.
  2. `@dataclass class FusedHit: memory_id: str; score: float; channel_ranks: dict[str, int]; channel_scores: dict[str, float]`.
  3. `def rrf(channels: dict[str, list[ChannelHit]], k: int | None = None) -> list[FusedHit]`: score is the sum over channels of `1 / (k + rank + 1)`; `channel_ranks` and `channel_scores` hold each channel's rank and raw score for that id. Sorted by score descending, ties broken by the best (lowest) rank across channels, then by `memory_id`, so the order is deterministic. `k=None` uses config.
- **Tests:** an id found by two channels outranks ids found by one at the same ranks; the exact score of a hand-computed example; deterministic tie-breaking; empty input gives `[]`.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add weights per channel (not in the PRD).

---

**W3-05 The memories block runs on the new channels (flagged)**
- **PRD:** memory 6.3 steps 2 to 4, rule 7, M3
- **Tier:** frontier
- **Depends on:** W3-02, W3-03, W3-04
- **Files:** `src/aura/engines/recall/engine.py` (`_build_memories`), `src/aura/engines/recall/models.py` (`TraceItem`), `src/aura/engines/recall/assembly.py` (only to copy the two new trace fields from the candidate), `src/aura/config.py`, new `tests/scenarios/test_recall_channels_wired_embedded.py`
- **Change:**
  1. Config: `recall_channels_enabled: bool = False` (`AURA_RECALL_CHANNELS_ENABLED`).
  2. `TraceItem`: add optional `channel_ranks: dict[str, int] | None = None` and `fused_score: float | None = None` as the last fields. `Candidate` gets the same two optional fields, and `assemble` copies them into the trace item.
  3. In `_build_memories`, when the flag is on: `build_queries(request.user_input, request.recent_turns)`; embed `dense_text` with the memory manager's embeddings client; run `dense_channel` and `lexical_channel` together with `asyncio.gather(..., return_exceptions=True)`; `rrf` the two; take the first `request.limit`; load those memories with one parameterised `SELECT * FROM memory WHERE id IN $ids` and build `Memory` objects the way `retrieve_memories` does, keeping the fused order. Candidates get `source="recall.channels"`, `channel_ranks` and `fused_score`. Render with `memory_manager._format_memories_xml(payloads, {})` (no thought clusters on this path; they belong to the M5 graph channel).
  4. One channel failing records `channel_errors["memories.dense"]` or `channel_errors["memories.lexical"]`, and the other channel's hits are still used.
  5. Flag off: exactly today's path. Nothing else in the engine changes.
- **Tests:** on the embedded engine, with the runner's stub embeddings and seeded memories: with the flag on, a name that only the lexical channel can find reaches the memories block; the trace items carry `channel_ranks` and `fused_score`; the dense channel raising still yields lexical results and records the error; with the flag off, `retrieve_for_l3_parts` is called and the channels are not (ablation). Run the full suite; characterisation tests pass unchanged.
- **Done when:** the new tests pass, the full suite passes, and `grep -n "settings.recall_channels_enabled" src/aura/engines/recall/engine.py` prints at least one line.
- **Do not:** turn the flag on by default. Do not change `MemoryManager` or the other three blocks. Do not add a model call.

---

**W3-06 The recall gate (flagged)**
- **PRD:** memory 6.3 step 1, M3
- **Tier:** bulk
- **Depends on:** W3-05
- **Files:** new `src/aura/engines/recall/gate.py`, `src/aura/engines/recall/engine.py`, `src/aura/engines/recall/models.py` (`RecallTrace`), `src/aura/config.py`, new `tests/unit/test_recall_gate.py`
- **Change:**
  1. Config: `recall_gate_enabled: bool = False`; `recall_gate_phrases: list[str]` defaulting to greetings and acknowledgements (`hi`, `hello`, `hey`, `thanks`, `thank you`, `ok`, `okay`, `cool`, `nice`, `great`, `got it`, `good morning`, `good night`, `bye`, `lol`, `yes`, `no`).
  2. `def needs_recall(user_input: str) -> bool`: `False` when the input, lowercased and stripped of punctuation and surrounding whitespace, is empty or equals one of the phrases; `True` otherwise. Rules only.
  3. In the engine, when the flag is on and `needs_recall` is `False`, the memories block reuses the memories candidates of the last packet built for the same `(user_id, session_id)` (kept in a small dict on the engine, at most 200 entries, oldest dropped first). `RecallTrace` gets a new optional last field `gate: str | None = None`: `"skipped"` when the gate skipped retrieval, `"ran"` when it ran, `None` when the flag is off. With no previous packet, the block is empty. The insights, latent and cold-start blocks are not gated.
- **Tests:** each phrase skips; punctuation and case are ignored; a question runs; with the flag on, a greeting after a real turn reuses the previous memories and does not call the memories retrieval (assert the mock was not awaited); the cache drops the oldest entry past 200; with the flag off nothing changes (ablation).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add a classifier or a model call.

---

**W3-07 Abstention (flagged)**
- **PRD:** memory 6.3 step 7, M3
- **Tier:** bulk
- **Depends on:** W3-05
- **Files:** `src/aura/engines/recall/engine.py`, `src/aura/config.py`, new `tests/unit/test_recall_abstain.py`
- **Change:**
  1. Config: `recall_abstain_enabled: bool = False`; `recall_abstain_min_similarity: float = 0.55` with a description saying it must be tuned for the embedding model in use.
  2. Only on the channels path (W3-05) and only when the flag is on: `abstain` is `True` when the lexical channel returned no hits and the best dense similarity is below the threshold (or the dense channel returned nothing). The lexical channel searches without stop words (W3-03), so any lexical hit is a content-word match.
  3. When abstaining, the memories block text is the single line `<memories abstain="true">Nothing relevant to this message is stored in memory. Do not claim to remember anything about it.</memories>` and the packet's `abstain` is `True`. The callers already read `packet.block_text("memories")`, so the note reaches the prompt with no change in `layers.py`.
  4. When the gate skipped retrieval (W3-06), never abstain.
- **Tests:** an unrelated query against seeded memories abstains and produces exactly that line; a query with a lexical hit does not abstain even if the dense similarity is low; a dense similarity above the threshold does not abstain; flag off gives `abstain == False` (ablation).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change `layers.py`. Do not abstain on the old (flag off) path.

---

**W3-08 Noise and abstention scenarios, and latency**
- **PRD:** memory M3 gate ("noise and abstention probes pass"), 6.2 (fast path under 250 ms at p95), 8.3
- **Tier:** bulk
- **Depends on:** W3-06, W3-07
- **Files:** new `tests/scenarios/test_recall_m3_embedded.py`, new `docs/metrics/m3.md`. Read `tests/scenarios/runner.py` and `docs/metrics/probes/README.md` (the probe set is still a placeholder; these scenarios stand in for its noise and abstention probes until Mai provides real ones).
- **Change:** scenario tests through the runner, all three M3 flags on (set with `monkeypatch`), the runner's stub embeddings:
  - **Noise:** store 30 unrelated memories plus one saying `"Mai's cat is called Pixel"`; the question `"what is my cat called?"` puts the Pixel memory in the memories block.
  - **Lexical:** a memory mentioning `parse_route` is found by the question `"where is parse_route defined?"`.
  - **Abstention:** the question `"what is my favourite mountain?"` (nothing stored about it) abstains with the note line; the Pixel question does not.
  - **Gate:** `"thanks!"` after the Pixel question skips retrieval and reuses the Pixel memory.
  - **Latency:** time 50 `recall()` calls of the fast path (flags on, 200 seeded memories) with `time.perf_counter`, and write p50 and p95 with the date to `docs/metrics/m3.md` only when `RECORD_BASELINE=1` (reuse `write_baseline` from `tests/conftest.py`). The test asserts nothing about the numbers; it records them.
- **Tests:** these are the tests. Run the full suite, then once with `RECORD_BASELINE=1` to write `docs/metrics/m3.md`, and commit that file.
- **Done when:** the new tests pass, the full suite passes, and `docs/metrics/m3.md` exists with p50, p95 and the date.
- **Do not:** change any flag default. Do not tune thresholds to make a test pass; if a scenario fails, report it.

---


### Wave 3: cards for M4 (schema v2, extraction, entity resolution, supersession, speakers and visibility)

Written by the supervisor on 2026-11-20 against the code after M3. The v2 tables live in the same database as today's tables under new names (`episode`, `fact`, `entity`, `question`, `theme`, `prediction` do not clash with any existing table), so nothing is migrated (PRD section 9: fresh start). Today's `memory` path keeps running; the old tables are deleted only after the v2 probes pass, in a later card. Everything new is behind two flags, both off: `memory_v2_write_enabled` (episodes, extraction and facts) and `memory_v2_recall_enabled` (the Recall Engine reads facts).

The extraction model is PRD open item 12.1 and Mai's decision: `memory_extraction_model`, empty by default, which means "use `settings.l2_model`".

SurrealDB syntax checked on the installed embedded engine on 2026-11-20: `DEFINE TABLE IF NOT EXISTS x SCHEMAFULL`; typed relations `DEFINE TABLE IF NOT EXISTS derived_from TYPE RELATION FROM fact TO episode SCHEMAFULL` (the engine rejects an edge to the wrong table); `TYPE record<entity>`, `option<datetime>`, `array<string> DEFAULT []`; `ASSERT $value IN [...]`; `RELATE a->edge->b`; `WHERE aliases CONTAINS $a`; `WHERE valid_to IS NONE`. HNSW and FULLTEXT as in the M3 notes.

---

**W3-09 Schema v2**
- **PRD:** memory 4.1 to 4.5, M4
- **Tier:** bulk
- **Files:** new `scripts/schema_v2.surql`, `src/aura/main.py` (the startup script list), `tests/scenarios/runner.py` (apply the new file after `init_schema.surql`), new `tests/scenarios/test_schema_v2_embedded.py`
- **Change:**
  1. `schema_v2.surql`, every statement with `IF NOT EXISTS`:
     - `entity` SCHEMAFULL: `name` string, `type` string ASSERT in `person, project, place, tool, concept, other`, `aliases` array<string> DEFAULT [] (stored lowercased), `summary` option<string>, `embedding` option<array<float, 768>>, `created_at` datetime.
     - `episode` SCHEMAFULL: `user_text` string, `aura_text` string, `speaker` record<entity>, `venue` string, `conversation_id` option<string>, `embedding` option<array<float, 768>>, `emotional_signature` object FLEXIBLE DEFAULT {}, `salience` float DEFAULT 0, `ephemeral` bool DEFAULT false, `recorded_at` datetime, `extraction_status` string DEFAULT "pending" ASSERT in `pending, done, failed, skipped`, `extraction_attempts` int DEFAULT 0, `extraction_error` option<string>.
     - `fact` SCHEMAFULL with the fields of PRD 4.2: `content`, `kind` (ASSERT in `fact, preference, pattern, decision, event`), `subject` option<string>, `predicate` option<string>, `object` option<string>, `provenance` (ASSERT in `observed, hearsay, inferred, imagined, external`), `visibility` string, `confidence` float ASSERT 0..1, `valid_from` option<datetime>, `valid_to` option<datetime>, `recorded_at` datetime, `embedding` option<array<float, 768>>, `salience` float DEFAULT 0, `pinned` bool DEFAULT false, `use_count` int DEFAULT 0, `last_used_at` option<datetime>.
     - `question` SCHEMAFULL: `content` string, `visibility` string, `status` string DEFAULT "open", `recorded_at` datetime. `theme` and `prediction`: SCHEMAFULL with `content` string, `recorded_at` datetime and, for `prediction`, `outcome` option<string> and `error` option<float>. (Used by later milestones; defined now so the schema is complete.)
     - Typed relations from PRD 4.3: `derived_from` fact→episode, `about` fact→entity, `mentions` episode→entity, `next` episode→episode, `supersedes` fact→fact, `contradicts` fact→fact, `answers` fact→question. `led_to`, `member_of`, `co_used` and `abstracted_into` are left for M5 to M7.
     - Indexes (PRD 4.5): HNSW DIMENSION 768 TYPE F32 DIST COSINE on `fact.embedding`, `episode.embedding`, `entity.embedding`; one analyzer `v2_text` (as `memory_text` in W3-01) and FULLTEXT BM25 indexes on `fact.content`, `episode.user_text`, `entity.name`; standard indexes on `fact.visibility`, `fact.valid_to`, `fact.provenance`, `fact.recorded_at`, `entity.aliases`, `episode.venue`, `episode.extraction_status`.
  2. `main.py`: add `("schema_v2.surql", "Memory v2 schema")` after `init_schema.surql`. The runner applies it the same way.
- **Tests:** on the embedded engine with both schema files applied: applying `schema_v2.surql` twice does not raise; an `entity`, an `episode` and a `fact` can be created and related with `derived_from` and `about`; `derived_from` to an `entity` is rejected; a `fact` with provenance `"guess"` is rejected; a KNN query on `fact.embedding` and a `@1,OR@` query on `fact.content` both return the created fact. Run the full suite.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change `init_schema.surql` or any existing table.

---

**W3-10 Venue and speaker reach the turn**
- **PRD:** memory 4.4, M4
- **Tier:** bulk
- **Files:** `src/aura/orchestrator/coordinator.py` (`process_query`, `stream_query`, `_turn_pipeline`, `TurnContext`), `src/aura/discord/bot.py` (the `process_query` call around line 630), new `src/aura/engines/memory/v2/__init__.py`, new `src/aura/engines/memory/v2/identity.py`, new `tests/unit/test_memory_v2_identity.py`
- **Change:**
  1. `identity.py`: `def speaker_key(user_id: str, requester_role: str) -> str` returns `"owner"` when `requester_role == "owner"`, otherwise `user_id` (Discord users are already `discord_<id>`). `def venue_for_discord(guild_id: str, channel_id: str, user_id: str) -> str` returns `f"dm:{user_id}"` when `guild_id == "dm"`, otherwise `f"guild:{guild_id}/channel:{channel_id}"`. `def visibility_for_venue(venue: str, speaker: str) -> str`: `"app"` gives `"owner"`; `"dm:<x>"` gives `"private:<x>"`; `"guild:<g>/channel:<c>"` gives `"guild:<g>"`. `def visible_in_venue(venue: str) -> list[str]` returns the visibilities that may be recalled there: `"app"` gives `["owner"]`; `"dm:<x>"` gives `["private:<x>"]`, plus `"owner"` when `x` is an owner DM (`venue == "dm:owner"`); `"guild:<g>/..."` gives `["guild:<g>"]`.
  2. Add `venue: str = "app"` as the last keyword argument of `process_query`, `stream_query` and `_turn_pipeline`, stored on `TurnContext` (new last field `venue: str = "app"`) together with `speaker: str` from `speaker_key`.
  3. The Discord bot passes `venue=venue_for_discord(guild_id, channel_id, user_id)` (owner DMs: when `requester_role == "owner"` and it is a DM, the venue is `"dm:owner"`). The chat routes pass nothing (default `"app"`).
- **Tests:** each helper on its documented inputs; `process_query` with `venue="guild:1/channel:2"` puts that venue and the right speaker on the turn context (use the `turn_orchestrator` fixture and capture the context); the default is `"app"`. Characterisation tests pass unchanged.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change what the bot sends to the model, its history keys or its role logic.

---

**W3-11 Salience**
- **PRD:** memory 5.4
- **Tier:** bulk
- **Files:** new `src/aura/engines/memory/v2/salience.py`, `src/aura/config.py`, new `tests/unit/test_memory_v2_salience.py`. Read the depth formula in `MemoryManager` (around `depth = (len_score * 0.5) ...`) and `EmotionEngine.config.baseline`.
- **Change:**
  1. Config: `memory_salience_active_min: float = 0.1`, `memory_salience_weights: tuple[float, float, float] = (0.4, 0.4, 0.2)`.
  2. `def interaction_depth(response_length: int | None, reasoning_steps: int | None, tool_calls: int | None) -> float`: the same formula as `MemoryManager`'s depth, moved into a function and called from there too, so there is one copy.
  3. `def emotional_intensity(state: dict[str, float], baseline: dict[str, float]) -> float`: for each dimension, `d = state - baseline`; keep dimensions with `abs(d) >= memory_salience_active_min`; return the root mean square of the kept `d` values, `0.0` when none are kept, capped at `1.0`. The PRD asks for a rolling baseline; the emotion engine has a fixed configured baseline today, so this uses `EmotionEngine.config.baseline` and says so in the docstring.
  4. `def salience(intensity: float, prediction_error: float | None, depth: float) -> float` with the configured weights; `prediction_error=None` means `0.5` until predictions exist.
- **Tests:** a resting state equal to the baseline gives intensity 0; three strong dimensions give a higher intensity than one; a hand-computed RMS example; salience with `prediction_error=None` uses 0.5; `MemoryManager`'s depth is unchanged (its existing tests pass).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change the depth formula or any formation-score weight.

---

**W3-12 Episodes are stored after every turn (flagged)**
- **PRD:** memory 5.1, 5.3 (ephemeral rule), M4
- **Tier:** bulk
- **Depends on:** W3-09, W3-10, W3-11
- **Files:** new `src/aura/engines/memory/v2/episodes.py`, `src/aura/orchestrator/coordinator.py` (`_post_response_chain`), `src/aura/config.py`, new `tests/scenarios/test_memory_v2_episodes_embedded.py`
- **Change:**
  1. Config: `memory_v2_write_enabled: bool = False` (`AURA_MEMORY_V2_WRITE_ENABLED`).
  2. `async def ensure_person(db, key: str, display_name: str | None) -> RecordID`: upsert `entity:<key>` (`type="person"`, `name` = display name or key, alias = lowercased name) and return its id. Keys are `owner` or `discord_<id>`; build the record id with the existing `to_record_id` helper, never by string formatting into a query.
  3. `async def store_episode(db, embeddings, *, user_text, aura_text, speaker, venue, conversation_id, emotional_signature, salience) -> RecordID`: embed `user_text + "\n" + aura_text[:200]`; create the episode with `recorded_at = get_clock().now()`; `ephemeral = not needs_recall(user_text)` (the W3-06 gate rule); relate `next` from the most recent episode with the same `venue` and `conversation_id`, if any. Returns the id. All values are query parameters.
  4. In `_post_response_chain`, after the experience is logged and only when the flag is on: compute salience (W3-11) from the current emotional state, the configured baseline, and the depth of this reply; call `store_episode` inside `try/except` (log a warning on failure; the turn is never affected). `_post_response_chain` receives `venue` and `speaker` from the turn context (add them as last keyword arguments with defaults `"app"` and `"owner"`).
- **Tests:** on the embedded engine with the runner: two turns in one venue create two episodes linked by `next`; a third turn in another venue starts a new chain; `"thanks!"` is stored with `ephemeral = true`; the speaker entity exists and is reused across turns; with the flag off nothing is written (ablation); a failing embed still stores nothing and does not raise into the turn.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** remove or change today's memory writes. Do not call a model.

---

**W3-13 Extraction after the turn (flagged)**
- **PRD:** memory 5.2 (the structured call), 12.1
- **Tier:** frontier
- **Depends on:** W3-12
- **Files:** new `src/aura/engines/memory/v2/extraction.py`, `src/aura/engines/memory/v2/episodes.py` (schedule extraction), `src/aura/config.py`, new `tests/unit/test_memory_v2_extraction.py`
- **Change:**
  1. Config: `memory_extraction_model: str = ""` (empty means `settings.l2_model`), `memory_extraction_max_attempts: int = 3`.
  2. Pydantic models: `ExtractedEntity(name: str, type: str, surface: str)`, `ExtractedFact(content: str, kind: str, subject: str | None, predicate: str | None, object: str | None, about: list[str], asserted_by: Literal["user", "aura"], implied: bool = False, negates: bool = False)`, `Extraction(entities: list[ExtractedEntity], facts: list[ExtractedFact], questions: list[str], predictions: list[str])`. Unknown `type` or `kind` values are coerced to `other` / `fact` with a warning rather than failing the whole extraction.
  3. `def build_prompt(episode, previous: list) -> list[dict]`: a system message that states the JSON shape above with one short example, the rules ("each fact is one self-contained sentence", "`asserted_by` is `aura` for anything only Aura said", "`subject` is `I` when the speaker talks about themselves", "`negates` is true when the statement denies something said before"), and a user message with the two previous episodes and this one, each as `speaker: user_text` / `Aura: aura_text`.
  4. `async def extract(client, episode, previous) -> Extraction`: one `complete` call with the extraction model, temperature 0; parse the first JSON object in the reply (fenced or bare); validate with the models.
  5. `async def run_extraction(db, client, episode_id)`: load the episode and the two previous ones in the same venue; on success store the `Extraction` as JSON in a new optional `episode.extraction` field (add `DEFINE FIELD IF NOT EXISTS extraction ON episode TYPE option<object> FLEXIBLE` to `schema_v2.surql`) and set `extraction_status="done"`; on any failure increment `extraction_attempts`, set `extraction_error`, and set the status to `failed` only once attempts reach the maximum (otherwise leave `pending` for the dream cycle to retry). An episode is never deleted because extraction failed.
  6. `store_episode`'s caller schedules `run_extraction` as a background task (`asyncio.create_task`, keep a reference so it is not garbage collected) when the flag is on.
- **Tests:** with a fake client: a bare JSON reply and a fenced one both validate; an unknown entity type becomes `other`; invalid JSON leaves the episode `pending` with attempts 1 and the error stored; the third failure sets `failed`; the prompt contains the previous two episodes and the speaker labels; the model name used is `settings.l2_model` when `memory_extraction_model` is empty.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** write facts or entities here (W3-14 to W3-16). Do not run extraction on the reply path.

---

**W3-14 Entity resolution**
- **PRD:** memory 5.2 step 1
- **Tier:** bulk
- **Depends on:** W3-13
- **Files:** new `src/aura/engines/memory/v2/entities.py`, `src/aura/config.py`, new `tests/scenarios/test_memory_v2_entities_embedded.py`
- **Change:**
  1. Config: `memory_entity_match_threshold: float = 0.92`, `memory_entity_close_margin: float = 0.02`.
  2. `async def resolve_entity(db, embeddings, name: str, type: str, speaker: str) -> RecordID`:
     - `"I"`, `"me"`, `"myself"` resolve to the speaker's person entity.
     - Exact alias: the lowercased, whitespace-collapsed name matches an alias (`aliases CONTAINS $a`), preferring the same `type`.
     - Otherwise embedding similarity over `entity.embedding` with the KNN operator (k=3): the best match at or above the threshold wins, and its aliases get the new surface form.
     - When the top two are both above the threshold and within the margin, take the best and log the pair at INFO (the PRD's model call for close cases is left for later; say so in the docstring).
     - Otherwise create a new entity with the name, type, lowercased alias and embedding.
- **Tests:** on the embedded engine: an exact alias resolves without embedding; a new surface form close in embedding resolves to the existing entity and is added as an alias; an unrelated name creates a new entity; `"I"` resolves to the speaker; resolving the same name twice creates one entity.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** call a model.

---

**W3-15 Facts with provenance and visibility**
- **PRD:** memory 4.4 (speakers, visibility, hearsay), 5.2 step 2, rules 5 and 6
- **Tier:** frontier
- **Depends on:** W3-14
- **Files:** new `src/aura/engines/memory/v2/facts.py`, `src/aura/engines/memory/v2/extraction.py` (`run_extraction` calls it after a successful extraction), `src/aura/config.py`, new `tests/scenarios/test_memory_v2_facts_embedded.py`
- **Change:**
  1. Config: `memory_hearsay_confidence: float = 0.3`, `memory_observed_confidence: float = 0.8`, `memory_inferred_confidence: float = 0.5`.
  2. `async def write_facts(db, embeddings, episode, extraction)`: resolve every extracted entity (W3-14) and relate `mentions` from the episode. For each extracted fact:
     - `asserted_by == "aura"`: skip it. Aura's own statements are never stored as facts about the world (rule 5).
     - Resolve `about` names and the `subject`. Provenance: `implied` gives `inferred`; a subject that resolves to the speaker, or to a non-person entity, gives `observed`; a subject that resolves to another person gives `hearsay`.
     - Confidence from the provenance settings.
     - `visibility = visibility_for_venue(episode.venue, episode.speaker)` (W3-10).
     - `recorded_at = get_clock().now()`; `valid_from` the same; embedding of `content`.
     - Hand the fact to the conflict check (W3-16; until it lands, store it as new), then relate `derived_from` to the episode and `about` to each resolved entity.
  3. Nothing a guest (speaker not `owner`) says can create a fact whose subject resolves to the `owner` entity with provenance other than `hearsay`.
- **Tests:** on the embedded engine with scripted extractions: the owner saying "I live in Lisbon" in the app stores an `observed` fact about `entity:owner` with visibility `owner`; a Discord guest saying "Mai lives in Porto" in a guild stores `hearsay` with confidence 0.3 and visibility `guild:<g>`; a DM fact gets `private:discord_<id>`; a fact with `asserted_by="aura"` is not stored; `derived_from`, `about` and `mentions` edges exist.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change today's `insight` or `memory` writes.

---

**W3-15a The owner's names resolve to the owner**
- **PRD:** memory 4.4 (every person is an entity keyed by a stable id; nothing a guest says can change facts about the owner)
- **Tier:** bulk
- **Depends on:** W3-15
- **Why:** added by the supervisor after reviewing W3-15. `ensure_person` names the owner's entity `owner` with the single alias `owner`, so a guest saying "Mai lives in Porto" resolves "Mai" to a new, separate person entity. The guest rule in `write_facts` (subject is `entity:owner`, so provenance is `hearsay`) then never applies, and the conflict check (W3-16) cannot see that the claim is about the owner. The W3-15 tests named the owner entity directly, so they did not catch this.
- **Files:** `src/aura/config.py`, `src/aura/engines/memory/v2/episodes.py` (`ensure_person`), `src/aura/orchestrator/coordinator.py` (the `store_episode` call in `_post_response_chain`), new `tests/scenarios/test_memory_v2_owner_names_embedded.py`
- **Change:**
  1. Config: `owner_display_name: str = ""` (`AURA_OWNER_NAME`) and `owner_aliases: list[str] = []` (`AURA_OWNER_ALIASES`, comma-separated in the environment if the settings class already parses lists that way; otherwise follow how other list settings are read).
  2. `ensure_person`: aliases are merged, never replaced: the stored aliases are the union of the existing ones and the new ones, lowercased and whitespace-collapsed. For `key == "owner"`, the name is `settings.owner_display_name`, else the passed display name, else `"owner"`; the aliases always include `"owner"`, the lowercased name and every `settings.owner_aliases` entry.
  3. In `_post_response_chain`, when the speaker is `"owner"` and the venue is `"app"`, pass the turn's `user_id` as the display name unless it is `"default"` or empty (the app sends the owner's name, for example `"Mai"`).
- **Tests:** on the embedded engine: with `owner_display_name="Mai"`, `ensure_person(db, "owner", None)` gives the name `Mai` and aliases containing `owner` and `mai`; a second call with another display name keeps the earlier aliases; `owner_aliases=["M"]` adds `m`. With a scripted extraction where a Discord guest in a guild says "Mai lives in Porto" (`subject="Mai"`), the stored fact is `about` `entity:owner` with provenance `hearsay`. An app turn with `user_id="Mai"` adds the alias `mai` even when `owner_display_name` is empty.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change the entity resolution rules (W3-14) or the provenance rules (W3-15) themselves.

---


**W3-16 The conflict check: duplicate, update, contradiction, new**
- **PRD:** memory 5.2 step 3, 5.3 (superseded facts)
- **Tier:** frontier
- **Depends on:** W3-15
- **Files:** new `src/aura/engines/memory/v2/conflicts.py`, `src/aura/engines/memory/v2/facts.py`, `src/aura/config.py`, new `tests/scenarios/test_memory_v2_conflicts_embedded.py`
- **Change:**
  1. Config: `memory_duplicate_similarity: float = 0.95`, `memory_contradiction_similarity: float = 0.8`, `memory_duplicate_confidence_step: float = 0.1`.
  2. `async def classify(db, new_fact, about_ids) -> tuple[str, RecordID | None]` over current facts (`valid_to IS NONE`) that are `about` any of the same entities and have the same `visibility`:
     - **duplicate:** an existing fact with embedding similarity at or above the duplicate threshold.
     - **update:** an existing fact with the same resolved `subject` and the same `predicate` (lowercased, whitespace-collapsed) and a different `object`, whose provenance is not stronger than the new one (`observed` > `inferred` > `hearsay`; hearsay never updates an observed fact).
     - **contradiction:** the new fact has `negates=True` and an existing fact is at or above the contradiction threshold, or an update was blocked only by the provenance rule.
     - **new:** otherwise.
  3. Apply: duplicate raises the existing fact's confidence by the step (capped at 1), relates `derived_from` to the new episode and stores nothing new; update stores the new fact, sets `valid_to = get_clock().now()` on the old one and relates new `supersedes` old; contradiction stores the new fact, relates `contradicts`, and creates a `question` ("Which is true: <old> or <new>?") with the same visibility; new stores the fact.
- **Tests:** on the embedded engine with scripted extractions and the runner's clock: "I live in Lisbon" then "I moved to Porto" (same subject and predicate `lives in`) leaves only Porto current, Lisbon with `valid_to` set and a `supersedes` edge; the same statement twice raises confidence and creates one fact; a guest's hearsay "Mai lives in Berlin" does not supersede Mai's observed fact and creates a `contradicts` edge and a question; a negation creates a contradiction; an unrelated fact is new.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** delete any fact. Do not call a model.

---

**W3-17 Recall reads facts, filtered by visibility (flagged)**
- **PRD:** memory 4.4 ("filters by visibility before ranking"), 6.3 step 6 (facts with age, provenance and confidence), M4
- **Tier:** frontier
- **Depends on:** W3-16, W3-05
- **Files:** `src/aura/engines/recall/channels.py`, `src/aura/engines/recall/engine.py`, `src/aura/engines/recall/models.py` (`RecallRequest`), the four `RecallRequest(...)` call sites in `coordinator.py` and `layers.py`, `src/aura/config.py`, new `tests/scenarios/test_recall_v2_facts_embedded.py`
- **Change:**
  1. Config: `memory_v2_recall_enabled: bool = False` (`AURA_MEMORY_V2_RECALL_ENABLED`).
  2. `RecallRequest` gets `venue: str = "app"` (last field); the call sites pass the turn's venue.
  3. `channels.py`: `fact_dense_channel` and `fact_lexical_channel`, like W3-02 but over `fact`, with `visibility IN $visible` (from `visible_in_venue`, W3-10) and `valid_to IS NONE`, and no `user_id` filter (visibility replaces it).
  4. When both `recall_channels_enabled` and `memory_v2_recall_enabled` are on, the memories block uses the fact channels, fuses them (W3-04), applies abstention (W3-07) unchanged, and renders `<memories>` with one `<fact age="<n>d" provenance="<p>" confidence="<c:.2f>">content</fact>` line per fact, age from `recorded_at` and `get_clock().now()`.
- **Tests:** on the embedded engine: a fact learned in the app is recalled in the app and not in a guild or a guest DM; a guild fact is recalled in that guild only; a guest DM fact only in that DM; a superseded fact is never recalled; the rendered line carries age, provenance and confidence; with the v2 flag off the memory-table path runs (ablation).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** remove the memory-table path. Do not turn any flag on by default.

---

**W3-18 M4 probes: updated facts, history, visibility, stale-fact rate**
- **PRD:** memory M4 gate ("updated-fact, history and visibility probes pass, stale-fact rate under 2%"), 8.3
- **Tier:** bulk
- **Depends on:** W3-17
- **Files:** new `tests/scenarios/test_memory_v2_m4_embedded.py`, new `docs/metrics/m4.md`. Read `tests/scenarios/runner.py`.
- **Change:** scenario tests through the runner with all v2 and M3 flags on and a scripted extraction client (a fake that returns a fixed `Extraction` per turn, so no model is called):
  - **Updated fact:** day 0 "I live in Lisbon", day 10 "I moved to Porto"; on day 11 "where do I live?" recalls Porto and not Lisbon.
  - **History:** after the update, `what_changed`-style query: the `supersedes` chain from Porto leads to Lisbon (query the edge directly; the recall tool itself is M5).
  - **Visibility:** a guest's DM fact never appears in the app or a guild; a guild fact never appears in another guild.
  - **Hearsay:** a guest's claim about the owner never replaces the owner's own fact.
  - **Stale-fact rate:** over a 40-turn script with 10 updates, the share of recalled facts that are superseded; assert under 2% and write the number with the date to `docs/metrics/m4.md` only when `RECORD_BASELINE=1` (use `write_baseline`).
- **Tests:** these are the tests. Run the full suite, then once with `RECORD_BASELINE=1`, and commit `docs/metrics/m4.md`.
- **Done when:** the new tests pass, the full suite passes, and `docs/metrics/m4.md` exists with the stale-fact rate and the date.
- **Do not:** change any flag default or threshold to make a test pass; report failures instead.

---


### Wave 3: cards for E2 and E3 (events, appraisal, causes, the new state interface)

Written by the supervisor on 2026-11-20 against the code after M4. E1 (physics v2) landed as W1-15. Everything new is behind `emotion_appraisal_enabled` (off): with it off, emotions change exactly as today, except that the keyword fallback is deleted (PRD 5.3 and T14 apply on both paths). Emotion PRD rules apply: time from the injected clock; the appraisal table in a data file; Aura's reply never reaches an appraisal; the 27 dimension names unchanged (`love, joy, interest, trust, fear, sadness, anger, surprise, disgust, awe, beauty, wonder, serenity, melancholy, nostalgia, empathy, gratitude, pride, shame, envy, compassion, curiosity, confusion, certainty, doubt, fascination, boredom`).

Note found while carding: the self-critique influence in `coordinator.py` pushes `determination`, which is not one of the 27 dimensions. W3-23 replaces that call with an event.

---

**W3-19 Appraisal variables and the appraisal table**
- **PRD:** emotion 5.2, 5.3, test T8
- **Tier:** frontier (the table is behaviour)
- **Files:** new `src/aura/models/appraisal.py`, new `src/aura/engines/emotion/appraisal_table.json`, new `src/aura/engines/emotion/appraisal.py`, new `tests/unit/test_appraisal_table.py`
- **Change:**
  1. `appraisal.py` (models): pydantic `Appraisal(congruence: float [-1,1] = 0, novelty: float [0,1] = 0, certainty: float [0,1] = 0.5, control: float [0,1] = 0.5, agency: Literal["self", "other", "circumstance"] = "circumstance", warmth: float [-1,1] = 0, beauty: float [0,1] = 0, intensity: float [0,1] = 0.5)` with field validators that clamp to range; `AppraisalEvent(kind: str, source: str, appraisal: Appraisal, person_id: str | None = None, venue: str | None = None, ref: str | None = None, user_state: dict[str, float] | None = None)`.
  2. `appraisal_table.json`: a list of patterns, each `{"name", "when": {<variable>: [min, max] or "<agency value>"}, "impulse": {<dimension>: weight}}`, covering every row of PRD 5.3 (high novelty; high novelty with positive congruence and high beauty; positive congruence with agency self; positive congruence, agency other, positive warmth; negative congruence, agency other, high control; negative congruence, low control, plus fear when certainty is low as its own row; negative congruence, agency self; low novelty and low intensity; low certainty; negative warmth from another is not in the table and is left out). Thresholds: "high" means at least 0.6, "low" at most 0.3, "positive" above 0.2, "negative" below -0.2. The "repeated" part of boredom and the "positive relationship" part of empathy need habituation (E3a) and relationships (E5); leave them out and say so in a `"note"` field on those rows. The empathy row matches on the event's `user_state` showing distress (sadness or fear at least 0.5) instead.
  3. `appraisal.py` (engine): `def load_table(path=None) -> list[Pattern]` (validates every dimension name against `EmotionVector.model_fields` and raises on an unknown one); `def impulses_for(appraisal, user_state=None, table=None) -> dict[str, float]`: sum the impulses of every matching row, then multiply by `appraisal.intensity`; values capped at 1.
- **Tests:** T8: for each row, a hand-built appraisal that matches it produces that row's expected dominant dimension (largest impulse); an unknown dimension in a table file raises at load; intensity 0 gives no impulse; an appraisal matching nothing gives `{}`.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** touch the engine or the physics. Do not invent rows beyond PRD 5.3.

---

**W3-20 `appraise` and cause records (flagged)**
- **PRD:** emotion 5.3 (impulse through coupling and inertia), 5.7 (causes), 9 (`appraise` is the only way state changes), T9
- **Tier:** frontier
- **Depends on:** W3-19
- **Files:** `src/aura/engines/emotion/engine.py`, `scripts/init_schema.surql` (new table), `src/aura/config.py`, new `tests/unit/test_emotion_appraise.py`
- **Change:**
  1. Config: `emotion_appraisal_enabled: bool = False` (`AURA_EMOTION_APPRAISAL_ENABLED`).
  2. Schema: `DEFINE TABLE IF NOT EXISTS emotion_event SCHEMAFULL` with `at` datetime, `kind` string, `source` string, `ref` option<string>, `person_id` option<string>, `venue` option<string>, `appraisal` object FLEXIBLE, `impulses` object FLEXIBLE, `deviation_change` object FLEXIBLE (per dimension, after physics), `dominant_change` option<string>; index on `at`.
  3. `EmotionEngine.appraise(event: AppraisalEvent) -> EmotionState`: `impulses_for(...)`; if empty, log at DEBUG and return the current state without writing; otherwise apply through the same physics call `apply_influence` uses today (coupling and inertia included), clamp as today, compute the per-dimension change in deviation from baseline, write one `emotion_event` (time from `get_clock()`), broadcast as today, and return the state. A database failure while writing the record is logged and does not undo the state change.
- **Tests:** a positive-congruence, agency-self event raises joy and writes one `emotion_event` with the appraisal, the impulses and the deviation change; an event matching no row writes nothing and changes nothing; T9: over a scripted sequence of ten events, every dimension whose deviation changed by more than 0.1 in a step has an `emotion_event` for that step (use a fake database that records writes).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** remove `apply_influence` yet (W3-23 moves its callers). Do not change the physics.

---

**W3-21 The L4 appraisal call reads the user's message only**
- **PRD:** emotion 5.2 (one model call returns the appraisal and an estimate of the user's state; Aura's reply is not input), finding E4, test T7
- **Tier:** frontier
- **Depends on:** W3-19
- **Files:** `src/aura/llm/layers.py` (new `l4_appraise_message`), new `tests/unit/test_l4_appraise.py`
- **Change:** `async def l4_appraise_message(self, user_input: str, recent_history: list[dict[str, str]], speaker: str) -> tuple[Appraisal, dict[str, float]]`: one call with the existing L4 model and settings, temperature as the current L4 call uses. The prompt explains the eight variables in one line each (PRD 5.2), gives the last four turns of history for context with Aura's turns included only as context labelled as such, and asks for JSON `{"appraisal": {...}, "user_state": {<dimension>: 0..1}}` judged from the user's latest message. It must not receive the reply Aura is about to give or has just given: the method has no parameter for it. Parse the first JSON object (as W3-13 does), validate with `Appraisal`, keep only known dimensions in `user_state`. Raise on failure; the caller decides.
- **Tests:** with a fake client: a valid reply parses; a fenced reply parses; unknown `user_state` keys are dropped; invalid JSON raises; T7: the request sent to the client is identical whatever reply text Aura produced in the turn (build two turns that differ only in Aura's latest reply, not yet in the history passed, and assert the prompts are equal).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change or remove `l4_emotion_analysis` here (W3-22 stops calling it).

---

**W3-22 Messages are appraised; the keyword fallback is deleted**
- **PRD:** emotion 5.2, 5.3 ("the keyword fallback (E5) is deleted"), T14
- **Tier:** frontier
- **Depends on:** W3-20, W3-21
- **Files:** `src/aura/orchestrator/coordinator.py` (`_post_response_chain`, `_apply_l4_emotion_analysis`, `_apply_conversation_influence_fallback`), `tests/unit/test_turn_*` only where they assert the fallback, new `tests/unit/test_message_appraisal.py`
- **Change:**
  1. Delete `_apply_conversation_influence_fallback` and both calls to it. When `_apply_l4_emotion_analysis` gets nothing after its retries, it logs a warning and applies nothing (T14 on the old path).
  2. When `emotion_appraisal_enabled` is on, `_post_response_chain` calls a new `_appraise_message(user_input, conversation_history, venue, speaker)` instead of `_apply_l4_emotion_analysis`: `l4_appraise_message` with the history up to and including the user's message (not Aura's reply), then `emotion_engine.appraise(AppraisalEvent(kind="message", source="conversation", appraisal=..., user_state=..., person_id=speaker, venue=venue))`. On failure: one warning log, no impulse, no fallback. No retry loop (the old one retried a call whose output was then never checked for sanity).
- **Tests:** T14 on both paths: a failing L4 call produces no state change and a warning, and no keyword-based change happens for a reply full of "architecture" and "blueprint"; with the flag on, a message is appraised and `appraise` receives `person_id` and `venue`; the reply text never reaches `l4_appraise_message` (assert on the call arguments). Update only the characterisation assertions that referred to the fallback, each with the docstring line "changed on purpose by W3-22 (keyword fallback removed)".
- **Done when:** the new tests pass, the full suite passes, and `grep -rn "_apply_conversation_influence_fallback" src` prints nothing.
- **Do not:** change the L4 model settings or `l4_emotion_analysis` itself.

---

**W3-23 System events are appraised, not pushed as raw deltas (flagged)**
- **PRD:** emotion 5.1 (events from the whole system), 5.2 (computed appraisal for system events), 9 (`apply_influence` removed from the public interface; callers post events)
- **Tier:** bulk
- **Depends on:** W3-20
- **Files:** `src/aura/orchestrator/coordinator.py` (the self-critique influence near `critique_buffer`, the memory-storage failure influence), `src/aura/orchestrator/tool_loop.py` (only to report results; see step 3), new `src/aura/engines/emotion/system_events.py`, new `tests/unit/test_system_appraisal.py`
- **Change:**
  1. `system_events.py`: functions that return an `AppraisalEvent` with computed values, each documented in one line: `memory_write_failed()` (congruence -0.6, control 0.3, certainty 0.8, agency circumstance, intensity 0.5); `self_critique_received()` (congruence -0.2, agency self, certainty 0.7, control 0.8, intensity 0.3); `tool_succeeded(tool)` (congruence 0.5, agency self, certainty 0.8, control 0.8, intensity 0.3); `tool_failed(tool, retryable: bool)` (congruence -0.5, agency circumstance, certainty 0.6, control 0.7 if retryable else 0.2, intensity 0.4).
  2. When `emotion_appraisal_enabled` is on, the two coordinator call sites call `emotion_engine.appraise(...)` with these events instead of `apply_influence`. With the flag off they stay as they are.
  3. `run_tool_loop` gains an optional `on_tool_result: Callable[[str, bool], Awaitable[None]] | None = None`, called once per executed call with the tool name and success, when the executor reports per-call success (if it only returns joined text, report success when the result block does not start with an error marker the executor already uses; read `execute_and_feedback` and say which in the log). The coordinator passes a callback that appraises `tool_succeeded` / `tool_failed` when the flag is on.
- **Tests:** each computed event produces its expected dominant dimension through the real table (failure: sadness or confusion; success: joy or pride); with the flag on, a memory write failure calls `appraise` and not `apply_influence`; with it off, today's call happens (ablation); the tool loop calls `on_tool_result` once per call.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** remove `apply_influence` or the `/emotion/influence` API route (the route is a developer tool; leave it).

---

**W3-24 The state interface: deviation, baseline, causes, `explain`**
- **PRD:** emotion 9 (`EmotionState` gains `deviation`, `baseline`, `mood`, `top_causes`; `explain`; websocket payload), milestone E3
- **Tier:** bulk
- **Depends on:** W3-20
- **Files:** `src/aura/models/emotion.py` (`EmotionState`, new `EmotionCause`), `src/aura/engines/emotion/engine.py` (`get_current_state`, new `get_state`, new `explain`, `_broadcast_state_update`), new `tests/unit/test_emotion_state_interface.py`
- **Change:**
  1. `EmotionCause(at: datetime, kind: str, source: str, ref: str | None, person_id: str | None, dominant_change: str | None, size: float)` where `size` is the largest absolute deviation change of that event.
  2. `EmotionState` gains optional `deviation: dict[str, float] | None`, `baseline: dict[str, float] | None`, `mood: dict[str, float] | None` (always `None` until E4) and `top_causes: list[EmotionCause] = []`.
  3. `get_current_state` fills `deviation` (vector minus baseline), `baseline`, and `top_causes` (the three largest `emotion_event`s of the last hour by `size`, newest first among equals; empty when there are none or the query fails).
  4. `get_state(person_id: str | None = None)` returns `get_current_state()` (per-person state is E5; say so). `explain(since: datetime | None = None) -> list[EmotionCause]` returns the events since then (default: the last hour), newest first.
  5. The websocket payload built in `_broadcast_state_update` gains `deviation`, `baseline`, `mood` and `top_causes` (as plain JSON), keeping every existing field.
- **Tests:** deviation equals vector minus baseline; `top_causes` orders and caps at three; `explain` filters by time with the fake clock; the broadcast payload keeps its old keys and has the new ones.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change the frontend. Do not remove any existing field.

---

**W3-25 The prompt names the main cause**
- **PRD:** emotion 5.7 ("the emotion block in her prompt names the main cause alongside the state"), E3
- **Tier:** bulk
- **Depends on:** W3-24
- **Files:** `src/aura/llm/layers.py` (`_build_l3_system_prompt`, the `<emotional_state>` block), new `src/aura/engines/emotion/describe.py`, new `tests/unit/test_emotion_prompt_cause.py`
- **Change:** `describe.py`: `def cause_phrase(cause: EmotionCause, now: datetime) -> str`, a short plain phrase such as `"since a tool failed 12 minutes ago"` or `"since a message from discord_42 3 minutes ago"`, built from `kind`, `source`, `person_id` and the age (minutes under an hour, hours otherwise). When the state has at least one top cause, the `<emotional_state>` block gains one line `  <cause>{phrase for the first cause}</cause>` after `<dominant>`. Without causes, the block is byte-for-byte as today.
- **Tests:** phrases for each kind used by W3-22 and W3-23; the block with a cause; the block without causes is unchanged (compare with today's exact string).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** reveal record ids, appraisal numbers or other people's message text in the phrase.

---

**W3-26 E2 and E3 scenarios: own reply, causes, signatures differ**
- **PRD:** emotion tests T7, T9, T14, T15
- **Tier:** bulk
- **Depends on:** W3-22, W3-23, W3-25
- **Files:** new `tests/scenarios/test_emotion_appraisal_embedded.py`, new `docs/metrics/e2e3.md`. Read `tests/scenarios/runner.py`.
- **Change:** scenarios through the runner with `emotion_appraisal_enabled` on and a scripted L4 client (a fake returning fixed appraisals per message, so no model is called):
  - **T7:** two runs that differ only in Aura's replies end in the same emotional state (within 1e-9).
  - **T9:** over a 30-turn script with system events mixed in, every deviation change above 0.1 has an `emotion_event` record.
  - **T14:** a turn whose appraisal call fails leaves the state unchanged except for physics decay over the elapsed simulated time.
  - **T15:** a memory formed right after a failed tool event and one formed right after a successful one have signatures whose cosine similarity, computed on deviations (signature minus baseline), is below 0.5. Write the measured similarity with the date to `docs/metrics/e2e3.md` only when `RECORD_BASELINE=1` (use `write_baseline`).
- **Tests:** these are the tests. Run the full suite, then once with `RECORD_BASELINE=1`, and commit `docs/metrics/e2e3.md`.
- **Done when:** the new tests pass, the full suite passes, and `docs/metrics/e2e3.md` exists with the T15 similarity and the date.
- **Do not:** change the table or any threshold to make a test pass; report failures instead.

---


### Wave 3: cards for G2 (the OpenCode client, managed process, version pin)

Written by the supervisor on 2026-11-20. Mai's decision (agency PRD 11.1, plan section 6 item 4): pin OpenCode **v2.3.2** (major version 2), and Aura runs her own `opencode serve` process; she does not attach to the desktop app's service. The OpenAPI document of that version is saved at `docs/opencode/openapi-v2.3.2.json` (fetched from a running v2.3.2 server). Agency PRD rule 2: every endpoint path and payload shape comes from that file, never from memory.

Facts checked on the v2.3.2 server on 2026-11-20:
- `opencode serve --hostname 127.0.0.1 --port <n>` prints `server listening on http://127.0.0.1:<n>` and `server password <secret>` on its output, and generates the password itself.
- Every `/api/*` request needs HTTP Basic auth with user `opencode` and that password. `GET /api/info` returns `{"version": "2.3.2", "pid": ..., ...}`.
- Endpoints the client needs: `POST /api/session` (create), `POST /api/session/{sessionID}/prompt` (body `{"text": ...}`), `GET /api/event` (server-sent events, optional `types` query), `GET /api/session/{sessionID}/permission` and `POST /api/session/{sessionID}/permission/{requestID}/reply`, `POST /api/session/{sessionID}/interrupt`, `GET /api/session/{sessionID}/diff`, `GET /api/session/{sessionID}/message`.
- Event types include `session.execution.started`, `session.execution.succeeded`, `session.execution.failed`, `session.execution.interrupted`, `session.step.started`, `session.step.ended`, `session.step.failed`, `session.tool.called`, `session.tool.success`, `session.tool.failed`, `permission.asked`, `permission.replied`, `session.idle`, `session.status`.

---

**W3-27 A managed OpenCode server with a version pin**
- **PRD:** agency 4.2 (starts `opencode serve` as a managed child process on localhost with a generated password; pins a version and refuses another major version), test T7
- **Tier:** frontier
- **Files:** new `src/aura/connections/__init__.py` (if missing), new `src/aura/connections/opencode_process.py`, `src/aura/config.py`, new `tests/unit/test_opencode_process.py`, new `tests/fixtures/fake_opencode_server.py`
- **Change:**
  1. Config: `opencode_command: list[str] = []` (`AURA_OPENCODE_COMMAND`, JSON list; empty means `["opencode"]` found on `PATH`), `opencode_version_pin: str = "2.3.2"`, `opencode_host: str = "127.0.0.1"`, `opencode_port: int = 0` (0 picks a free port), `opencode_start_timeout_secs: int = 30`.
  2. `class OpenCodeProcess`: `async start()` runs `opencode_command + ["serve", "--hostname", host, "--port", str(port)]` as a child process (`asyncio.create_subprocess_exec`, no shell), reads its output lines until it has both the listening URL and the password (regexes on the two lines above), then polls `GET /api/info` with Basic auth until it answers or the timeout passes. `base_url`, `auth` (an `httpx.BasicAuth`) and `version` are then available. `async stop()` terminates the process (kill after 5 s). The password is never logged, printed or stored outside the object; log lines show `***`.
  3. Version check (T7): if the major version from `/api/info` differs from the pin's major, `start()` stops the process and raises `OpenCodeVersionError` with both versions in the message, before any other request is made. A different minor or patch version is allowed with a warning.
  4. A process that exits before printing both lines raises `OpenCodeStartError` with the last 20 output lines, with any line containing `password` redacted.
- **Tests:** `tests/fixtures/fake_opencode_server.py` is a small standalone script (standard library only: `http.server` and `threading`) that prints the two lines and serves `/api/info` behind Basic auth, with the version taken from a command-line argument. Tests run it with `sys.executable` through `opencode_command`: start succeeds and `version == "2.3.2"`; version `3.0.0` raises `OpenCodeVersionError` and no request other than `/api/info` reached the fake (it records request paths); `2.4.0` starts with a warning; a script that exits immediately raises `OpenCodeStartError`; the password does not appear in captured logs; `stop()` leaves no child process running.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** start OpenCode at Aura startup yet (W3-28 adds the client; G3 decides when to start it). Do not use the desktop app's background service. Do not add a dependency.

---

**W3-28 `OpenCodeClient` against a fake server**
- **PRD:** agency 4.2 (the client interface, the only code that talks to OpenCode), test T6
- **Tier:** frontier
- **Depends on:** W3-27
- **Files:** new `src/aura/connections/opencode_client.py`, new `src/aura/models/work.py`, new `tests/unit/test_opencode_client.py`, new `tests/unit/test_opencode_spec_coverage.py`. Read `docs/opencode/openapi-v2.3.2.json` for every path and body used.
- **Change:**
  1. `models/work.py`: `WorkEvent(kind: str, session_id: str, type: str, data: dict)`, where `kind` is one of `started`, `step`, `tool`, `permission`, `succeeded`, `failed`, `interrupted`, `idle`, `other`, mapped from the event types listed above; `PermissionRequest(id, session_id, action, resources, message)`; `WorkResult(session_id, summary: str, files_changed: list[str], additions: int, deletions: int)`.
  2. `OpenCodeClient(process_or_base_url, auth)` with the PRD 4.2 interface: `ensure_running()` (starts the managed process from W3-27 if not running), `create_session(workspace: Path, agent: str, title: str) -> str`, `send(session_id, prompt)`, `events(session_id) -> AsyncIterator[WorkEvent]` (one `GET /api/event` stream, filtered to the session; parse SSE `event:`/`data:` lines; the `data` field is a JSON-encoded string per the spec's `V2EventEncoded`), `pending_permissions(session_id) -> list[PermissionRequest]`, `answer_permission(session_id, request_id, allow: bool)` (the reply body from the spec), `abort(session_id)` (interrupt), `result(session_id) -> WorkResult` (files and counts from the diff endpoint; summary from the last assistant message's text).
  3. How a session is bound to the `workspace` directory: find it in the spec (the create-session body, or the location endpoints). If the spec does not make it clear, stop and report instead of guessing.
  4. Errors: every connection failure or server exit becomes `OpenCodeUnavailable` (T6); HTTP errors become `OpenCodeError` with the status and the server's `_tag`/`message`. `events()` raises `OpenCodeUnavailable` when the stream breaks, so the caller can mark the task interrupted and re-attach later with the same session id.
- **Tests:** with `httpx.MockTransport` (no real OpenCode): each method sends the right method, path and body; an SSE stream with mixed sessions yields only this session's events, mapped to the right kinds; T6: the transport raising `httpx.ConnectError` mid-stream raises `OpenCodeUnavailable`, and a new `events()` call for the same session id works after the transport recovers; `result()` sums the diff. `test_opencode_spec_coverage.py` loads the saved spec and asserts every `(method, path template)` the client uses exists in it (the client exposes them as a module-level list for this test).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add `delegate_work`, agents or policy (G3). Do not read events with a model. Do not add a dependency.

---


### Wave 3: cards for G3 (`delegate_work`, the three agents, briefs, task records, policy and approvals)

Written by the supervisor on 2026-11-20 against the code after G2. Agency PRD open items 11.2 (workspaces) and 11.3 (the default policy table) are Mai's: the defaults below are the PRD's recommendation, and no workspace is registered by default, so nothing can be delegated until Mai registers one. Everything is behind `delegation_enabled` (off).

OpenCode v2.3.2 facts from `docs/opencode/openapi-v2.3.2.json`: the config has an `agents` map whose entries (`Config.AgentEncoded`) take `model` (for example `"sluice/coder"`), `system`, `description`, `mode` (`subagent`, `primary`, `all`), `steps`, `disabled` and `permissions` (`Permission.Ruleset`); a session is created with an `agent` id; permission requests carry `action` and `resources`.

---

**W3-29 Workspaces and the policy table**
- **PRD:** agency 4.5 (policy table; workspaces registered explicitly; Aura's own source tree is not a workspace unless registered), 11.2, 11.3, rule 4
- **Tier:** frontier
- **Files:** new `src/aura/executor/policy.py`, `src/aura/config.py`, new `tests/unit/test_policy.py`
- **Change:**
  1. Config: `workspaces: dict[str, str] = {}` (`AURA_WORKSPACES`, JSON object of name to absolute path); `delegation_enabled: bool = False` (`AURA_DELEGATION_ENABLED`); `policy_table: dict[str, dict[str, str]]` defaulting to the PRD 11.3 recommendation for the owner, `{"read": "allow", "write": "allow", "execute": "ask", "send": "ask"}`, keyed by role, with `trusted` = read allow and everything else deny, and `guest` = deny for every risk.
  2. `policy.py`: `def workspace_path(name: str) -> Path | None` (resolved, must exist and be a directory; `None` otherwise); `def inside_workspace(path: str | Path, workspace: str) -> bool` (resolved path is the workspace or below it; symlinks and `..` resolved first); `def decide(risk: Risk, workspace: str | None, role: str, resources: list[str] = []) -> Literal["allow", "ask", "deny"]`: unknown role or risk is `deny`; an unregistered workspace is `deny`; for `write`, any resource outside the workspace is `deny`; otherwise the table value. This is the one function every delegated permission decision goes through (rule 4).
  3. `def risk_for_action(action: str) -> Risk`: map OpenCode permission actions to risk classes (`read`, `glob`, `grep`, `list` style actions to `read`; `edit`, `write`, `patch` to `write`; `bash`, `shell`, `execute` to `execute`; `webfetch`, `websearch`, network actions to `send`); anything unknown is `execute` (the strictest class that can still be approved). Read the action names actually used in the spec's permission schemas and examples and list them in the log entry.
- **Tests:** every cell of the default table for each role; a guest is denied everything; an unregistered workspace is denied; `..` and a symlink pointing outside the workspace are both denied for `write`; unknown actions map to `execute`.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** register any workspace by default, and never register Aura's own repository.

---

**W3-30 Pending decisions: owner approvals**
- **PRD:** agency 4.5 (`ask` creates a decision item with the exact action shown; only the runtime calls `answer_permission`, on a recorded owner decision), test T3 (store part)
- **Tier:** frontier
- **Depends on:** W3-28, W3-29
- **Files:** `scripts/init_schema.surql` (new table), new `src/aura/executor/decisions.py`, new `src/aura/api/routes/decisions.py`, `src/aura/main.py` (include the router), new `tests/unit/test_decisions.py`
- **Change:**
  1. Schema: `decision` SCHEMAFULL with `kind` string, `task_id` option<string>, `session_id` string, `request_id` string, `action` string, `resources` array<string>, `risk` string, `workspace` option<string>, `message` option<string>, `status` string DEFAULT "pending" ASSERT in `pending, allowed, denied, expired`, `created_at` datetime, `decided_at` option<datetime>, `decided_by` option<string>; index on `status`.
  2. `DecisionService(db, client)`: `create(...)` stores a pending decision; `pending()` lists them newest first; `answer(decision_id, allow: bool, decided_by: str)` records the decision and only then calls `client.answer_permission(session_id, request_id, allow)`; answering a decision that is not pending raises; `expire_for_session(session_id)` marks a closed session's pending decisions `expired`.
  3. Routes: `GET /decisions` (pending) and `POST /decisions/{id}` with `{"allow": bool}`. Follow how the other owner-only routes in `src/aura/api/routes/` are protected; if there is no owner check on the HTTP API, add the routes like the others and say so in the log (the app is local; Discord cannot reach these routes).
- **Tests:** create, list and answer with a fake client: the client is called only after the record says allowed or denied, with the right ids and value; a second answer raises; expiry; the routes with FastAPI's test client if the project already uses it, otherwise by calling the handlers.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add any approval argument to a tool schema (rule 3).

---

**W3-31 The three agents for Aura's OpenCode server**
- **PRD:** agency 4.3
- **Tier:** frontier
- **Depends on:** W3-27
- **Files:** new `src/aura/connections/opencode_agents.py`, `src/aura/connections/opencode_process.py` (only to pass the agent config to the server it starts), `src/aura/config.py`, new `tests/unit/test_opencode_agents.py`
- **Change:**
  1. Config: `opencode_agent_model: str = "sluice/coder"` (the router's coder pool through the `sluice` provider in Mai's OpenCode config).
  2. `opencode_agents.py`: `def agent_definitions() -> dict[str, dict]` returning the three agents in the `Config.AgentEncoded` shape: `aura-explore` (description, `mode: "subagent"` or `"primary"` as fits a session started directly, read-only permissions: read and search allowed, edits denied, shell denied except safe listing commands if the ruleset can express that, otherwise denied), `aura-build` (edits allowed, shell `ask`), `aura-review` (read-only plus the test command `ask`). Each has a short `system` prompt saying what it is for and that the brief is the source of truth. Read `Permission.Ruleset` in the spec for the exact rule shape.
  3. How Aura's server gets these agents: find, from the spec (`/api/config`, `/api/experimental/config`, `Config.*`), the CLI help (`opencode serve --help`, `opencode debug --help`) and the v2.3.2 binary's behaviour, a way that applies only to the server Aura starts: for example a config file in a directory Aura owns passed through an environment variable or flag, or `PATCH /api/experimental/config` on Aura's own server after it starts. Write it up in the log with the evidence. **If the only way is to edit Mai's global OpenCode config (`~/.config/opencode/`), stop and report instead**: that file is also used by Mai's desktop app.
  4. Apply it in `OpenCodeProcess.start()` (or right after, before the process is returned as ready), and verify with `GET /api/agent` that the three agents exist; a missing agent raises `OpenCodeStartError`.
- **Tests:** the definitions validate against the spec's `Config.AgentEncoded` and `Permission.Ruleset` schemas (load the JSON schema pieces from the saved spec and check required keys and enums by hand; no new dependency); the fake server from W3-27 extended to accept the chosen mechanism and to serve `GET /api/agent`; start fails when an agent is missing.
- **Done when:** the new tests pass, the full suite passes, and the log entry names the mechanism and its evidence.
- **Do not:** write to `~/.config/opencode/` or any file outside Aura's own directories.

---

**W3-31a The agents reach Aura's server through an Aura-owned config directory**
- **PRD:** agency 4.3
- **Tier:** frontier
- **Depends on:** W3-31
- **Why:** added by the supervisor after reviewing W3-31. W3-31 sends the agents with `PATCH /api/experimental/config` and its log says "the actual v2.3.2 server accepts `agents` in the patch payload". That was never tested against a real server, only against the fake. The supervisor tested it on a real v2.3.2 server in a sandbox on 2026-11-20: the server rejects it with `{"_tag":"InvalidRequestError","message":"Missing key\n  at [\"shell\"]"}`, as the spec's `Config.Patch` (only `shell`) says. The same test showed a mechanism that works: started with the environment variable `XDG_CONFIG_HOME` pointing at a directory, the server reads `<that directory>/opencode/opencode.jsonc` (seen in `GET /api/config` as a `document` entry with that path), and agents defined there under `"agents"` appear in `GET /api/agent` and `GET /api/agent/{id}`. Mai's global config was not touched.
- **Files:** `src/aura/connections/opencode_agents.py`, `src/aura/connections/opencode_process.py`, `src/aura/config.py`, `tests/fixtures/fake_opencode_server.py`, `tests/unit/test_opencode_agents.py`, `tests/unit/test_opencode_process.py`
- **Change:**
  1. Config: `opencode_config_dir: str = ""` (empty means `<the directory of Aura's state or data files, or the app directory>/opencode-config`; pick the existing Aura data location and say which in the log) and `opencode_router_base_url: str = "http://127.0.0.1:8787/v1"`.
  2. `opencode_agents.py`: `def write_config(config_dir: Path) -> Path` writes `<config_dir>/opencode/opencode.jsonc` (plain JSON is valid JSONC) with exactly two top-level keys: `"provider"` with the `sluice` provider (`{"npm": "@ai-sdk/openai-compatible", "name": "Sluice", "options": {"baseURL": <opencode_router_base_url>}, "models": {"coder": {"name": "coder"}, "chat": {"name": "chat"}}}`) and `"agents"` with `agent_definitions()`. It returns the file path, writes atomically (temporary file, then replace), and creates the directories.
  3. `OpenCodeProcess.start()`: before starting the child, call `write_config(...)`, and start the child with `env = os.environ.copy()` plus `XDG_CONFIG_HOME=<config_dir>`. Do not set `XDG_DATA_HOME` or `XDG_STATE_HOME` (sessions stay in the normal OpenCode data directory, so Mai can open them in her app). Remove the `PATCH /api/experimental/config` call and its code entirely.
  4. Verification after the version check: `GET /api/agent/{id}` for each of the three agents (the list endpoint can lag right after start); a missing agent raises `OpenCodeStartError`.
  5. The fake server: drop the PATCH handler; read the agents from the `XDG_CONFIG_HOME` file it is started with, and serve `GET /api/agent` and `GET /api/agent/{id}` from it.
  6. In the log entry, correct the W3-31 claim: say plainly that the PATCH mechanism was assumed, not tested, and that a real server rejects it.
- **Tests:** `write_config` produces valid JSON with the provider and the three agents; the process starts the child with `XDG_CONFIG_HOME` set to the config dir and without `XDG_DATA_HOME`; start fails when the fake does not serve one of the agents; no request to `/api/experimental/config` is ever made (the fake records paths).
- **Done when:** the new tests pass, the full suite passes, and `grep -rn "experimental/config" src` prints nothing.
- **Do not:** write to `~/.config/opencode/` or set any `XDG_*` variable in Aura's own process environment (only in the child's).

---


**W3-31b Start the real OpenCode server: real output lines, redaction, config location, a real-binary test**
- **PRD:** agency 4.2, 4.3
- **Tier:** frontier
- **Depends on:** W3-31a
- **Why:** added by the supervisor after running `OpenCodeProcess.start()` against the real v2.3.2 binary on 2026-11-20. It failed with `OpenCodeStartError: OpenCode process exited before printing URL and password`, although the real server had printed both. The patterns in `opencode_process.py` are `^\s*Listening on\s+(https?://\S+)\s*$` and `^\s*Password:\s+(\S+)\s*$`, but the real server prints exactly `server listening on http://127.0.0.1:51209` and `server password <secret>` (the W3-27 card gave these lines). The fake server was written to print the wrong lines, so every test passed. Because redaction uses the same wrong pattern, the error message printed the real password in full. The default config directory was also created inside the repository folder (`aura-app/opencode-config/`), which is not ignored by git.
- **Files:** `src/aura/connections/opencode_process.py`, `tests/fixtures/fake_opencode_server.py`, `tests/unit/test_opencode_process.py`, new `tests/integration/test_opencode_real.py` (create `tests/integration/__init__.py` if the package needs it)
- **Change:**
  1. Patterns: `(?i)\bserver listening on\s+(https?://\S+)` and `(?i)\bserver password\s+(\S+)`, applied to each line after stripping `\r` and `\n`. Redaction replaces the secret on any line matching the password pattern with `***`, and also redacts any line containing the exact password string once it is known (so a later echo of it cannot leak).
  2. The fake server prints exactly `server listening on http://127.0.0.1:<port>` and `server password <secret>`, each followed by a newline, as the real one does.
  3. Default config directory: `<aura-app>/.aura/opencode-config` (`.aura/` is already in `.gitignore`); create it if missing.
  4. `tests/integration/test_opencode_real.py`: skipped unless the environment variable `AURA_OPENCODE_REAL_COMMAND` is set (a JSON list, for example `["C:/Users/Mai/AppData/Local/Programs/ai.opencode.desktop/resources/opencode-cli.exe"]`). It starts `OpenCodeProcess` with that command and a temporary `opencode_config_dir`, asserts the version starts with `2.`, asserts `GET /api/agent/{id}` returns 200 for `aura-explore`, `aura-build` and `aura-review`, stops the process, and asserts no output line kept by the process contains the password.
- **Tests:** a unit test feeds the exact real lines (with and without `\r\n`) to the parser and to the redactor, and checks the password never appears in the redacted text or in a start error's message. Run the full suite, then run the integration test once with `AURA_OPENCODE_REAL_COMMAND='["C:/Users/Mai/AppData/Local/Programs/ai.opencode.desktop/resources/opencode-cli.exe"]'` and put its result in the log entry. It must pass.
- **Done when:** the full suite passes, the real-binary integration test passes when run as above, and `git status --short` shows no `opencode-config` directory.
- **Do not:** change the version check or the agent definitions. Do not write to `~/.config/opencode/`.

---


**W3-32 `delegate_work`: brief, task record, session, event folding, budget**
- **PRD:** agency 4.4 steps 1 to 3 and 5, 4.5, 4.1 parity (live step log, abort), rule 8, tests T3 and T5
- **Tier:** frontier
- **Depends on:** W3-28, W3-29, W3-30, W3-31
- **Files:** new `src/aura/tools/delegate.py`, `src/aura/executor/tool_registry.py` (`BUILTIN_MODULES`), new `src/aura/executor/delegation.py`, `src/aura/models/task.py` (fields only if needed), new `tests/unit/test_delegation.py`
- **Change:**
  1. The `delegate_work` tool (risk `execute`, transport `builtin`) with arguments `goal`, `workspace`, `agent` (enum of the three), `success_criteria`, `budget` (`{"tokens": int, "minutes": int}`, both optional with config defaults `delegation_default_tokens: int = 200000`, `delegation_default_minutes: int = 30`), `skill` (optional string, recorded only; skills are G5). No approval-related argument. When `delegation_enabled` is off, the tool returns a clear "delegation is turned off" result and does nothing.
  2. `delegation.py`, `class DelegationRunner`:
     - **Brief:** goal, success criteria, and the Recall Engine's packet in `agent` mode for the goal (`RecallRequest(mode="agent", ...)`), rendered as plain text sections.
     - **Task record:** through the existing `TaskQueueService.create_task` with the workspace path and, once created, the OpenCode session id in the task's `session_id` field.
     - **Session:** `ensure_running`, `create_session(workspace path, agent, title)`, `send(brief)`.
     - **Monitor** (a background task per delegation; rule 8: no model reads the stream): fold events into task steps with `persist_step` (one step per `session.step.ended` or tool call, with a one-line summary built from the event data); on `permission.asked`, take the request, compute `risk_for_action` and `decide(...)` (role `owner`, since only the owner can call tools): `allow` and `deny` answer at once through the client, `ask` creates a decision (W3-30) and sets the task to waiting approval; track tokens from usage events and elapsed time from the clock, and on exceeding the budget call `abort`, then `fail_task(reason="budget exceeded: ...")` (T5); on `session.execution.succeeded` mark the task for review (W3-33); on `failed` or `interrupted`, fail the task with the reason; on `OpenCodeUnavailable` mark the task interrupted (T6) so it can be re-attached.
  3. The tool call returns at once with the task id and "started"; the work continues in the background.
- **Tests:** with a fake `OpenCodeClient` that scripts events: a guest cannot call the tool (the existing role check); flag off does nothing; T3: a `permission.asked` for a shell command creates a pending decision and the task waits, and the session continues only after `DecisionService.answer` (the fake records the reply); a read request is allowed at once; a write outside the workspace is denied at once; T5: usage events past the token budget cause `abort` and a failed task with the reason; steps are persisted; the brief contains the goal, the criteria and the recall text.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** remove the agent loop or the IDE (G4). Do not let any model read the event stream.

---

**W3-33 Review, closing the task, and work into memory**
- **PRD:** agency 4.4 steps 4 and 5, 4.8, test T4
- **Tier:** frontier
- **Depends on:** W3-32
- **Files:** `src/aura/executor/delegation.py`, new `tests/unit/test_delegation_close.py`, new `tests/scenarios/test_delegation_embedded.py`
- **Change:**
  1. When a delegated session succeeds and `result()` shows changed files, start an `aura-review` session in the same workspace with a brief containing the original goal, the success criteria and the diff stats, and ask for a verdict line `VERDICT: PASS` or `VERDICT: FAIL: <reason>` at the end of its final message. Parse it from `result().summary` (a missing verdict counts as `needs_owner`). No changed files: no review.
  2. Close the task as `succeeded` (pass, or no files changed and the session succeeded), `failed` (fail verdict, with the reason) or `needs_owner` (no verdict, or a decision expired), using `TaskQueueService` and adding a `needs_owner` status if the enum lacks one (say so in the log).
  3. Memory (4.8): when `memory_v2_write_enabled` is on, store an episode for the task (user text: the goal; Aura text: the outcome and summary; speaker `owner`; venue `app`) and one fact with provenance `external` and visibility `owner`, "<Aura delegated: goal> in <workspace>: <outcome>", related `derived_from` to that episode. Emit an appraisal event (E2) for the outcome when `emotion_appraisal_enabled` is on: success like `tool_succeeded`, failure like `tool_failed`.
- **Tests:** with the fake client: changed files plus a PASS verdict closes `succeeded`; FAIL closes `failed` with the reason; no verdict gives `needs_owner`; no changed files skips the review. T4 on the embedded engine with the runner: a succeeded task stores the episode and the external fact; skill statistics are G5 and are not asserted.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** start the review with any agent other than `aura-review`.

---


### Wave 3: cards for V1 to V4 (stage, controller, affect, cognitive states), without the MetaHuman steps

Written by the supervisor on 2026-11-20. Mai excluded the MetaHuman steps (the export, the bake, and V8's final asset), so V1 here is only the stage with a placeholder head and the renderer work; the asset build script with budgets and shape pruning (T13, T14) waits for a real asset. The frontend had no test runner, so W3-34 adds one. Avatar PRD rules apply: the controller is written against bone and shape names, never a specific asset; every mapping weight is JSON; no model call between a user message and her first frame; the avatar never blocks the chat (if it fails, the spiral shows). Everything renders only behind `NEXT_PUBLIC_AVATAR_STAGE=1`; the spiral stays the default.

---

**W3-34 A frontend unit test runner**
- **PRD:** avatar 12 (controller tests need a runner)
- **Tier:** bulk
- **Files:** `frontend/package.json`, `frontend/package-lock.json` (through `npm install -D vitest` only), new `frontend/vitest.config.ts`, new `frontend/src/avatar/__tests__/smoke.test.ts`
- **Change:** add `vitest` as a dev dependency, a `"test": "vitest run"` script, a config that runs `src/**/*.test.ts` in the `node` environment with the `@/` path alias the app uses, and one smoke test (`1 + 1 === 2`).
- **Done when:** `npm test` passes from `frontend/` and `npm run build` still passes (the supervisor runs both).
- **Do not:** add any other dependency.

---

**W3-35 Controller skeleton: channels, six layers, ownership, idle life, blink, look-at**
- **PRD:** avatar 7 (layers, ownership table, rules), V2, tests T2 and T6
- **Tier:** frontier
- **Depends on:** W3-34
- **Files:** new `frontend/src/avatar/controller/` (`channels.ts`, `ownership.json`, `layers.ts`, `mixer.ts`, `idle.ts`, `blink.ts`, `lookat.ts`, `events.ts`, `index.ts`), new tests under `frontend/src/avatar/__tests__/`
- **Change:**
  1. `channels.ts`: channel names: the 52 ARKit blend shape names, plus bone channels (`spine`, `chest`, `neck`, `head`, `eyeL`, `eyeR`, shoulders, arms, hands), each with a group (`upperFace`, `lowerFace`, `eyes`, `jaw`, `head`, `body`, `arms`). No asset names.
  2. `ownership.json`: for each group, the layers allowed to write it and their priority, following the PRD table (idle life: body base; affect: brows, lids, cheeks, mouth corners, posture; cognitive: gaze, head tilt, brow modifiers; events: additive pulses; speech: jaw and mouth shapes; gesture: arms, hands, torso, head through masks, never face shapes).
  3. `layers.ts`: a `Layer` interface `update(t: number, dt: number, input: ControllerInput): Partial<Record<Channel, number>>`. `mixer.ts`: combines the six layers' outputs per frame under the ownership table (the winning layer per channel; event pulses add; speech scales lower-face affect to 30% while speaking) and records which layer wrote each channel (for T2).
  4. `idle.ts` (breathing, weight shift, small spine and neck noise from a seeded noise function), `blink.ts` (blinks every 2 to 6 s, also on large gaze shifts), `lookat.ts` (eyes, then head, then a little chest toward a target), `events.ts` (pulses of 200 to 600 ms that return to exactly zero).
  5. Time is passed in (`t`, `dt`); no `Date.now()` or `performance.now()` inside the controller, so tests are deterministic.
- **Tests:** T2: over 600 simulated frames with all layers active, no channel is written by a layer the ownership table does not allow; a gesture never writes a face shape. T6: every event pulse is back to zero within 600 ms. Blink happens within 6 s. Idle output is deterministic for the same seed.
- **Done when:** the new tests pass with `npm test` and `npm run build` passes (the supervisor runs both).
- **Do not:** touch three.js, rendering or the chat page.

---

**W3-36 The affect layer**
- **PRD:** avatar 7.1, V3, tests T3 and T4
- **Tier:** frontier
- **Depends on:** W3-35
- **Files:** new `frontend/src/avatar/controller/affect.ts`, new `frontend/src/avatar/controller/tables/dimension_to_au.json`, new `frontend/src/avatar/controller/tables/au_to_arkit.json`, new tests
- **Change:** input is the emotion deviation (the backend's `deviation` field, E3) and mood (`null` until E4).
  1. Dominant few: the top three dimensions by absolute deviation; a newcomer replaces the current third only after beating it by a margin (`0.05`, in JSON) for 300 ms.
  2. Tables: each of the 27 dimensions to facial action units with weights; action units to ARKit shapes. Both JSON.
  3. Zones: inward dimensions (curiosity, confusion, doubt, certainty, fascination, boredom) weight the upper face; social ones (joy, love, gratitude, empathy, compassion) the lower face (weights in JSON).
  4. Asymmetry: a fixed 5 to 10% left/right offset per expression (seeded by the dimension name).
  5. Eyes lead: upper-face channels move 150 to 250 ms before lower-face ones.
  6. Posture from mood valence and arousal (skip while mood is `null`).
- **Tests:** T4: zero deviation gives exactly the neutral face and pose. T3: two near-equal emotions alternating every 100 ms produce at most one expression change per second. Every dimension name in the table is one of the 27; every shape name is an ARKit name.
- **Done when:** the new tests pass with `npm test` and `npm run build` passes.
- **Do not:** use model calls or the network.

---

**W3-37 `avatar_state` from the backend: cognitive states**
- **PRD:** avatar 8 (cognitive states from the pipeline trace, no model call), 11 (`avatar_state` protocol), V4, test T7
- **Tier:** frontier
- **Files:** new `src/aura/avatar/__init__.py`, new `src/aura/avatar/state.py`, `src/aura/api/websocket.py` (a broadcast helper), the call sites that start and finish recall, L3 reasoning, delegation and dreaming (only to emit a state event), new `tests/unit/test_avatar_state.py`
- **Change:**
  1. `state.py`: `class AvatarStateMachine` with states `attending`, `recalling`, `thinking`, `unsure`, `found_it`, `surprised`, `working`, `curious`, `resting`, `idle`, fed by small events (`message_received`, `recall_started`, `recall_finished(abstain: bool, strong: bool)`, `reasoning_started`, `reasoning_finished`, `delegation_running(bool)`, `dreaming(bool)`, `prediction_error(size)`). It builds the PRD 11 payload (`deviation` from the emotion engine's state, `mood: null`, `cognitive_state`, `events`, `speaking: false`, `gaze_target`).
  2. Broadcast `{"type": "avatar_state", ...}` on change, at most 10 times a second (coalesce within 100 ms), through the existing websocket manager.
  3. Emit the events from the existing pipeline points: when the Recall Engine runs, when L3 starts and ends, when a delegated task runs, when dreaming starts and ends.
- **Tests:** T7: a replayed sequence for one turn (`message_received`, `recall_started`, `recall_finished`, `reasoning_started`, `reasoning_finished`) produces `attending`, `recalling`, `thinking`, `attending` in order; `abstain` gives `unsure`; the rate limit holds (20 changes in 100 ms broadcast at most twice); no model is called (the state machine has no client).
- **Done when:** the new tests pass and the full Python suite passes (the supervisor runs it).
- **Do not:** add a model call anywhere on this path.

---

**W3-38 The cognitive layer in the client, and the stage with a placeholder head**
- **PRD:** avatar 6 (renderer, pixel ratio, framing), 7 (layer 3), 5.4 (placeholder head with ARKit names), V1 (without export and bake), V4, test T16
- **Tier:** frontier
- **Depends on:** W3-36, W3-37
- **Files:** new `frontend/src/avatar/controller/cognitive.ts`, new `frontend/src/avatar/AvatarStage.tsx`, new `frontend/src/avatar/placeholderHead.ts`, `frontend/src/services/socketService.ts` (subscribe to `avatar_state`), `frontend/src/pages/chat.tsx` (only to render the stage instead of the spiral when `NEXT_PUBLIC_AVATAR_STAGE=1`), new tests
- **Change:**
  1. `cognitive.ts`: layer 3, mapping each cognitive state to gaze target, head tilt and brow modifiers (values in JSON), with smooth transitions.
  2. `placeholderHead.ts`: a head built in code (no downloaded asset, so no licence entry is needed) with morph targets named after the ARKit shapes the tables use, simple displacements per shape. Rule 2: nothing in the controller depends on it.
  3. `AvatarStage.tsx`: uses the installed `three` (0.169; upgrading three is left for the asset milestone) with `WebGLRenderer`, pixel ratio capped at 1.5 on narrow screens and 2.0 otherwise, portrait framing, the controller driving the placeholder's morph targets each frame. Any error while loading or rendering falls back to the spiral (rule 6). Render only when `NEXT_PUBLIC_AVATAR_STAGE=1`.
- **Tests:** the cognitive layer's outputs per state; the stage module can be imported without a browser (no top-level DOM access); a forced load error renders the spiral (test the fallback function, not the canvas).
- **Done when:** the new tests pass with `npm test`, `npm run build` passes, and the chat page without the flag is unchanged (the supervisor runs these).
- **Do not:** upgrade `three`, add WebGPU, or add any asset file.

---


### Wave 4: cards for M5 (entity, graph and temporal channels, rerank, recall tools, feedback)

Written by the supervisor on 2026-11-20 against the code after wave 3. All of it works on the v2 fact path (`_build_fact_memories` in `engines/recall/engine.py`, used when `recall_channels_enabled` and `memory_v2_recall_enabled` are on). Each new channel and mechanism has its own flag, off by default, and an ablation test (memory PRD rule 7). Weights and thresholds live in config (rule 8). No model call on the fast path (rule 9). Every query is parameterised; the KNN `k`/`ef` integer rule from the M3 notes still applies. Visibility filtering (`visible_in_venue`) applies to every channel before ranking.

---

**W4-01 The entity channel**
- **PRD:** memory 6.3 step 2 (entities by alias in the last two turns) and step 3 (entity channel: current facts `about` each matched entity)
- **Tier:** bulk
- **Files:** `src/aura/engines/recall/query.py`, `src/aura/engines/recall/channels.py`, `src/aura/engines/recall/engine.py` (`_build_fact_memories`), `src/aura/config.py`, new `tests/scenarios/test_recall_entity_channel_embedded.py`
- **Change:**
  1. Config: `recall_entity_channel_enabled: bool = False`, `recall_entity_k: int = 20`.
  2. `RecallQueries` gains `entity_aliases: list[str]` (default empty): every lowercased word and adjacent word pair of the input and the previous user turn, minus stop words, capped at 30. `build_queries` stays free of database access.
  3. `channels.py`: `async def fact_entity_channel(db, aliases: list[str], venue: str) -> list[ChannelHit]`: entities whose `aliases` contain any of the candidates (`aliases CONTAINSANY $aliases`), then current, visible facts `about` them, newest `recorded_at` first, up to `recall_entity_k`; score 1.0 for every hit (rank carries the order).
  4. In `_build_fact_memories`, when the flag is on, run it in the same `asyncio.gather` as dense and lexical, and fuse it as channel `"entity"`.
- **Tests:** on the embedded engine with the runner: a question naming an entity by an alias ("what does Pixel eat?") finds facts about that entity that share no words with the question; another venue's fact about the same entity is not returned; the flag off gives exactly the M4 behaviour (ablation).
- **Done when:** the new tests pass and the full suite passes (the supervisor runs the suite).

---

**W4-02 The temporal channel**
- **PRD:** memory 6.3 step 2 (a date range when the input contains a time expression) and step 3 (temporal channel)
- **Tier:** bulk
- **Files:** new `src/aura/engines/recall/timeexpr.py`, `src/aura/engines/recall/query.py`, `src/aura/engines/recall/channels.py`, `src/aura/engines/recall/engine.py`, `src/aura/config.py`, new `tests/unit/test_timeexpr.py`, new `tests/scenarios/test_recall_temporal_channel_embedded.py`
- **Change:**
  1. `timeexpr.py`: `def parse_range(text: str, now: datetime) -> tuple[datetime, datetime] | None` for English rules only: `today`, `yesterday`, `last week`, `this week`, `last month`, `this month`, `N days/weeks/months ago` (a day, week or month window around that point), weekday names (`on Monday` = the most recent past Monday), month names (`in March` = the most recent past March), ISO dates (`2026-11-02`). `now` comes from `get_clock()` at the call site.
  2. `RecallQueries` gains `time_range: tuple[datetime, datetime] | None`.
  3. `fact_temporal_channel(db, time_range, venue)`: visible facts whose `valid_from` or `recorded_at` falls in the range (superseded ones included, because a question about a time is a question about the past), newest first, capped by `recall_temporal_k: int = 20`. Flag `recall_temporal_channel_enabled: bool = False`.
- **Tests:** each rule with a fixed `now`; no range for text without a time expression; on the embedded engine with the runner's clock, "what did I say yesterday?" returns yesterday's facts and not older ones; ablation.
- **Done when:** the new tests pass and the full suite passes.

---

**W4-03 The graph channel: Personalised PageRank**
- **PRD:** memory 6.3 step 3 (graph channel: PPR from the hits of the first three channels over typed edges, subgraph capped at 500 nodes, `supersedes` never followed forward, `co_used` and `about` strong, `mentions` weak, high-degree nodes damped)
- **Tier:** frontier
- **Depends on:** W4-01
- **Files:** new `src/aura/engines/recall/graph.py`, `src/aura/engines/recall/channels.py`, `src/aura/engines/recall/engine.py`, `src/aura/config.py`, `scripts/schema_v2.surql` (only the `co_used` relation, fact to fact, with a `weight` float default 1), new `tests/unit/test_recall_graph.py`, new `tests/scenarios/test_recall_graph_channel_embedded.py`
- **Change:**
  1. `graph.py` (pure, no I/O): `def personalised_pagerank(edges: list[tuple[str, str, float]], seeds: dict[str, float], alpha: float, iterations: int, degree_damping: float) -> dict[str, float]` over an undirected weighted graph, where each node's outgoing weight is divided by `degree ** degree_damping`.
  2. Loader: starting from the seed facts (the dense, lexical and entity hits), expand breadth-first through `about` (fact to entity and back), `co_used`, `derived_from` (fact to episode and back) and `mentions`, never following `supersedes` from old to new, until 500 nodes. Edge weights from config: `recall_graph_weights = {"about": 1.0, "co_used": 1.0, "derived_from": 0.5, "mentions": 0.2}`; `recall_graph_alpha = 0.15`, `recall_graph_iterations = 20`, `recall_graph_degree_damping = 0.5`.
  3. `fact_graph_channel`: the visible, current facts ranked by PPR score, excluding the seeds themselves, capped by `recall_graph_k: int = 20`; flag `recall_graph_channel_enabled: bool = False`; runs after the first three channels and is fused as `"graph"`.
- **Tests:** PPR on a hand-built graph: a node two hops from the seed through strong edges outranks one through weak edges; a hub's score is damped; `supersedes` is not followed forward. Multi-hop on the embedded engine: "where does my sister live?" finds "Ana lives in Porto" through "My sister is called Ana" (seed found by dense/lexical, target reached through the shared entity), which no other channel finds; ablation.
- **Done when:** the new tests pass and the full suite passes.

---

**W4-04 Rerank on features**
- **PRD:** memory 6.3 step 5
- **Tier:** frontier
- **Depends on:** W4-03
- **Files:** new `src/aura/engines/recall/rerank.py`, `src/aura/engines/recall/engine.py`, `src/aura/config.py`, new `tests/unit/test_recall_rerank.py`
- **Change:** after fusion and before the limit, when `recall_rerank_enabled: bool = False`: drop superseded facts unless a time range was detected (W4-02); drop `imagined` facts unless `request.mode == "creative"`; multiply the fused score by a provenance weight (`observed 1.0`, `external 0.9`, `inferred 0.8`, `hearsay 0.6` in config), by `0.5 + 0.5 * confidence`, by `1 + 0.2 * salience`, and by a slow decay `exp(-age_days / recall_rerank_decay_days)` with `recall_rerank_decay_days = 365`; add emotional resonance `0.10 * cosine(fact signature minus baseline, current deviation)`, capped at zero when the current state's negative dimensions dominate (sum of fear, sadness, anger, shame, disgust deviations above the positive ones); then maximal marginal relevance (`lambda = 0.7`) on the fact embeddings to pick the final order. All numbers in config.
- **Tests:** each rule on hand-built candidates; MMR keeps one of five near-identical facts in the top three; ablation (flag off leaves the fused order).
- **Done when:** the new tests pass and the full suite passes.

---

**W4-05 Recall tools**
- **PRD:** memory 6.4
- **Tier:** bulk
- **Files:** new `src/aura/tools/recall_tools.py`, `src/aura/executor/tool_registry.py` (`BUILTIN_MODULES`; the tool counts in `tests/unit/test_tool_registry.py` change with it), `src/aura/engines/recall/engine.py` (`timeline` and `evidence` reimplemented on v2 tables when `memory_v2_recall_enabled` is on), new `tests/scenarios/test_recall_tools_embedded.py`
- **Change:** tools, risk `read`, all filtered by the caller's venue visibility: `recall(query, filters)` (ranked facts with provenance, through the Recall Engine's fact path), `timeline(entity or date range)` (ordered episodes and facts), `evidence(fact_id)` (the episodes the fact was `derived_from`), `what_changed(entity)` (the `supersedes` chain for facts about that entity, oldest first). `pin(fact_id)` and `unpin(fact_id)` are risk `write` and owner-only (the existing role check). Each returns plain text the model can read. The old `timeline`/`evidence` behaviour stays when the v2 flag is off.
- **Tests:** each tool on the embedded engine with seeded facts and edges; `what_changed` returns Lisbon then Porto; a guest venue cannot see an owner fact through any tool; a guest cannot pin.
- **Done when:** the new tests pass and the full suite passes.

---

**W4-06 Feedback: which recalled facts the reply used**
- **PRD:** memory 6.5
- **Tier:** frontier
- **Depends on:** W4-03 (the `co_used` relation)
- **Files:** new `src/aura/engines/recall/feedback.py`, `src/aura/orchestrator/coordinator.py` (`_post_response_chain`: call it with the turn's packet and the reply), `src/aura/config.py`, `scripts/schema_v2.surql` (`unused_streak` int DEFAULT 0 on `fact`), new `tests/scenarios/test_recall_feedback_embedded.py`
- **Change:** when `recall_feedback_enabled: bool = False` is on and the packet came from the fact path: a fact counts as used when the lexical overlap between the reply and the fact's content (content words, stop words removed) is at least `recall_feedback_min_overlap = 0.3`, or the embedding similarity of the reply and the fact is at least `recall_feedback_min_similarity = 0.6`. For used facts, one atomic update: `use_count += 1`, `last_used_at = now`, `unused_streak = 0`; relate or strengthen `co_used` (weight `+ 1`) between every pair of used facts. For injected but unused facts, `unused_streak += 1`; W4-04's rerank multiplies by `recall_unused_penalty = 0.9` when `unused_streak >= 5`. Never on Aura's text alone: the reply is compared with facts, nothing from the reply is stored.
- **Tests:** a reply quoting one of three injected facts marks only that one used; two used facts get a `co_used` edge whose weight grows on repetition; five unused turns trigger the penalty; ablation.
- **Done when:** the new tests pass and the full suite passes.

---

**W4-07 M5 probes: multi-hop and temporal**
- **PRD:** memory M5 gate ("multi-hop and temporal probes pass")
- **Tier:** bulk
- **Depends on:** W4-01..W4-06
- **Files:** new `tests/scenarios/test_memory_m5_embedded.py`, new `docs/metrics/m5.md`
- **Change:** scenarios through the runner with every M3, M4 and M5 flag on and scripted extractions: five multi-hop questions (answers two hops away through an entity) and five temporal questions ("yesterday", "last week", "in March", "3 days ago", an ISO date). Record the share answered (the right fact in the memories block) for each set, with and without the M5 flags, to `docs/metrics/m5.md` only when `RECORD_BASELINE=1` (use `write_baseline`).
- **Tests:** these are the tests: with the flags on, at least 4 of 5 in each set; the numbers are recorded either way.
- **Done when:** the tests pass and the full suite passes; the supervisor records the metrics.

---

### Wave 4: cards for M6 (dreaming v2)

Written by the supervisor on 2026-11-23 against the code after M5. The memory v2 dream phases run inside `DreamingEngine.enter_rem_sleep` (`src/aura/engines/dreaming/engine.py`) when `dreaming_v2_enabled: bool = False` is on and `memory_v2_write_enabled` is on; the existing phases (pruning of the old `memory` table, abstraction, emotional reprocessing, causal weaving, trial and error) keep running unchanged (memory PRD 7.5). Every time read goes through `get_clock()`. Model calls are allowed in dreaming (it is off the reply path) but go through the existing LLM layers / clients, and every phase has a per-cycle cap in config so one cycle stays bounded. Visibility is never widened by consolidation: anything built from facts keeps the visibility of the facts it was built from, and never mixes visibilities.

---

**W4-08 Dream cycle v2: retry extraction**
- **PRD:** memory 7.1
- **Tier:** bulk
- **Files:** `src/aura/engines/dreaming/engine.py`, `src/aura/config.py`, new `tests/scenarios/test_dreaming_v2_retry_embedded.py`
- **Change:**
  1. Config: `dreaming_v2_enabled: bool = False`, `dreaming_retry_batch: int = 20`, `dreaming_retry_min_age_minutes: int = 10`.
  2. In `enter_rem_sleep`, when the flag (and `memory_v2_write_enabled`) is on, a new phase before the existing ones: select episodes with `extraction_status = "pending"` and `recorded_at` older than `dreaming_retry_min_age_minutes` (from `get_clock()`), oldest first, up to `dreaming_retry_batch`, and call `run_extraction(db, client, episode_id)` (`src/aura/engines/memory/v2/extraction.py`) for each, one at a time. Use the same extraction client the write path uses (see `episodes.py`, where `run_extraction` is scheduled). Count successes into the report (add `retried: int = 0` and `extracted: int = 0` to `DreamConsolidationReport` if it is a model you can extend; otherwise log them).
  3. `tick` uses `get_clock().now()` instead of `datetime.now(timezone.utc)`.
- **Tests:** on the embedded engine with the runner and a fake extraction client (scripted reply): a pending episode older than the minimum age is extracted and its facts written; a fresh one and a `failed` one are left alone; a failing client increments `extraction_attempts` and leaves the episode pending until the maximum; the batch cap holds; flag off: nothing happens (ablation).
- **Done when:** the new tests pass and the full suite passes (the supervisor runs the suite).

---

**W4-09 Archive, do not delete**
- **PRD:** memory 7.4
- **Tier:** bulk
- **Files:** `scripts/schema_v2.surql` (`archived` bool DEFAULT false on `fact` and `episode`, with an index on each), `src/aura/engines/dreaming/engine.py`, `src/aura/engines/recall/channels.py` and `src/aura/engines/recall/engine.py` (every v2 read path), `src/aura/config.py`, new `tests/scenarios/test_dreaming_v2_archive_embedded.py`
- **Change:**
  1. Config: `dreaming_archive_superseded_days: int = 90`, `dreaming_archive_ephemeral_days: int = 7`.
  2. A dream phase (flag `dreaming_v2_enabled`): `UPDATE fact SET archived = true WHERE valid_to IS NOT NONE AND valid_to < $cutoff AND archived = false AND pinned = false`; `UPDATE episode SET archived = true WHERE ephemeral = true AND recorded_at < $cutoff AND archived = false`. Nothing in the v2 tables is ever deleted by dreaming.
  3. Every v2 read excludes archived rows: `_fact_filter_clause` (dense, lexical, entity, graph results), the temporal channel (which keeps superseded facts but not archived ones), the graph loader's node set, and the recall tools' `timeline`, `evidence` and `what_changed` (`what_changed` keeps the chain but marks an archived link "(archived)" rather than dropping it, so history stays explainable). `evidence` on an archived episode still returns it (the evidence is the point).
- **Tests:** a superseded fact 91 days old is archived and a pinned one is not; a superseded fact 89 days old is not; an ephemeral episode 8 days old is archived, a non-ephemeral one is not; an archived fact is found by no channel, including temporal with a matching range; `what_changed` shows it marked; ablation.
- **Done when:** the new tests pass and the full suite passes.

---

**W4-10 Themes: communities, summaries, prioritised replay**
- **PRD:** memory 7.2 and 7.3
- **Tier:** frontier
- **Depends on:** W4-08
- **Files:** new `src/aura/engines/dreaming/themes.py`, `src/aura/engines/dreaming/engine.py`, `scripts/schema_v2.surql` (`theme`: add `visibility` string, `embedding`, `updated_at`, `fact_count`; new relation `member_of` fact -> theme; `entity`: add `summary_updated_at` option<datetime>), `src/aura/config.py`, new `tests/unit/test_dream_themes.py`, new `tests/scenarios/test_dreaming_v2_themes_embedded.py`
- **Change:**
  1. Prioritised replay: the facts considered in a cycle are the top `dreaming_replay_batch = 200` current, unarchived facts by `salience * exp(-age_days / dreaming_replay_recency_days)` with `dreaming_replay_recency_days = 14`, plus every fact recorded since the last cycle.
  2. Communities (pure function in `themes.py`, no I/O): weighted label propagation (deterministic: fixed iteration order, ties broken by smallest label) over the fact-entity graph built from `about` and `co_used` among the replayed facts and their neighbours, per visibility (a theme never mixes visibilities). Keep communities with at least `dreaming_theme_min_facts = 4` facts.
  3. For each community, match an existing theme when at least half of its members are already `member_of` that theme (update it), otherwise create one; write a summary of at most `dreaming_theme_summary_words = 80` words with one model call per changed theme (prompt with the member facts' content only), embed it, and set `member_of` edges. Cap the model calls per cycle with `dreaming_theme_max_per_cycle = 10`.
  4. Entity summaries: for entities with facts recorded after their `summary_updated_at`, rewrite `summary` from their current facts (one call each, capped by `dreaming_entity_summary_max_per_cycle = 10`), per visibility: only owner-visible facts go into the stored summary (the summary is a field on a shared entity, so it must not carry guild or private facts).
- **Tests:** label propagation on a hand-built graph (two clusters joined by one weak edge come out as two communities; deterministic across runs); replay ordering; a theme is created once and updated, not duplicated, on the next cycle; no theme mixes visibilities; the entity summary ignores guild and private facts; the per-cycle caps hold; ablation. Use a scripted fake model client, never a real one.
- **Done when:** the new tests pass and the full suite passes.

---

**W4-11 Theme recall**
- **PRD:** memory 7.3 (themes as a source for long-topic questions; M6 gate "long-topic probes pass")
- **Tier:** frontier
- **Depends on:** W4-10
- **Files:** `src/aura/engines/recall/channels.py`, `src/aura/engines/recall/engine.py`, `src/aura/config.py`, new `tests/scenarios/test_recall_themes_embedded.py`
- **Change:** flag `recall_themes_enabled: bool = False`. After fusion on the fact path: a theme qualifies when it is visible in the venue and either its embedding is within `recall_theme_min_similarity = 0.55` of the query embedding, or at least `recall_theme_min_members = 2` of the fused facts are `member_of` it. At most `recall_theme_k = 1` theme is rendered, as a `<theme>` line at the top of the memories block (counted in the token budget like the facts, deduplicated by the existing assembly); its member facts keep their own lines. One batched query; no model call.
- **Tests:** a broad question ("how is the house renovation going?") over twelve renovation facts spread across weeks gets the theme line; a guild venue never gets an owner theme; the token budget still holds; ablation.
- **Done when:** the new tests pass and the full suite passes.

---

**W4-12 M6 probes: long topics and 90 simulated days**
- **PRD:** memory M6 gate ("long-topic probes pass, memory stable over 90 simulated days")
- **Tier:** bulk
- **Depends on:** W4-08..W4-11
- **Files:** new `tests/scenarios/test_memory_m6_embedded.py`, new `docs/metrics/m6.md`
- **Change:** through the runner with every M3 to M6 flag on, a scripted fake extraction client and a fake model client for summaries: 90 simulated days, a few turns a day across three long topics, a handful of updated facts, ephemeral chatter, and a dream cycle every simulated night. Probes at day 30, 60 and 90: five long-topic questions (answered when the topic's theme line or at least two of its facts are in the memories block), five single-fact questions from the first week (the fact still recalled), and the updated-fact probes from M4 (the newest value present, the old one absent). Stability numbers: facts, archived facts, themes, entities and episodes per probe day (bounded growth: themes do not multiply for an unchanged topic). Record to `docs/metrics/m6.md` only when `RECORD_BASELINE=1` (`write_baseline` in `tests/conftest.py`).
- **Tests:** at least 4 of 5 long-topic and 5 of 5 single-fact probes on each probe day; updated facts correct; theme count for the three topics stays at three or fewer per visibility.
- **Done when:** the tests pass and the full suite passes; the supervisor records the metrics.

---

### Wave 4: cards for E4 and E5 (mood, relationships, venue caps)

Written by the supervisor on 2026-11-23 against the code after M6. The emotion engine is `src/aura/engines/emotion/engine.py`; every state change goes through `appraise(event: AppraisalEvent)` (W3-20..W3-26), which turns appraisal variables into impulses (`engines/emotion/appraisal.py`, `impulses_for`), applies them through the physics, and writes an `emotion_event` with `person_id`, `venue` and `size`. Every time read goes through `get_clock()`. Each mechanism has its own flag, off by default, and an ablation test; every number is in config.

---

**W4-13 Mood**
- **PRD:** emotion 6.2, test T12
- **Tier:** frontier
- **Files:** new `src/aura/engines/emotion/mood.py`, `src/aura/engines/emotion/engine.py`, `src/aura/models/emotion.py` (the existing `EmotionState.mood` field), `src/aura/config.py`, new `tests/unit/test_emotion_mood.py`
- **Change:**
  1. Flag `emotion_mood_enabled: bool = False`. Mood is three numbers, `valence`, `arousal`, `control`, each in [-1, 1], a running average of the state's projection with a half-life of `emotion_mood_half_life_hours = 8.0`, advanced by real elapsed time (`get_clock()`) on every tick and every appraisal. The projections are weighted sums over the 27 dimensions' deviations from baseline, with the weights in config (`emotion_mood_valence_weights`, `emotion_mood_arousal_weights`, `emotion_mood_control_weights`; reuse the positive/negative split already used by `_compute_valence` for valence), clamped to [-1, 1]. The pure maths (projection, decay step) lives in `mood.py`.
  2. Effective baseline: while the flag is on, the physics decays toward the configured baseline plus a mood shift on the positive dimensions only, `clamp(emotion_mood_baseline_gain * mood.valence, -emotion_mood_baseline_shift_max, +emotion_mood_baseline_shift_max)` with `emotion_mood_baseline_shift_max = 0.1`. The configured baseline itself never changes.
  3. Appraisal bias (separate flag `emotion_mood_appraisal_bias_enabled: bool = False`, for ablation): for an ambiguous event (`abs(goal_congruence) < 0.3`), shift `goal_congruence` by `emotion_mood_appraisal_bias * mood.valence`, capped at `±0.1`, before `impulses_for`. Record the unbiased appraisal on the `emotion_event` and the bias applied as its own field.
  4. Persistence: mood is saved with the state (`_persist_state` / `_load_state` / `_hydrate_physics_from_db` — follow the existing pattern) with its timestamp, and on load it decays by the real elapsed time since then (no cap). `EmotionState.mood` is filled when the flag is on (the websocket and prompt already carry the field).
- **Tests:** T12: a simulated day of negative events (fake clock, appraisals every few minutes) lowers the effective baseline by no more than 0.1 and it recovers over the following days (most of the way back after three days without events); positive day raises it symmetrically; the projection and decay maths on fixed inputs; the bias stays within its cap and is absent with its flag off; restart: mood saved, clock moved 16 hours, loaded mood is a quarter of what it was; ablation (flag off: physics and appraisal exactly as today).
- **Done when:** the new tests pass and the full suite passes (the supervisor runs the suite).

---

**W4-14 Relationships on person entities**
- **PRD:** emotion 6.3, finding E6, test T10
- **Tier:** frontier
- **Depends on:** W4-13 (same engine paths; no functional dependency)
- **Files:** new `src/aura/engines/emotion/relationship.py`, `src/aura/engines/emotion/engine.py`, `scripts/schema_v2.surql` (on `entity`: `affection`, `trust`, `familiarity`, `tension` as `option<float>`, `relationship_updated_at` as `option<datetime>` — new fields on a table with rows must be `option<...>`, read missing as the configured starting values), `src/aura/config.py`, the call sites that build message `AppraisalEvent`s (they must carry the speaker's entity id as `person_id` — find them; the speaker entity is the one the memory write path uses for `episode.speaker`, see `src/aura/engines/memory/v2/episodes.py`), new `tests/unit/test_emotion_relationship.py`, new `tests/scenarios/test_emotion_relationship_embedded.py`
- **Change:**
  1. Flag `emotion_relationships_enabled: bool = False`. Starting values for a person never seen: `affection 0.0`, `trust 0.3`, `familiarity 0.0`, `tension 0.0` (config); the owner's starting values are config too (`affection 0.5`, `trust 0.7`, `familiarity 0.6`).
  2. Updates, after each appraised event with a `person_id`, one parameterised `UPDATE` on that entity (pure step function in `relationship.py`, all step sizes in config, small: about 0.01 to 0.03 per event, every field clamped to [0, 1]): `familiarity` rises with every exchange, with diminishing returns; `affection` rises with positive warmth and positive congruence when the agency is the other person, and falls slowly with negative warmth; `tension` rises with negative congruence or negative warmth from the other person and eases with later positive warmth (repair); `trust` rises when an event confirms an expectation and falls when one is broken (use the appraisal's `certainty`/`goal_congruence` with agency other as the proxy, and say so in the docstring). No time decay.
  3. When a person is present (the event's `person_id`), the effective baseline of the `love` and `trust` dimensions comes from that relationship (`love` from `affection`, `trust` from `trust`, scaled into the dimension's range by config) instead of the global configured values, so the state moves toward a different resting point for the owner than for a stranger. In a channel with several people the current speaker's relationship is used (it is the event's `person_id`).
  4. The relationship scales the message's impulses: positive-warmth impulses are multiplied by `1 + emotion_relationship_warmth_gain * (affection + familiarity) / 2`; for a person with `familiarity < emotion_stranger_familiarity` the negative impulses are capped at `emotion_stranger_hostility_cap` per event.
  5. `get_state(person_id)` returns the state with `love` and `trust` read from that person's relationship (replacing the "E5 is not implemented" stub).
- **Tests:** T10: the same warm message from the owner and from a new guest produces a larger response (sum of positive impulses applied) for the owner; step functions on fixed inputs (familiarity diminishing returns, tension rises then eases with repair, clamping); relationship fields written to the right entity and nothing written for an event without `person_id`; a stranger's single hostile message is capped; `get_state` for two people differs in love and trust; ablation.
- **Done when:** the new tests pass and the full suite passes.

---

**W4-15 Venue caps for guests**
- **PRD:** emotion 7 ("venue caps"), test T11
- **Tier:** bulk
- **Depends on:** W4-14
- **Files:** `src/aura/engines/emotion/engine.py`, `src/aura/config.py`, new `tests/unit/test_emotion_guest_cap.py`
- **Change:** flag `emotion_guest_cap_enabled: bool = False`. An event is a guest event when its `person_id` is not the owner's entity (an event with no `person_id` is not capped). Guest events together may move her state by at most `emotion_guest_cap_per_hour = 0.5`, measured as the sum of the `size` of guest `emotion_event`s in the last hour (sliding window; query the table, or keep an in-memory window that is rebuilt from the table on load — pick one and say why). Before applying a guest event's impulses, scale them so its size fits the remaining budget; with no budget left the event is recorded with `size 0` and a `capped: true` field, and the state does not move.
- **Tests:** T11: 100 hostile guest messages in one simulated hour move the state (sum of sizes, and the actual deviation) by no more than the cap; the budget frees up as the window slides; owner events are never capped and do not use the budget; ablation.
- **Done when:** the new tests pass and the full suite passes.

---


### Wave 5 (Phase 2 order): cards for G4 (Workbench, blocker monitor, then removal of the agent loop and the IDE)

Written 2026-11-23 against commit 85996ab. Agency PRD 4.1 (removal and parity table), 4.5, 4.6, tests T15 to T17. G4 runs before Phase 2 Part 4 (P2-08 to P2-11), which builds on what it leaves. Order: G4-01, G4-02, G4-03, then G4-04 (parity), then G4-05 (removal) last.

**G4-01 Delegation registry and controls API**
- **PRD:** agency 4.1 parity rows "Abort, pause all, abort all" and "Guidance injected mid-task", 4.6
- **Tier:** bulk
- **Files:** `src/aura/executor/delegation.py`, new `src/aura/api/routes/delegations.py`, `src/aura/main.py` (router), `src/aura/config.py`, new `tests/unit/test_delegation_controls.py`
- **Change:**
  1. A module-level registry in `delegation.py`: `task_id -> DelegationRunner` for running runners, added in `run()` and removed in a `finally`. No unbounded growth.
  2. `pause_all` state: a module flag that makes `delegate_work` refuse new delegations with a clear error ("delegations are paused") while running sessions continue. OpenCode has no session pause, so this is the honest meaning of "pause all". Say so in the docstring.
  3. Routes under `/delegations`:
     - `GET /delegations`: delegated tasks (running and the last 50 closed) with state, brief, session id, workspace, budget use, the last 20 steps and any pending decision ids.
     - `GET /delegations/{task_id}`: one task with all its steps.
     - `POST /delegations/{task_id}/abort`: `OpenCodeClient.abort(session_id)`, then the task fails with reason "aborted by owner".
     - `POST /delegations/abort-all`, `POST /delegations/pause-all` and `POST /delegations/resume-all`.
     - `POST /delegations/{task_id}/guidance` `{text}`: `OpenCodeClient.send(session_id, text)` into the running session. The text is recorded as a task step, kind "guidance".
     - `GET /delegations/{task_id}/diff`: the diff from `OpenCodeClient.result` or the session diff endpoint, never from local files.
     - `GET /delegations/opencode-url`: the managed server's base URL (no auth in the response), for the "open in OpenCode" link.
  4. Every route checks that the task is a delegated task (it has a session id). They are unauthenticated like the rest of the API; the FOR_MAI item already covers that.
- **Tests:** registry add and remove (including on failure); abort calls the client and fails the task; guidance reaches `send` and is recorded; pause-all refuses `delegate_work` while a running runner continues; abort-all reaches every running runner; the diff comes from the client fake. Fake `OpenCodeClient` only.
- **Done when:** the new tests pass and the full suite passes.

**G4-02 Blocker monitor, heartbeat, emotion per step, re-attach**
- **PRD:** agency 4.1 parity rows "Blocker detection", "Suggested next action", "Heartbeat", "Emotional snapshot per step", "Step persistence and resume after restart"
- **Tier:** frontier
- **Depends on:** G4-01
- **Files:** `src/aura/executor/delegation.py` (`_monitor`, `_persist_step_from_event`), `src/aura/executor/task_queue.py`, `src/aura/main.py` (startup recovery), `src/aura/config.py`, new `tests/unit/test_delegation_monitor.py`
- **Change:**
  1. Blocker monitor in `_monitor`. These fire a blocker:
     - an error streak of `delegation_error_streak` (default 3) failed tool events in a row;
     - a loop of the same tool with the same normalised arguments `delegation_repeat_limit` times (default 4);
     - 80% of the time or token budget used.

     On a blocker: `set_blocker_info` on the task, and a `needs_decision` item through the decisions service with the reason and the last 5 steps. Fire once per blocker kind per task.
  2. Suggested next action: when a blocker fires, one background L2 call (`settings.active_l2_model`, never awaited inside the event loop of `_monitor`) drafts a one-paragraph suggestion from the brief and the last steps. It is stored on the blocker info. If the call fails, the blocker stands without a suggestion.
  3. Heartbeat: every `delegation_heartbeat_seconds` (default 60) while running, a status step "still working: <last step summary>, <n> steps, <minutes> min". No model call.
  4. Emotion per step: each persisted step stores `emotion` (the top 3 dimensions and values from `EmotionEngine.get_current_state()`). A failure to read the state never blocks the step.
  5. Re-attach after restart: at startup, tasks interrupted by the restart that still have a session id and whose OpenCode session is still running (check the session status through the client) get a new `DelegationRunner` monitor attached instead of being marked interrupted. If OpenCode is not running or the session ended, keep today's behaviour.
  6. All numbers in config with `AURA_` aliases. Time comes from `get_clock()`.
- **Tests:** each blocker kind fires once and creates one decision; the suggestion is stored, and a failed call still leaves the blocker; the heartbeat appears with a FakeClock moved past the interval; the step carries an emotion snapshot; re-attach with a running session versus an ended one. Fake client, fake LLM.
- **Done when:** the new tests pass and the full suite passes.

**G4-03 Workbench page**
- **PRD:** agency 4.6
- **Tier:** bulk
- **Depends on:** G4-01, G4-02 (it shows their data)
- **Files:** new `frontend/src/pages/workbench.tsx`, new `frontend/src/components/workbench/` (TaskList, StepLog, DiffView, DecisionBar, GuidanceBox), the nav component that links to `/ide`, `frontend/src/services/` (API client)
- **Change:**
  1. Left: the delegated task list with state badges, filterable by running or closed.
  2. Right, for the selected task: the brief; the live step log, polling `GET /delegations/{id}` every 2 s while running and stopping when closed (guidance, heartbeat and blocker steps styled distinctly, emotion shown as a small tag); changed files with the diff; pending decisions with approve and deny (the existing decisions API); abort; a guidance box; the blocker with its suggestion; and an "Open in OpenCode" link from `/delegations/opencode-url`.
  3. Bulk controls: pause all, resume all and abort all, with a confirm dialog for abort all.
  4. Replace the nav link to `/ide` with `/workbench`. The IDE page itself is removed in G4-05, not here.
  5. Use the existing glass-panel styles; no new dependencies.
- **Tests:** vitest render tests with fixture data: the list, step log kinds, decision buttons calling the API, the abort-all confirm, and polling stopping when the task is closed.
- **Done when:** `npm test` and `npm run build` pass, and the full Python suite passes.

**G4-04 Parity and built-in tools (T16, T17)**
- **PRD:** agency 4.1 parity table, tests T16 and T17
- **Tier:** bulk
- **Depends on:** G4-01 to G4-03
- **Files:** new `tests/unit/test_g4_parity.py`, new `docs/metrics/g4_parity.md`, `docs/FOR_MAI.md`
- **Change:**
  1. T16: for each row of the parity table in PRD 4.1, a test that proves it with the new path (fake OpenCode client), or a row in `g4_parity.md` saying which manual check covers it and why it can't be automated. Rows already covered by G3 or G4-01/02 tests get a reference to the existing test (file::name) instead of a duplicate.
  2. T17: for every built-in tool in the PRD 4.1 "kept" table, the owner can call it through the executor in a temp directory, and its registered schema has no approval argument (`force_execute` or `_`-prefixed). Reuse the registry's existing schema filter in the assertion; don't re-implement it.
  3. Add the manual acceptance from agency PRD section 9 to FOR_MAI section 3.
- **Tests:** as above.
- **Done when:** every parity row has a passing test or a recorded manual check, T17 passes, and the full suite passes.

**G4-04a Session allowlist, namespace and overlay on the chat and delegation paths**
- **PRD:** agency 4.1 parity row "Per-session tool allowlist, memory namespace, identity overlay" (gap found by G4-04)
- **Tier:** frontier
- **Depends on:** G4-04. Must land before G4-05, because `agent_loop.py` is today the only place the allowlist is enforced.
- **Files:** `src/aura/orchestrator/coordinator.py` (`_resolve_session`, the `select_tools` call, the `run_tool_loop` calls), `src/aura/orchestrator/tool_loop.py` (pass-through only), `src/aura/executor/tool_executor.py` (`execute_tool_call`, `execute_and_feedback`), `src/aura/executor/tool_registry.py` (`select_tools` exclude), `src/aura/tools/delegate.py`, `src/aura/executor/delegation.py` (`_build_brief`, `_write_delegation_memory`), new `tests/unit/test_session_scope_tools.py`
- **Change:**
  1. Chat path: the turn's `SessionContext` (from `_resolve_session`) travels with the turn the same way `venue` does: through `run_tool_loop`, `_forced_seed` and `execute_and_feedback` to `execute_tool_call`.
     - Tools the session does not allow (`SessionContext.is_tool_allowed`) are excluded in `select_tools`.
     - `execute_tool_call` refuses them with the session's message.
     - The role check stays first, then the tier gate (P2-03), then the session check.
     - The main session (no allowlist) changes nothing.
  2. Delegation path:
     - `delegate_work` refuses when the session does not allow it.
     - The brief includes the session's identity overlay, when there is one, as a short labelled section.
     - The closing memory write (`_write_delegation_memory`) uses the session's memory namespace instead of the global one.
     - The session context reaches the tool through the reserved `_session` argument, alongside `_venue` and `_requester_role` (see W1-02); never through the model-visible schema.
  3. Tests for `_resolve_session` itself: the namespace and overlay are set for a sub-session and None for main.
- **Tests:**
  - a sub-session with an allowlist offers only the allowed tools and refuses a forced call to another;
  - main is unchanged (ablation);
  - order of refusal: a guest is refused by role before the session check, and a Lean tier is refused by tier before the session check;
  - `delegate_work` is refused outside the allowlist;
  - the brief contains the overlay;
  - the memory write uses the session namespace;
  - `_resolve_session` cases;
  - revert each new check temporarily and confirm a test fails.
- **Done when:** the new tests pass, the G4-04 parity row moves from "gap" to covered in `docs/metrics/g4_parity.md`, and the full suite passes.

---

**G4-05 Remove the agent loop, the workspace routes, the IDE chat store and the IDE page (T15)**
- **PRD:** agency 4.1 "Removed" table, rule 6 ("leaving no parallel old and new paths"), test T15
- **Tier:** bulk
- **Depends on:** G4-04 (parity proven first)
- **Files:** delete `src/aura/executor/agent_loop.py`, `src/aura/api/routes/agent.py`, `src/aura/api/routes/workspace.py`, `frontend/src/pages/ide.tsx`, `frontend/src/components/ide/`, `frontend/src/components/agent/AgentLoopPanel.tsx`; edit `src/aura/main.py`, `src/aura/api/routes/tasks.py` (`_agent_loop_runner`), `src/aura/executor/task_queue.py` (`store_ide_chat_message`, `get_ide_chat_history`, `save_file_version`, `add_file_annotation` and their fields), `src/aura/models/session.py` and `src/aura/orchestrator/session_runtime.py` (references only), `src/aura/config.py` (`agent_loop_*` settings), `frontend/src/pages/mission-control.tsx` (the agent loop panel), any nav or service that calls `/agent/*` or `/workspace/*`
- **Change:**
  1. Delete the files and every caller. Grep for `agent_loop`, `AgentLoop`, `/agent/`, `/workspace/`, `ide-chat`, `file_versions` and `AuraIDE` in `src/` and `frontend/src` until nothing remains. Don't touch `/workspaces` (G3's registered workspaces) or `connections/opencode_*`.
  2. Task model fields used only by the removed code: keep them in the schema as `option<...>` (existing rows) but stop writing them. List them in the log entry.
  3. Mission Control: remove the agent loop panel and link to `/workbench` in its place. No other redesign (P2-14 does that).
  4. Tests that only covered the removed modules are deleted, and listed in the log entry. Tests that covered shared behaviour through the agent loop are ported to the delegation path, or the shared behaviour is shown to be covered by G4-04.
- **Tests:** T15, `tests/unit/test_g4_removed.py`: no module in `src/aura` imports `agent_loop` or `api.routes.workspace` or `api.routes.agent` (walk the AST, don't grep text); the FastAPI app has no route starting with `/agent/` or `/workspace/`; `frontend/src/pages/ide.tsx` does not exist. Run `npm test` and `npm run build`.
- **Done when:** T15 passes, the frontend builds, and the full suite passes.

---


### Wave 5 (Phase 2 order): cards for G5 and G6 (skills v2, attribution, distillation)

What exists today. The `skill` table (`scripts/init_schema.surql`, SCHEMAFULL) is a graph node with `name`, `domain`, `mastery_level`, `skill_type` (`abstract`, `mcp_tool`, `local_function`, `python_script`), `execution_config` and `description_embedding`; tool records are built from its `mcp_tool` and `local_function` rows by `executor/tool_registry.py` (`records_from_skill_rows`), and `tool_executor._get_skill_by_name` looks tools up in it. `engines/learning/skills.py` (`SkillTreeManager`) creates tree nodes and derives mastery from attached insights, not from outcomes (PRD L3). `engines/learning/engine.py` has the teaching fast lane (`_check_pattern_extraction`, `_process_direct_instruction`, `_compile_new_skill`), trigger phrase generation (`_generate_triggers_background`, W2-38) and `update_insight_confidence` (the smoothed rate, kept). There is no skill document, no version, no state, no per-skill attempts or successes, and no skill selection. Outcomes are hard-coded: `coordinator._log_interaction_experience` writes `{"success": True}` (L1). `ToolRegistry.record_call` keeps in-memory `ToolStats` (calls, successes, latencies) that are lost on restart. Recall feedback (`engines/recall/feedback.py::record_feedback`, W4-06, flag `recall_feedback_enabled`) runs in `_post_response_chain` and already knows which facts a turn used from `packet.trace`. Delegation accepts a free-text `skill` string in `DelegationConfig` (`executor/delegation.py`) and finalises tasks in `_finalize_task`; owner approvals go through `executor/decisions.py::DecisionService` (`create`, `get`, `reopen`, `answer`) with `kind="needs_decision"` items that have no OpenCode request to answer (G4-02, code nodes). Dreaming v2 runs from `DreamingEngine.enter_rem_sleep`, each phase gated by `dreaming_v2_enabled` and wrapped in its own try/except. P2-20 (skills at JIT presence levels), P2-24 and P2-26 (Striatum labels and warm-up) and P2-34/P2-35 (library cards, reviewer skills) build on the record these cards leave: a skill with `name`, a one-line `when_to_use`, `tags`, a `body`, and per-version usage and outcome statistics, read only through `engines/learning/skill_store.py` and `skill_index.py`.

Choices made where the PRD is open (the build agent must not reopen them):
- Skill documents go in new tables (`skill_doc`, `skill_version`, `skill_use`). The old `skill` table is not changed except for one optional link field, so tool lookup keeps working. PRD 6.1 "tool-as-skill nodes become plain tool records" is not done here.
- "Becomes active only after owner approval." A version is live only when it has `approved_at`. A `candidate` with no approval is inert (stored, shown on the agenda, never offered). An approved candidate is on trial: selectable, and it becomes `trusted` after `skill_promote_successes` (5) successes or on an explicit owner "trusted" approval (PRD 6.4). Without this reading a candidate could never gather the five successes.
- PRD 6.2 "Taught: a `trusted` skill, version 1" is the one exception, and only because the owner's own instruction is the approval. Taught by a guest, or from a guest conversation, is a `candidate` that needs a decision like any other.
- Automatic rollback (PRD 6.4) restores a version the owner already approved, so it needs no new approval, but it is flagged on the agenda.
- T11 is listed under G5 and distillation under G6. G5 delivers the proposal path (`propose_skill`, candidate linked to a task, body kept out of the default context); G6-01 adds the background drafting that calls it.

---

**G5-01 Skill model v2: schema, models, store and flags**
- **PRD:** agency 6.1, L3
- **Tier:** bulk
- **Depends on:** none
- **Files:** `scripts/schema_v2.surql` (or a new `scripts/schema_skills.surql` applied the same way; read how `schema_v2.surql` is loaded first), `src/aura/models/learning.py`, new `src/aura/engines/learning/skill_store.py`, `src/aura/config.py`, new `tests/unit/test_skill_store.py`
- **Exists today:** `skill` is SCHEMAFULL with tree and tool fields and a 768-dim HNSW `description_embedding`; `models/learning.py` has `Skill` (name, domain, mastery_level). No document, version or statistics.
- **Change:**
  1. Tables, all `DEFINE TABLE IF NOT EXISTS ... SCHEMAFULL`:
     - `skill_doc`: `name` (string, unique index), `when_to_use` (string, one or two sentences), `tags` (array<string> DEFAULT []), `state` (`candidate`, `trusted`, `retired`), `active_version` (option<int>), `previous_version` (option<int>), `origin_speaker` (string, `owner` or `guest`), `workspace` (option<string>), `node` (option<record<skill>>), `when_embedding` (option<array<float, 768>>), `created_at`, `updated_at`, `last_used_at` (option<datetime>), `retired_at` (option<datetime>), `flagged` (option<string>).
     - `skill_version`: `skill` (record<skill_doc>), `version` (int), `body` (string), `tools` (array<string>), `examples` (array<string>, task and episode ids), `pitfalls` (array<string>), `source` (`taught`, `distilled`, `corrected`, `imported`), `source_task` (option<string>), `change_note` (option<string>), `approved_at` (option<datetime>), `approved_by` (option<string>), `rejected` (bool DEFAULT false), `attempts` (int DEFAULT 0), `successes` (int DEFAULT 0), `practice_attempts` (int DEFAULT 0), `practice_successes` (int DEFAULT 0), `created_at`. Unique index on (`skill`, `version`). Old versions are never deleted.
     - `skill_use`: `skill` (record<skill_doc>), `version` (int), `turn_id` (option<string>), `task_id` (option<string>), `requester_role` (string), `tools` (array<string>), `fact_ids` (array<string>), `outcome` (option<string>: `positive`, `negative`, `unknown`), `counted` (bool DEFAULT false), `practice` (bool DEFAULT false), `created_at`. Index on `turn_id` and on `task_id`.
  2. Pydantic models `SkillDoc`, `SkillVersion`, `SkillUse` in `models/learning.py`.
  3. `skill_store.py` with an async class `SkillStore(db)`: `create_doc`, `add_version` (next integer, never reuses a number, never edits an old row), `get_doc(name)`, `get_version(skill, version)`, `list_docs(state=None, include_unapproved=False)`, `set_state`, `set_active(skill, version)`, `touch_used`. Every query uses `$params`; record ids go through `to_record_id` from `aura.db.query_utils`.
  4. Config: `skills_v2_enabled` (False, `AURA_SKILLS_V2_ENABLED`), the parent flag every later skill card checks. No other behaviour changes in this card.
  5. Time comes from `get_clock()`.
- **Tests:** create a doc and three versions (numbers 1 to 3, old bodies intact); a duplicate `name` is refused; `list_docs` hides unapproved candidates unless asked; the schema statements parse and every new field on the old `skill` table (if any) is `option<...>`; the existing tool lookup tests still pass. Use the runner's `EmbeddedSurrealDB` with the real schema for the store tests (that is the only way to catch fields a SCHEMAFULL table drops); never copy the schema into a test.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** change `SkillTreeManager`, `records_from_skill_rows` or `_get_skill_by_name`. Do not put skill documents in the `skill` table.
- **Known pitfalls:** SCHEMAFULL silently drops undeclared fields, so every field a test writes must be declared, and the embedded tests must read each field back.
- **Guest and privacy:** `origin_speaker` and `skill_use.requester_role` are stored so later cards can keep guest-learned skills inert.

---

**G5-02 Proposals, versions, near-duplicate merge and owner approval (T12)**
- **PRD:** agency 6.2 ("Before creating, compare against existing skills by `when_to_use`"), 6.4, test T12
- **Tier:** frontier
- **Depends on:** G5-01
- **Files:** `src/aura/engines/learning/skill_store.py`, new `src/aura/engines/learning/skill_proposals.py`, `src/aura/executor/decisions.py` (a post-answer hook only), new `src/aura/api/routes/skills.py`, `src/aura/main.py` (router), `src/aura/config.py`, new `tests/unit/test_skill_proposals.py`
- **Exists today:** `DecisionService.create(kind, session_id, request_id, action, resources, risk, workspace, message, task_id)` and `answer(decision_id, allow, decided_by)`; for `kind="needs_decision"` `answer` only records the status. Code nodes (`executor/code_node.py`) wait on such a decision and read it back with `get`. `engines/learning/engine.py::_compile_new_skill` creates tool nodes directly; nothing compares skills by meaning.
- **Change:**
  1. `propose_skill(store, embeddings, draft, source, source_task, origin_speaker)` in `skill_proposals.py`. `draft` has `name`, `when_to_use`, `tags`, `body`, `tools`, `pitfalls`. Steps: embed `when_to_use` with the embeddings client; find the nearest non-retired doc by cosine of `when_embedding`; if the similarity is at least `skill_dup_similarity` (default 0.85, `AURA_SKILL_DUP_SIMILARITY`) add a new `skill_version` to that doc (T12: no second doc), else create a `candidate` doc with version 1. Either way the new version has no `approved_at`. The currently active version stays active until approval. Returns `(doc, version, merged)`.
  2. Approval through the decisions service: after the proposal, `DecisionService.create(kind="needs_decision", action="skill_activate", risk="write", message=<name, one-line change note, first 300 chars of the body change>, session_id="skill", request_id=<skill name and version>)`, one item per (skill, version), never a second while one is pending. The decision resource is `["skill:<name>:v<version>"]`.
  3. A post-answer hook in `DecisionService.answer`: when the decision `action` is `skill_activate` and the answer is allow, call `SkillStore.approve(skill, version, by)`, which sets `approved_at`, sets `active_version` (moving the old one to `previous_version`), and keeps state `candidate` (on trial), or `trusted` if the owner chose "trusted" in the API body. A deny sets `rejected = true` on the version and it is never offered again. The hook stays inside the `needs_decision` branch and never touches the OpenCode client path. Gate it on `skills_v2_enabled`.
  4. Visibility: a proposal with `origin_speaker == "guest"` goes through the same decision, and the message says "learned from a guest conversation". A guest cannot call any route in this card, and `propose_skill` never approves anything itself.
  5. Routes in `api/routes/skills.py` (same unauthenticated posture as the other routes): `GET /skills` (docs with active version summary, state, stats), `GET /skills/{name}` (all versions), `POST /skills/{name}/versions/{n}/approve` and `/reject` (both go through `DecisionService.answer` on the pending decision, so there is one approval path).
  6. Config: `skill_dup_similarity`.
- **Tests (T12):** a proposal near an existing skill adds version 2 and creates no second doc, with a fake embedding client returning controlled vectors; a dissimilar one creates a new candidate; neither is live before the decision; allowing the decision sets `approved_at` and `active_version`; denying leaves the old active version; a second proposal while one is pending adds no second decision; with `skills_v2_enabled` off the hook does nothing (ablation) and `answer` behaves as before for `needs_decision` merges (existing code node tests unchanged).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** make any model call here. Do not activate a version from `propose_skill`. Do not copy the approval logic into the routes.
- **Known pitfalls:** `DecisionService.answer` raises when no OpenCode client is set, except for `needs_decision`; keep the hook inside that branch. Use a `FakeClock` for `approved_at`. Monkeypatch `settings.skills_v2_enabled` in each test. No real embeddings model.

---

**G5-03 Real per-turn outcome signal (T14)**
- **PRD:** agency 7 step 1 and L1; behavior PRD section 11; test T14
- **Tier:** frontier
- **Depends on:** G5-01 (flag); otherwise independent
- **Files:** new `src/aura/engines/learning/outcomes.py`, `src/aura/orchestrator/coordinator.py` (`_post_response_chain`, `_log_interaction_experience`), `src/aura/engines/learning/engine.py` (add `set_experience_outcome` only), `src/aura/config.py`, new `tests/unit/test_turn_outcomes.py`
- **Exists today:** `_log_interaction_experience` writes `outcome: {"success": True}` for every turn. `_post_response_chain` runs after the reply, already embeds text for recall feedback (`get_embeddings_client`) and knows `speaker` and `venue`. `Experience.outcome` is a free dict. Mai's corrections are not detected anywhere; the teaching fast lane only detects instructions.
- **Change:**
  1. `outcomes.py`: `classify_outcome(previous_turn, current_turn, embeddings) -> "positive" | "negative" | "unknown"` with no model call. Negative: the owner's current message rephrases their previous message within `outcome_rephrase_turns` (2, `AURA_OUTCOME_REPHRASE_TURNS`) turns, meaning cosine of the two message embeddings at least `outcome_rephrase_similarity` (0.8) or content-word overlap at least `outcome_rephrase_overlap` (0.6), or the message starts with a correction marker from a small list in the module ("no,", "that's not", "I meant", "wrong"). Explicit feedback from a thumbs control, if the app sends it, overrides. Positive: only explicit positive feedback, or a delegated task's tests passing (G5-04 passes that in). Everything else is `unknown`, not positive.
  2. A small in-memory ring of the last `outcome_rephrase_turns` owner turns per conversation (`conversation_id`, experience id, text, embedding). Bounded; no persistence.
  3. When a later owner turn is classified, patch the earlier experience: `outcome = {"signal": ..., "success": <True|False|None>, "source": ...}` through `LearningEngine.set_experience_outcome(experience_id, outcome)` using a parameterised merge. Behind the flag the hard-coded `{"success": True}` is replaced by `{"signal": "unknown", "success": None}` at log time.
  4. Only owner turns classify and are classified. Guest turns (`speaker != "owner"`) are written as `unknown` and never patched, and a guest rephrase never changes an owner turn's outcome.
  5. Runs in `_post_response_chain` after the reply, wrapped so a failure never affects the turn (follow `record_feedback`).
  6. Config: `outcome_signals_enabled` (False, `AURA_OUTCOME_SIGNALS_ENABLED`), plus the numbers above. With the flag off the old hard-coded success is written unchanged (ablation).
- **Tests (T14):** the owner asks, then rephrases within two turns: the first turn's outcome is `negative`; a different follow-up leaves it `unknown`; a rephrase three turns later does not patch it; a correction marker marks `negative`; a guest rephrase changes nothing; flag off writes `success: True` as before; the classifier never calls an LLM (the fake LLM client received zero calls). Fake embeddings returning fixed vectors.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** treat silence as positive. Do not add a model call. Do not change `update_insight_confidence`.
- **Known pitfalls:** existing tests assert `{"success": True}`; they run with the flag off and must stay unchanged. Monkeypatch settings per test.

---

**G5-04 Attribution and outcome updates (statistics per skill version)**
- **PRD:** agency 7 steps 2 and 3, 6.4 ("Mastery is the measured success rate with its uncertainty"), T4's "skill statistics updated"
- **Tier:** frontier
- **Depends on:** G5-01, G5-02, G5-03
- **Files:** new `src/aura/engines/learning/skill_stats.py`, `src/aura/orchestrator/coordinator.py` (`_post_response_chain`), `src/aura/orchestrator/tool_loop.py` (read how tool calls are collected before editing), `src/aura/executor/delegation.py` (`_finalize_task`, brief assembly), `src/aura/tools/delegate.py`, `src/aura/engines/recall/feedback.py` (return the used ids only), `src/aura/config.py`, new `tests/unit/test_skill_attribution.py`
- **Exists today:** `ToolRegistry.record_call` counts in memory only. `record_feedback` computes used facts but returns nothing. `DelegationConfig.skill` is a text blob put in the brief; nothing records which skill produced which task. `Skill.mastery_level` is derived from insights.
- **Change:**
  1. Attribution: `record_skill_use(store, skill, version, turn_id, task_id, requester_role, tools, fact_ids, practice=False)` writes one `skill_use` row. The turn path calls it from `_post_response_chain` for every skill G5-05 chose; tools come from the tool loop's calls for that turn (names only), fact ids from `record_feedback` (make it return the used ids; behaviour unchanged). Delegation: `delegate_work` accepts a skill name, resolves it to a live version, puts the body in the brief, and records the use with the task id.
  2. `apply_outcome(store, use, outcome)` in `skill_stats.py`: once a use has an outcome (`positive` or `negative`, never `unknown`) and `counted` is false and `requester_role == "owner"` and it is not practice, add one attempt to the version (`attempts += 1`, `successes += 1` on positive) in one parameterised update and set `counted = true` so it cannot double count. `unknown` is left uncounted, not a failure.
  3. Triggers: (a) G5-03 patches a turn outcome, which calls `apply_outcome` for that turn's uses; (b) `_finalize_task` outcome `succeeded` with the review (tests) passing counts positive, `failed` counts negative, `needs_owner` and aborted by owner count nothing.
  4. Inferred-fact confidence: the facts relied on get the existing smoothed update, reusing the formula in `update_insight_confidence` by import, not copy, for `inferred` facts only, on positive and negative outcomes.
  5. Pure helpers: `beta_params(attempts, successes) -> (1 + successes, 1 + attempts - successes)` and `mastery(attempts, successes) -> (mean, lower_bound)` where the lower bound is the `skill_mastery_quantile` (0.2, `AURA_SKILL_MASTERY_QUANTILE`) of the Beta, so two uses and two hundred uses at the same rate are not equal. Persisting `ToolStats` is out of scope; the tool names on `skill_use` are the attribution.
  6. Config: `skill_attribution_enabled` (False, `AURA_SKILL_ATTRIBUTION_ENABLED`) and `skill_mastery_quantile`. Both also need `skills_v2_enabled`.
- **Tests:** a turn using skill A v2 with a negative owner outcome gives v2 `attempts` 1, `successes` 0; positive adds a success; `unknown` adds nothing; a second patch does not double count; a guest turn's use is recorded but not counted; practice rows go to `practice_*` only; a succeeded delegation with a passing review counts positive and a failed one negative (fake OpenCode client); the lower bound is lower for 2 of 2 than for 200 of 200; flag off writes no `skill_use` (ablation).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** count `unknown` as failure. Do not make a model call on the reply path. Do not read the system clock; use `get_clock()`.
- **Known pitfalls:** increment in the query (`attempts += 1`), not read-modify-write. Existing delegation tests use a fake task queue; add the attribution call behind the flag so they are unchanged.
- **Guest and privacy:** guest turns and guest-requested tasks never move owner skill statistics, so a guest cannot push a skill to `trusted` or into a rollback.

---

**G5-05 Skill index, selection and default context (T11)**
- **PRD:** agency 6.1 ("Only `name` and `when_to_use` are ever placed in context by default"), 6.3, test T11
- **Tier:** frontier
- **Depends on:** G5-01, G5-02, G5-04
- **Files:** new `src/aura/engines/learning/skill_index.py`, `src/aura/llm/layers.py` (the system prompt assembly; read first), `src/aura/orchestrator/coordinator.py` (one call before the model call, no model use), `src/aura/config.py`, new `tests/unit/test_skill_selection.py`
- **Exists today:** nothing selects skills. `get_learning_context` returns insights. `select_tools` in `tool_registry.py` selects tools by relevance (mirror its floor style, do not reuse or change it). P2-20 later gives skills `full`, `stub` and `absent` presence levels from a shared budget with tools.
- **Change:**
  1. `skill_index.py` exposes the hooks P2-20, P2-24 and P2-26 will use: `SkillStub(name, one_line, tags, version, mastery)`, `render_index(stubs) -> str` (one line each, `name: when_to_use`), `load_body(name, version) -> str`, `candidates(request_embedding) -> list[...]`. Live means: state `candidate` or `trusted`, the version has `approved_at` and is not `rejected`, and the doc is not retired. Unapproved candidates never appear.
  2. Selection (PRD 6.3), pure and seedable: retrieve live skills by cosine between the request embedding and `when_embedding`; keep those at or above `skill_relevance_floor` (0.55, `AURA_SKILL_RELEVANCE_FLOOR`), at most `skill_candidates_max` (8); sample one value per arm from `Beta(1 + successes, 1 + failures)` with an injected `random.Random` and choose the highest draw. Arms are the active version and, while the active version has fewer than `skill_trial_attempts` (10) attempts, the previous version, so a new version is measured against the old one and still gets tried. Return nothing when no skill passes the floor.
  3. Context: the index for the top `skill_index_max` (50) live skills by relevance goes into the prompt as stubs only; the chosen skill's body is added for the chosen skill only.
  4. Record the choice with `record_skill_use` (G5-04) on the turn. Reuse the request embedding the turn already computes for recall; if none exists, one embeddings call (not an LLM call) before the model call, with a timeout that falls back to no skill.
  5. Owner turns only: for a guest requester no skill body and no index line is added. A skill with `origin_speaker == "guest"` is selectable only because the owner approved it.
  6. Config: `skill_selection_enabled` (False, `AURA_SKILL_SELECTION_ENABLED`), `skill_relevance_floor`, `skill_candidates_max`, `skill_trial_attempts`, `skill_index_max`.
- **Tests (T11 and selection):** a candidate created by `propose_skill` with `source_task` has that task id in `examples`, and its body is absent from the assembled prompt until it is approved and chosen; with 50 skills the default prompt holds 50 one-liners and no body; a seeded sampler picks a high-success skill most of the time over 1000 draws and picks a fresh version some of the time; below the floor returns none; unapproved and rejected versions are never selected; a guest turn gets no skill text; flag off leaves the prompt byte-identical (ablation); no LLM call occurs.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** put a body in context except for the chosen skill. Do not call the model to rank skills. Do not change `select_tools`.
- **Known pitfalls:** pass the random generator in; never call the global `random`. Prompt assembly tests may compare exact strings; run them with the flag off to confirm they are unchanged.

---

**G6-01 Skill distillation in dreaming**
- **PRD:** agency 6.2 "Distilled", 7 step 4, test T11
- **Tier:** frontier
- **Depends on:** G5-02, G5-04, G5-05
- **Files:** new `src/aura/engines/learning/skill_distill.py`, `src/aura/engines/dreaming/engine.py` (a new phase in `enter_rem_sleep`), `src/aura/executor/task_queue.py` (read how task records and steps are stored), `src/aura/config.py`, new `tests/unit/test_skill_distill.py`
- **Exists today:** delegated tasks are stored with steps and a final status (`delegation._finalize_task`), and `_write_delegation_memory` writes an episode and fact. `DreamingEngine.enter_rem_sleep` runs phases each gated by flags and its own try/except; the engine has an LLM through `set_dependencies`. Nothing reads finished tasks to learn a procedure.
- **Change:**
  1. `find_distillable_tasks(db, since)`: tasks with status complete, at least `skill_distill_min_steps` (3, `AURA_SKILL_DISTILL_MIN_STEPS`) steps, review passed, requested by the owner (not a guest), not already distilled (a `skill_distill_log` table with `task_id`, or an `option<datetime>` `distilled_at` on the task). "Nothing similar exists" is decided by `propose_skill`, which merges near matches into a new version.
  2. `draft_skill(llm, task)`: one call to the model the dreaming engine already uses (read how it reaches the LLM), from the task brief and the step titles (not raw tool output; pass text through the existing log sanitiser), returning JSON `{name, when_to_use, tags, body, tools, pitfalls}`. Invalid JSON, an empty body or a body over `skill_body_max_chars` (6000, `AURA_SKILL_BODY_MAX_CHARS`) is dropped and logged.
  3. A new dreaming phase `_distill_skills` after the themes phase, gated on `skills_v2_enabled` and `skill_distill_enabled` (False, `AURA_SKILL_DISTILL_ENABLED`), at most `skill_distill_max_per_cycle` (2) tasks per cycle, in its own try/except. Each draft goes to `propose_skill(source="distilled", source_task=<task id>)`, so it becomes an unapproved candidate (or a new version of a near match) with the approval decision from G5-02. Nothing is live.
  4. No model call on the chat hot path; this phase is the only place the draft call happens.
- **Tests (T11 end to end):** a planted successful delegated task produces exactly one candidate with `source_task` set and `examples` containing the task id, the body absent from the default prompt, and one pending decision; a second cycle does not distil the same task again; a guest-requested task is skipped; a near-duplicate draft becomes version 2 of the existing skill (T12 through this path); invalid model output creates nothing; flag off makes no model call (ablation); the per-cycle cap holds. Fake LLM returning canned JSON.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** activate anything. Do not read raw file contents or tool output into the prompt. Do not call the model outside the dreaming phase.
- **Known pitfalls:** a failing phase must not stop later dreaming phases (copy the try/except pattern). Use `FakeClock` for the `since` window. The fake LLM must fail the test if called with the flag off.
- **Guest and privacy:** only owner-requested tasks are distilled; a guest conversation can never become a skill through this path.

---

**G6-02 Taught and imported skills**
- **PRD:** agency 6.2 "Taught" and "Imported"
- **Tier:** bulk
- **Depends on:** G5-02, G5-05
- **Files:** `src/aura/engines/learning/engine.py` (`_process_direct_instruction` and the fast lane; leave `_check_pattern_extraction` routing alone), `src/aura/engines/learning/skill_proposals.py`, `src/aura/api/routes/skills.py`, `src/aura/config.py`, new `tests/unit/test_skill_taught_imported.py`
- **Exists today:** the fast lane queues experiences whose `task_type == "instruction"` or `metadata.intent == "teaching"` for `_process_direct_instruction`, which today creates insights and tool skill nodes. No import path exists.
- **Change:**
  1. Taught: when the fast lane fires for an owner turn, `skills_v2_enabled` and `skill_taught_enabled` (False, `AURA_SKILL_TAUGHT_ENABLED`) are on, and the instruction describes a procedure (a list, or at least two sentences; a plain preference stays an insight), build the draft from the owner's text with no new model call (reuse what instruction processing already produced; otherwise the owner's words are the body and the first sentence is `when_to_use`). `propose_skill(source="taught", origin_speaker="owner")` creates version 1 with `approved_at` set at once, state `trusted`, `approved_by="owner-taught"` (PRD: taught is trusted). A near match becomes a new version, also pre-approved because the owner wrote it.
  2. A teaching turn from a guest is proposed with `origin_speaker="guest"` as an unapproved candidate and a decision, as in G5-02, never as trusted.
  3. Imported: `POST /skills/import` `{name?, text}` accepts a skill file the owner provides (markdown with an optional front matter of `name`, `when_to_use`, `tags`). Parsed without a model, limited to `skill_body_max_chars`, and sent through `propose_skill(source="imported")` as an unapproved candidate with a decision. A workspace scan is not part of this card.
- **Tests:** an owner teaching creates a trusted live v1; the same teaching again makes v2, not a second skill; a guest teaching makes an inert candidate and a decision; a plain preference makes no skill; an import creates an inert candidate and one decision; oversize and malformed imports are refused; flag off leaves the fast lane exactly as today (ablation).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** let `trusted` be set from any non-owner path. Do not alter trigger phrase generation (W2-38).
- **Known pitfalls:** how `speaker` reaches the learning engine is not obvious; read the `log_experience` call and pass the speaker through `Experience.metadata` rather than inferring it from `user_id`.

---

**G6-03 Correction: new versions from failures and owner corrections**
- **PRD:** agency 6.2 "Corrected", 7 step 4 ("Reflection with consequences") and step 5 ("Lessons are scoped")
- **Tier:** frontier
- **Depends on:** G5-03, G5-04, G6-01
- **Files:** new `src/aura/engines/learning/skill_correct.py`, `src/aura/engines/dreaming/engine.py` (a phase after distillation), `src/aura/config.py`, new `tests/unit/test_skill_correction.py`
- **Exists today:** G5-04 counts negative outcomes per version and records each `skill_use` with its turn or task. The dreaming engine hosts background reflection-style work; nothing yet turns failures into skill proposals. Owner corrections arrive as the negative signal from G5-03.
- **Change:**
  1. `find_correction_candidates(db, since)`: counted owner `skill_use` rows with outcome `negative`, grouped by (skill, version); a candidate needs at least `skill_correct_min_negatives` (2, `AURA_SKILL_CORRECT_MIN_NEGATIVES`) negatives since the last correction, or one explicit owner correction message.
  2. `draft_lesson(llm, skill_version, evidence)`: one background model call from the skill's body and the evidence (the failed task's step titles, or the owner's correcting message), returning one lesson sentence for the pitfalls list. The body is not edited; only pitfalls grow, capped at `skill_pitfalls_max` (10, `AURA_SKILL_PITFALLS_MAX`, oldest dropped).
  3. The result goes to `propose_skill(source="corrected")` as a new version of the same skill with extended `pitfalls` and a `change_note` quoting the evidence ids, unapproved, with the G5-02 decision. The active version keeps serving until the owner approves.
  4. Scoping (PRD 7.5): a lesson from a task in workspace W is stored as `workspace:<W>: ...` in the pitfalls; it becomes an unscoped line only when the same lesson (embedding similarity at `skill_dup_similarity`) recurs from a second workspace.
  5. Phase gated on `skills_v2_enabled` and `skill_correction_enabled` (False, `AURA_SKILL_CORRECTION_ENABLED`), cap `skill_correct_max_per_cycle` (2). Guest evidence is excluded by construction (G5-04 never counts it).
- **Tests:** two counted negatives produce one corrected version with a longer pitfalls list, an unchanged body and a pending decision; a single negative without an explicit correction produces nothing; a lesson from workspace A stays scoped and becomes unscoped only after workspace B repeats it; the cap holds; pitfalls never exceed the cap; flag off makes no model call (ablation). Fake LLM only.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** apply a corrected version without approval. Do not rewrite the body. Do not run on the reply path.
- **Known pitfalls:** the same negatives must not feed a second correction; keep a `corrected_at` watermark on the version or a log row.

---

**G6-04 Trial comparison, automatic rollback, promotion and retirement (T13)**
- **PRD:** agency 6.4, test T13
- **Tier:** frontier
- **Depends on:** G5-04, G5-05, G6-03
- **Files:** new `src/aura/engines/learning/skill_lifecycle.py`, `src/aura/engines/learning/skill_store.py`, `src/aura/engines/dreaming/engine.py`, `src/aura/api/routes/skills.py`, `src/aura/config.py`, new `tests/unit/test_skill_lifecycle.py`
- **Exists today:** G5-04 keeps `attempts` and `successes` per version and `previous_version` on the doc; G5-02 `approve` moves the old active version to `previous_version`; G5-05 samples between the two while the new one is on trial. Owner-facing items go through `DecisionService`; dreaming writes a report at the end of each cycle.
- **Change:**
  1. `evaluate_skill(doc)`, pure over the two versions' counts: roll back when the active version has at least `skill_rollback_min_attempts` (8, `AURA_SKILL_ROLLBACK_MIN_ATTEMPTS`) attempts, the previous version has at least as many, and the active mean success rate is below the previous mean by more than `skill_rollback_margin` (0.15, `AURA_SKILL_ROLLBACK_MARGIN`). "Clearly below" is that margin on the Beta means, not a hypothesis test. Practice results (G8) are excluded.
  2. `rollback(doc)`: set `active_version` back to `previous_version`, set `previous_version` to none, set `flagged = "rolled back from v<n>: <rates>"`, mark the bad version `rejected`, and create an informational `needs_decision` item (`action="skill_rolled_back"`; answering only acknowledges). The bad version stays stored; a later correction creates a new number. No new approval is needed because the restored version was approved earlier (say so in the docstring).
  3. Promotion: a `candidate` with `approved_at` becomes `trusted` once its active version has `skill_promote_successes` (5, `AURA_SKILL_PROMOTE_SUCCESSES`) successes.
  4. Retirement: a skill with no `last_used_at` for `skill_retire_days` (90, `AURA_SKILL_RETIRE_DAYS`) days that is also superseded (a newer doc covers the same `when_to_use` by the G5-02 similarity test) becomes `retired`: never deleted, never offered, still listed by `GET /skills?state=retired`.
  5. A dreaming phase `_skill_lifecycle` runs evaluation, promotion and retirement for all docs in its own try/except; the same check runs for the affected doc after each `apply_outcome` (cheap, no model). Gated on `skills_v2_enabled` and `skill_rollback_enabled` (False, `AURA_SKILL_ROLLBACK_ENABLED`).
  6. `GET /skills` shows `flagged`, the Beta mean and lower bound per version and the rollback reason.
- **Tests (T13):** a new version with 8 attempts at 25 percent against a previous at 80 percent rolls back, `active_version` returns to the previous, the doc is flagged and one decision item exists; 70 percent against 75 percent does not; fewer than the minimum attempts does not; the rolled back version is never selected (G5-05 sampler); a candidate with five successes becomes trusted; a stale superseded skill is retired and not deleted; flag off changes nothing (ablation). Use a `FakeClock` moved past the retirement window.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** delete any version or doc. Do not roll back on practice results. Do not roll back to a version that was never approved.
- **Known pitfalls:** rollback and a concurrent approval can race; do the state change in one parameterised transaction and re-read the doc inside it. Monkeypatch the numbers through `settings`, not by editing constants.

---


### Wave 5 (Phase 2 order): cards for B1 to B5 (outcomes, agenda, workspace, goals v2, curiosity, interruptibility)

Written 2026-11-23 against commit 3c1ec50. Behaviour PRD sections 2 to 15, tests T1 to T12 and T14 (T13 is B0, already landed as `_turn_pipeline` in `orchestrator/coordinator.py`; B6 and B7 are not carded here). Current state: initiative is still timer-based (`GoalEngine.tick`, `_consider_new_goal`, `check_boredom` in `engines/goal/engine.py`); goal progress still rises from mood and stale goals are marked complete; pursuit is still requested by the `[GOAL_PURSUIT_REQUEST:id]` text tag (`llm/layers.py` around line 1345, regex in `frontend/src/pages/chat.tsx` around line 1294); the only server push channels are `/ws/emotion`, `/v1/stream/emotions` and `/v1/stream/traces` (`main.py`, `api/websocket.py`), and the chat polls `GET /chat/task-reports` (P2-11); `_log_interaction_experience` still writes `outcome: {"success": True}`. Already in place and reused: the clock provider (`aura.clock`: `get_clock`, `FakeClock`, `set_clock`), the decisions service (`executor/decisions.py`, kind `needs_decision` from G4-02 and G4-05 code nodes), `delegation.pause_all` / abort-all (G4-01), the task graph tables and scheduler (`executor/task_scheduler.py`, `scripts/setup_tasks.surql`), the message bus (`orchestrator/message_bus.py`, which already has a `PROPOSAL` type), `question` and `prediction` tables (`scripts/schema_v2.surql`) and `write_facts` (`engines/memory/v2/facts.py`).

**B-number mapping to the Phase 2 plan.** The Phase 2 plan's B numbers are loose. It says "B2/B4 change goals and the agenda" and P2-33 names "the B2 agenda and B5 interruptibility code". Mapping used here, by the behaviour PRD's milestones: the Phase 2 "B2 agenda" is behaviour B1 (agenda table, endpoints, controls) plus B2 (workspace, drives). The Phase 2 "B4 goals v2, evidence-based" (P2-31 and P2-32 read "the result of B4") is behaviour B3 (goals v2). The Phase 2 "B4" curiosity part is behaviour B4. "B5 interruptibility" is behaviour B5. **Cards Phase 2 needs:** B1-01, B1-02, B1-04, B1-05, B1-06 and B2-04 (the gate, the agenda and the push channel, for P2-11 and P2-33); B3-01 to B3-04 (P2-31 and P2-32 extend the goal schema and criteria checker); B3-05 (P2-33 pursuit gating); B5-01 and B5-02 (P2-33 item 5). Order: B1-01 to B1-08, B2-01 to B2-04, B3-01 to B3-06, B4-01 to B4-04, B5-01 to B5-04. Cards marked "Phase 2" are marked `P2-31..33` in their Tier line note.

Hooks left for Phase 2 (not designed here): P2-33 owns autonomy levels 0 to 3, the daily message and Sage budgets and `may_initiate(kind)`. B1-01 builds one gate function `may_initiate(kind)` with the PRD's three levels (`silent`, `important`, `open`) and the kill switch; P2-33 replaces the level logic and adds budgets inside the same function. Nothing else may bypass it. P2-31 owns goal stages, origin, milestones and `close_reason`. B3-01 adds only `criteria`, `abandon_reason` and the `abandoned` status, with the criterion kinds chosen so P2-32's evidence kinds extend them (`test_pass`, `file_exists`, `task_node_done`, `mai_confirms`). P2-11 owns report messages. B1-04 builds the channel and its `chat_message` event so the chat can switch from polling later; B1 does not touch `chat.tsx` polling.

Shared conventions for every card below. Every new mechanism has a flag in `config.py`, off by default (the owner controls and kill switch in B1 are not flagged, they are safety, and default to the safest state). Every number is a `Field(..., validation_alias="AURA_...")` in `config.py`. Time comes from `get_clock()`; tests use `FakeClock` and restore with `set_clock(Clock())`. No model call on the chat hot path and none in a timer loop (PRD rule 2). All queries use `$param`. New fields on tables with rows are `option<...>`. New tables go in a new `scripts/schema_behavior.surql` (created in B1-01 and added to the bootstrap list in `main.py`). Aura messages only the owner proactively; guests are never contacted (D6, D15). Each card's tests include an ablation test (flag off means the old behaviour exactly) unless it adds none.

---

**B1-01 Behaviour config, the gate, owner control state and the trace table**
- **PRD:** 8.3, 3 (principle 5), 14 rules 5 to 7; phase 2 hook for P2-33
- **Tier:** frontier (Phase 2 needs: `P2-31..33` via the gate)
- **Files:** `src/aura/config.py`, new `scripts/schema_behavior.surql`, `src/aura/main.py` (bootstrap list and router include), new `src/aura/autonomy/__init__.py`, new `src/aura/autonomy/controls.py`, new `src/aura/autonomy/trace.py`, new `tests/unit/test_autonomy_controls.py`
- **Change:**
  1. Config fields, all with `AURA_` aliases: `autonomy_default_level` (`silent|important|open`, default `important`, PRD open item 1 recommended value), `quiet_hours_start` and `quiet_hours_end` (local `HH:MM`, default `22:00` and `08:00`, PRD open item 3), `autonomy_enabled` (master flag for any unprompted delivery, default false), `outcomes_enabled`, `workspace_enabled`, `drives_enabled`, `goals_v2_enabled`, `curiosity_enabled`, `interruptibility_model_enabled`, `dismissal_learning_enabled` (all default false). Quiet hours use `app_timezone`.
  2. `scripts/schema_behavior.surql`: `autonomy_control` (singleton row `autonomy_control:main`: `level` string, `muted_kinds` array of strings, `killed` bool, `killed_at` option<datetime>, `updated_at` datetime) and `autonomy_trace` (`source`, `action`, `why`, `cost` object, `refs` array, `at` datetime, `allowed` bool). Both `IF NOT EXISTS`. Add the file to the list in `main.py` after `schema_v2.surql`.
  3. `autonomy/controls.py`: `get_controls()`, `set_level()`, `mute_kind()`, `unmute_kind()`, `set_killed()` backed by the singleton row, with an in-memory cache refreshed on write. `killed` is read synchronously from the cache so hot loops never await the database.
  4. `may_initiate(kind: str, *, now=None) -> Decision` (a small dataclass with `allowed`, `reason`). Order: killed, then `autonomy_enabled`, then the kind is not muted, then the level (`silent`: nothing; `important`: kinds `needs_decision` and `task_done` only; `open`: everything). `reminder` items the owner created by hand are an exception allowed at `important` (the owner asked for them). Every call that would start autonomous work writes an `autonomy_trace` row through `trace.record(...)`, allowed or refused. This is the single gate P2-33 extends; the docstring says so.
  5. `quiet_hours_active(now)` in `controls.py`, using the clock and `app_timezone`; handles a window that crosses midnight.
- **Tests:** each level allows exactly its kinds; muted kind refused; killed refuses everything including `reminder`; master flag off refuses and the trace row says why; quiet hours across midnight with a FakeClock; the singleton survives a re-read; trace rows written for allowed and refused calls.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** read wall time or `settings` inside `may_initiate` beyond the documented fields; add budgets or numeric autonomy levels (P2-33).

---

**B1-02 Agenda table, service and the refs rule**
- **PRD:** 8, rule 3 (item without `refs` rejected)
- **Tier:** bulk (Phase 2 needs: P2-32 flags orphans and conflicts "on the agenda")
- **Depends on:** B1-01
- **Files:** `scripts/schema_behavior.surql`, new `src/aura/autonomy/agenda.py`, `src/aura/config.py`, new `tests/unit/test_agenda.py`
- **Change:**
  1. `agenda_item` table: `kind` (ASSERT in `finding`, `task_done`, `needs_decision`, `question_for_you`, `reminder`, `observation`), `content`, `refs` array of strings, `priority` float, `venue` string (default `app`), `created_at`, `expires_at` option<datetime>, `state` (ASSERT in `pending`, `delivered`, `acknowledged`, `dismissed`, `expired`), `delivered_at` option<datetime>, `resolved_at` option<datetime>, `source` string, `due_at` option<datetime>. Index on `state`.
  2. `AgendaService.create(kind, content, refs, priority, venue="app", expires_at=None, due_at=None, source)` rejects an empty `refs` with `ValueError("agenda item needs refs")` (principle 1), clamps priority to 0..1, and rejects an unknown kind.
  3. `effective_priority(item, now)`: stored priority decayed by a per-kind rate (`agenda_decay_per_hour_<kind>` config fields, floats, defaults 0 for `needs_decision` and `reminder`, small for the rest). Pure function.
  4. `list(states=None)`, `get(id)`, `acknowledge(id)`, `dismiss(id)`, `expire_due(now)` (moves pending or delivered items past `expires_at` to `expired`, silently). `acknowledge` and `dismiss` only act on `delivered` or `pending` items and stamp `resolved_at`. Use `get_clock()` throughout.
  5. Venue is a string for now (`app`, or `discord:<channel>` later); only `app` is delivered in B1.
- **Tests:** create without refs fails; unknown kind fails; decay is pure and monotone; expiry moves items without delivering them; state transitions; double acknowledge is a no-op; parameterised queries only (a quote in `content` round-trips).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add a model call to draft content; callers pass the drafted `content`.

---

**B1-03 Explicit outcome feedback and task evidence (extends G5-03)**
- **PRD:** 11, finding B8
- **Tier:** bulk
- **Depends on:** B1-01, G5-03 (the per-turn classifier, `engines/learning/outcomes.py`, the ring of owner turns and `LearningEngine.set_experience_outcome` already exist; do not build a second classifier)
- **Files:** `src/aura/engines/learning/outcomes.py`, `src/aura/api/routes/chat.py` (new `POST /chat/outcome`), `src/aura/orchestrator/coordinator.py` (only if the message id to experience id mapping needs exposing), `src/aura/config.py`, new `tests/unit/test_outcome_feedback.py`
- **Change:**
  1. `POST /chat/outcome` `{experience_id or message_id, signal: "up"|"down"}`: owner only (same role check as the other owner routes). It records an explicit signal through G5-03's override path, so explicit beats implicit, and calls the same downstream hooks G5-03 calls (G5-04's `apply_outcome` when skill attribution is on).
  2. Positive task evidence: when a delegated task or a task-graph code node in the same conversation finishes with tests passing (the review verdict PASS) or an approved merge, the turn that requested it is marked `positive` with source `task`. Read the existing task and graph rows; add no new events.
  3. Extend G5-03's signal vocabulary only by adding `source` values (`explicit`, `task`); keep `positive|negative|unknown`.
  4. Gated on G5-03's `outcome_signals_enabled`; no new master flag.
  5. A docstring lists the consumers: skill statistics (G5-04), prediction settlement (B6), dismissal learning (B5-03).
- **Tests:** an explicit "down" overrides an implicit unknown; an explicit "up" overrides an implicit negative; a guest cannot post an outcome (403); a passing delegated task marks its requesting turn positive; a failing one leaves it as is; flag off: the route returns 404 or a no-op and nothing changes (ablation).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add a second correction or rephrase detector; call a model.

---

**B1-04 `/ws/aura` channel and event hub**
- **PRD:** 8.4, finding B5; design hook for P2-11 (chat report polling switches to this later)
- **Tier:** frontier (Phase 2 needs: `P2-31..33` and P2-11 follow-up)
- **Depends on:** B1-01
- **Files:** `src/aura/api/websocket.py` (new `aura_manager` and endpoint function, same `ConnectionManager` style), new `src/aura/autonomy/channel.py`, `src/aura/main.py` (`@app.websocket("/ws/aura")`), `src/aura/api/routes/` (new `aura_events.py` for the catch-up route), `src/aura/config.py`, new `tests/unit/test_aura_channel.py`
- **Change:**
  1. `channel.py`: `publish(event_type, payload, *, persist=True)` builds an envelope `{"v": 1, "seq": n, "type": ..., "at": iso, "payload": {...}}`. Types in B1: `aura_message`, `agenda_update`, `drive_state`, `chat_message`, `autonomy_state`, `ping`. `seq` is a monotone integer per process. A bounded ring buffer (`aura_channel_buffer`, default 200) keeps recent events.
  2. `chat_message` payload is exactly the message dict that `GET /chat/task-reports` returns (`id`, `conversationId`, `content`, `role`, `timestamp`, `meta`). That is the design hook: P2-11's task reports can later call `publish("chat_message", msg)` and the chat can subscribe instead of polling. Do not change `executor/task_reports.py` or `chat.tsx` in this card.
  3. `/ws/aura`: on connect, the client may send `{"type": "hello", "last_seq": n}` and receives the buffered events after `n`, then live events. A `ping` every 30 s (same pattern as `/v1/stream/traces`). Client messages of type `presence` are accepted and stored in a small in-memory `PresenceState` (typing, active view, last interaction time) for B5, nothing else is read from the client.
  4. `GET /aura/events?since_seq=n` returns the buffered events after `n`, the polling fallback (reconnect, tests, and a way for P2-11 to migrate in two steps).
  5. Events are delivered to the owner's app connection only. There is no per-guest channel; guests reach Aura only through Discord, and nothing in this card sends to Discord.
  6. Flag `AURA_WS_AURA_ENABLED` (default false): when off, the endpoint closes with 1008 and `publish` is a no-op that still returns the envelope.
- **Tests:** ordering and seq; catch-up after a given `last_seq`; the buffer bound; a failing client is dropped without affecting others; `publish` with the flag off sends nothing; `chat_message` payload equals the shape of a `/chat/task-reports` message (compare keys); presence is stored.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add auth schemes (the API is unauthenticated like the rest, per the open FOR_MAI item); migrate the chat's polling.

---

**B1-05 Agenda endpoints and manual-item delivery**
- **PRD:** 8, 8.2 (first part), 8.4; tests T4, T5
- **Tier:** bulk (Phase 2 needs: P2-33 reads delivery and P2-32 posts to the agenda)
- **Depends on:** B1-02, B1-04
- **Files:** new `src/aura/api/routes/agenda.py`, `src/aura/main.py` (router include; start and stop of the deliverer), new `src/aura/autonomy/delivery.py`, `src/aura/config.py`, new `tests/unit/test_agenda_delivery.py`
- **Change:**
  1. Routes: `GET /agenda?state=` (default pending and delivered), `POST /agenda` (owner creates a manual item: `kind` limited to `reminder` and `observation` here, `content`, `refs` default `["owner:manual"]` so manual items satisfy the refs rule honestly, `due_at`, `expires_at`), `POST /agenda/{id}/ack`, `POST /agenda/{id}/dismiss`. Each state change publishes `agenda_update` on the channel.
  2. `delivery.py`: `AgendaDeliverer` is event-driven (PRD 4.3). It runs `deliver_due()` when an item is created, when an item's `due_at` arrives (one `asyncio` timer set for the earliest `due_at`, re-armed on change, using the clock's `now`), when controls change, and on the 5-minute fallback check (`agenda_fallback_seconds`, default 300) which only handles stuck items. No model call.
  3. `deliver_due()` for each pending item whose `due_at` has passed: skip when `may_initiate(item.kind)` refuses (item waits), skip inside quiet hours (item waits, or expires if `expires_at` passed, T4), otherwise set `delivered`, publish `aura_message` for priority at or above `agenda_message_priority` (default 0.7) and `agenda_update` only (quiet indicator) below it. Write an `autonomy_trace` row for each delivery.
  4. Interruptibility is a stub function `interruptibility(now)` returning 1.0, in `delivery.py`, called through one name so B5-01 replaces it. Say so in the docstring.
  5. An item created while `silent` is stored and not delivered (T5); it is still readable through `GET /agenda`.
- **Tests (T4, T5):** quiet hours with a FakeClock: nothing delivered, item still pending, then delivered after the window or expired when `expires_at` passes; `silent`: item stays pending, drives and creation still work, no `aura_message`; muted kind waits; delivery sets state and publishes once; `due_at` in the future is not delivered early; the fallback timer does not double-deliver; routes round-trip.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add Discord delivery; deliver to any venue other than `app`.

---

**B1-06 Owner controls API and the kill switch (T14)**
- **PRD:** 8.3, test T14, principle 5, D6
- **Tier:** frontier (Phase 2 needs: P2-33 reuses the same routes for its slider)
- **Depends on:** B1-01, B1-05
- **Files:** `src/aura/autonomy/controls.py`, new `src/aura/autonomy/registry.py`, new `src/aura/api/routes/autonomy.py`, `src/aura/main.py`, `src/aura/executor/delegation.py` (only the existing `abort_all` entry point is called, not edited), `src/aura/executor/task_scheduler.py` (call its existing `shutdown`/cancel path only), `src/aura/engines/goal/engine.py` (`pursue_goal_autonomously` registers its task), new `tests/unit/test_autonomy_kill_switch.py`
- **Change:**
  1. `registry.py`: `register_autonomous_task(task: asyncio.Task, kind: str, owner_ref: str)` (added to a module set with a done-callback that removes it, so no unbounded growth), `cancel_all(reason)`, and `interrupt_for_user()` (cooperative pause hook, a no-op list of callbacks for now that B2-04 and B4-02 fill).
  2. Routes: `GET /autonomy` (level, muted kinds, killed, quiet hours, enabled flags), `PUT /autonomy/level`, `POST /autonomy/mute` and `POST /autonomy/unmute` `{kind}`, `POST /autonomy/kill`, `POST /autonomy/resume` (clears the kill; does not restart anything that was cancelled). Each change publishes `autonomy_state` and writes a trace row.
  3. Kill: set `killed` first (synchronous cache, so every `may_initiate` refuses at once), then `cancel_all`, then abort every autonomous delegation (call the G4-01 abort-all) and cancel running task graphs that were started autonomously (graphs carry `created_by_turn`; autonomous graphs have none, so select those and call the scheduler's cancel path; leave owner-started graphs alone and say so in the response). Return what was stopped. Everything must have finished within 2 s on the FakeClock-free path; the test measures wall time with fakes.
  4. `GoalEngine.pursue_goal_autonomously`: wrap its work in a registered task and call `may_initiate("pursue_goal")` first (refused when `silent`, muted or killed). `check_goals_needing_autonomous_pursuit` returns an empty list when the gate refuses. These two gates apply only when `autonomy_enabled`; off means the old behaviour.
- **Tests (T14):** with several fake long-running autonomous tasks, a delegation and an autonomous graph, `POST /autonomy/kill` cancels them all in under 2 s, leaves an owner-started graph running, and `may_initiate` refuses afterwards; resume clears the flag without restarting; level changes are reflected by `GET /autonomy`; gate on the goal engine blocks pursuit when `silent`; flag off leaves pursuit unchanged.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** make the kill switch depend on a flag, or on the database being reachable for the in-memory refusal.

---

**B1-07 Frontend: quiet indicator, agenda panel, owner controls, thumbs**
- **PRD:** 8.3, 8.4, 11 (thumbs control)
- **Tier:** bulk
- **Depends on:** B1-03, B1-04, B1-05, B1-06
- **Files:** new `frontend/src/services/auraChannel.ts`, new `frontend/src/hooks/useAuraChannel.ts`, new `frontend/src/components/agenda/` (AgendaIndicator, AgendaPanel, AutonomyControls), `frontend/src/pages/chat.tsx` (render `aura_message` events as assistant messages and the thumbs control; do not touch the task-report polling or the pursuit tag code), `frontend/src/services/auraApiService.ts` (client calls), the settings or dashboard page that fits (find it with grep, add the controls there)
- **Change:**
  1. `auraChannel.ts`: a WebSocket client for `/ws/aura` with reconnect and `hello {last_seq}`; sends `presence` (typing, active view) throttled to once per 5 s. `useAuraChannel` exposes events by type.
  2. Indicator: a small badge with the pending count; opening it shows the agenda items with acknowledge and dismiss. High-priority items arrive as assistant messages in the chat marked "Aura started this".
  3. Controls: level selector, per-kind mute switches, a clearly separated kill button with a confirm, and the killed state shown when set.
  4. Thumbs up and down on each assistant message calling `POST /chat/outcome`.
  5. Existing glass-panel styles; no new dependencies.
- **Tests:** vitest render tests: the indicator count; ack and dismiss call the API; the kill confirm; thumbs call the API; an `aura_message` event appears in the chat; the client resends `hello` with the last seq after a reconnect.
- **Done when:** `npm test` and `npm run build` pass, and the full Python suite passes.
- **Do not:** change how the chat polls `/chat/task-reports`.

---

**B1-08 B1 scenario tests on the simulated clock (T4, T5, T14)**
- **PRD:** 12 T4, T5, T14
- **Tier:** bulk
- **Depends on:** B1-01 to B1-06
- **Files:** new `tests/scenarios/test_behavior_b1.py`, `docs/FOR_MAI.md`
- **Change:**
  1. Three end-to-end scenarios over the real services with fakes and a `FakeClock`: T4 (a reminder due at 02:00 inside quiet hours is delivered at 08:00, or expires), T5 (`silent`: create items, advance a day, nothing delivered, nothing started, controls still readable), T14 (kill during a running fake investigation and a fake delegation, all stopped within 2 s).
  2. Add to FOR_MAI the three PRD open items that B1 chose defaults for (autonomy default `important`, quiet hours 22:00 to 08:00) so Mai can confirm or change them.
- **Tests:** the scenarios.
- **Done when:** the scenarios pass and the full suite passes.

---

**B2-01 Drives as persisted scalars**
- **PRD:** 5, principle 3 and 6
- **Tier:** frontier
- **Depends on:** B1-01, B1-04
- **Files:** `scripts/schema_behavior.surql`, new `src/aura/autonomy/drives.py`, `src/aura/config.py`, new `tests/unit/test_drives.py`
- **Change:**
  1. `drive_state` singleton row `drive_state:main`: `curiosity`, `competence`, `connection`, `coherence`, `rest` floats 0..1 (default 0.3), `updated_at`.
  2. `DriveModel` with pure arithmetic, no model call: `on_event(name, payload, now)` applies per-event deltas from config (`drive_delta_<event>_<drive>`, all in `config.py`): events `question_opened`, `question_resolved`, `prediction_failed` (reserved for B6), `goal_unfinished_tick`, `task_done`, `finding_pending`, `finding_delivered`, `exchange_happened`, `contradiction_open`, `contradiction_settled`, `dream_completed`, `consolidation_debt` (count of `episode` rows with `extraction_status = "pending"`, read from the table with a parameterised count query; no new field). Plus slow time drift: `drive_decay_per_hour` toward baseline, computed from `now - updated_at` when an event arrives, not from a timer.
  3. `gain(drive, emotion_vector) -> float`: the drive level times an emotion factor in `[0.8, 1.2]` built from the matching dimensions (curiosity: `curiosity`, `fascination`; competence: `boredom`; others 1.0). Emotion modulation is behind `drive_emotion_modulation_enabled` (default false, ablation: off means factor 1.0). The 20% bound is a clamp in code and in a test.
  4. Persist after each change; publish `drive_state` on the channel (if enabled). Whole feature behind `drives_enabled`. Drives update even at autonomy `silent` (T5).
  5. Boredom stops being a goal generator in B3-06, not here; here it is only an input to the gains.
- **Tests:** each event moves only the listed drives; values clamp to 0..1; decay is computed from the FakeClock; the factor never leaves 0.8 to 1.2 even with extreme emotions; modulation off gives exactly the raw level (ablation); persistence round trip; flag off does nothing and writes no row.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** call a model; read `datetime.now`.

---

**B2-02 Proposals and the workspace registry**
- **PRD:** 4.1
- **Tier:** bulk
- **Depends on:** B2-01
- **Files:** new `src/aura/orchestrator/workspace.py`, `src/aura/orchestrator/message_bus.py` (read only; use its existing `PROPOSAL` type and `subscribe`), `src/aura/models/` (read `EngineMessage` first), `src/aura/config.py`, new `tests/unit/test_workspace_proposals.py`
- **Change:**
  1. `Proposal` and `Cost` models per PRD 4.1: `source`, `kind` (the seven kinds), `summary`, `refs`, `urgency`, `value`, `cost` (`tokens`, `seconds`, `risk` in `read|write|execute|send`), `expires_at`, `created_at`, `id`. A proposal needs non-empty `refs` (same rule as the agenda) and a `summary` of one line.
  2. `Workspace.post(proposal)`: validates, stores in a bounded in-memory dict (`workspace_max_proposals`, default 50, oldest expired first), and returns the id. Engines may post through the message bus (`PROPOSAL` message) or by calling `post` directly; the workspace subscribes once and converts bus messages.
  3. `live(now)` drops expired proposals. Duplicates (same `source`, `kind` and sorted `refs`) replace the older one.
  4. Everything behind `workspace_enabled`; off means `post` returns None and nothing subscribes.
- **Tests:** validation (empty refs, multi-line summary); expiry with a FakeClock; duplicate replacement; bound; a bus `PROPOSAL` message reaches the workspace; flag off is inert.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** replace or modify the message bus.

---

**B2-03 The attention step**
- **PRD:** 4.2, principle 2, rule 5
- **Tier:** frontier
- **Depends on:** B2-02, B1-01
- **Files:** `src/aura/orchestrator/workspace.py`, `src/aura/autonomy/trace.py`, `src/aura/config.py`, new `tests/unit/test_workspace_attention.py`
- **Change:**
  1. `Workspace.attend(now, budget) -> Winner | None`. Steps: a pending user message wins and pre-empts (returns None for autonomous work and calls `registry.interrupt_for_user()`); otherwise drop proposals refused by `may_initiate(kind_to_gate_kind)` (map each proposal kind to a gate kind; `respond` is never autonomous); drop proposals whose cost exceeds the `budget` object passed in (rule 4: the caller passes the budget, `attend` never reads config or wall time; the budget object is a small dataclass with `tokens`, `seconds` and `allow_risk`, and B4-03 fills it); score each remaining proposal `urgency * value * drive_gain / max(cost_score, epsilon)`, where `cost_score` is a normalised combination from config weights and `drive_gain` comes from B2-01 by the kind-to-drive map from PRD section 5 (`investigate` to curiosity, `pursue_goal` and `practice` to competence, `share` and `ask_user` to connection, `consolidate` to rest, `ask_user` also to coherence taking the max).
  2. Rejections and the winner each write an `autonomy_trace` row with source, reason and cost (rule 5). Ties break by `created_at`.
  3. The winner is published on the bus as a broadcast message and returned; the outcome is posted back later as an event (B2-04).
  4. A cooldown is NOT designed here; B5-02 owns refractory periods. `attend` only picks.
- **Tests:** a user message wins over a high-scoring proposal; the highest scored wins; an over-budget proposal is rejected and logged; a proposal refused by the gate (silent, muted, killed) is rejected and logged; the drive gain changes the winner; with `drives_enabled` off the gain is 1.0 (ablation); every outcome has a trace row; `attend` called with a FakeClock never reads wall time.
- **Done when:** the new tests pass and the full suite passes.

---

**B2-04 Event triggers, the cycle runner and the pre-emption hook (T1, T12)**
- **PRD:** 4.3, test T1, T12, finding B1 and B7
- **Tier:** frontier (Phase 2 needs: P2-33 relies on the cycle being the only self-start path)
- **Depends on:** B2-03, B1-06
- **Files:** `src/aura/orchestrator/workspace.py` (`Workspace.on_event`, `run_cycle`), `src/aura/orchestrator/coordinator.py` (one hook in `_turn_pipeline` that fires `user_message` and nothing else; also one in `_dreaming_sequence` end for `dream_completed`), `src/aura/executor/task_queue.py` and `src/aura/executor/task_scheduler.py` (one call each to `on_event("task_result")` at the existing completion points; read them first), `src/aura/engines/goal/engine.py` (`tick`: skip the boredom and idle `_consider_new_goal` branches when `workspace_enabled`), `src/aura/main.py` (create and start), `src/aura/config.py`, new `tests/unit/test_workspace_cycle.py`
- **Change:**
  1. Event names: `user_message`, `task_result`, `question_resolved`, `prediction_settled` (reserved for B6), `dream_completed`, `agenda_due`. `on_event` updates drives (B2-01) and schedules a cycle with `asyncio` (never awaited inside the turn; the hook is `create_task` with exceptions logged). A slow fallback (`workspace_fallback_seconds`, default 300) only checks that nothing is stuck; it posts no proposals and calls no model.
  2. `run_cycle`: call `attend`, and when there is a winner, dispatch by kind to a handler registered with `register_handler(kind, coro)`. B2 registers none (handlers come in B4 and B5); an unhandled winner is traced as "no handler" and dropped. So at the end of B2 nothing autonomous happens yet, which is the point: T1.
  3. Pre-emption (T12): `user_message` calls `registry.interrupt_for_user()` synchronously inside the hook before the reply is generated; handlers registered by autonomous work must pause within 2 s. The workspace supplies `PauseToken` (an `asyncio.Event`) that long autonomous work checks between steps; define it here and use it in B4-02.
  4. With `workspace_enabled` on, the goal engine's `tick` no longer creates goals from boredom or idle time (the B1 finding), and says so in the trace once at startup. Off keeps the old branches exactly. The goal-progress and stale-goal code in `tick` is left for B3.
  5. Hook placement is one place in `_turn_pipeline` (B0 merged the pipelines), so T13 stays true: add a test that both entry points fire it once.
- **Tests:** T1 (idle for six simulated hours with no questions and no findings, no cycle produces a delivery or an investigation, zero `aura_message` events); T12 (a fake autonomous task holding a `PauseToken` pauses within 2 s of a `user_message` event while the reply proceeds); each event name schedules exactly one cycle; the fallback does not post proposals; the boredom branch is skipped when on and runs when off (ablation); both entry points fire the hook once.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add a model call to a cycle, or put work on the chat reply path.

---

**B3-01 Goal schema v2: criteria, evidence, abandoned**
- **PRD:** 9, findings B2 and B3; hook for P2-31
- **Tier:** frontier (Phase 2 needs: `P2-31..32`)
- **Depends on:** B1-01
- **Files:** `src/aura/models/goal.py`, `scripts/init_schema.surql` (or a `DEFINE FIELD IF NOT EXISTS` block in `scripts/schema_behavior.surql`; prefer the latter so existing databases migrate), `src/aura/engines/goal/engine.py` (`_load_active_goals` and the goal create paths, read only for the row shape), `src/aura/config.py`, new `tests/unit/test_goal_criteria_model.py`
- **Change:**
  1. `Goal.status` gains `abandoned`. New `option` fields on the `goal` table and model: `criteria` (array of objects), `abandon_reason`, `last_evidence_at`, `evidence` (array of objects). Existing rows read as `None` and behave as before.
  2. Criterion shape: `{"id": str, "name": str, "kind": "test_pass"|"file_exists"|"question_resolved"|"owner_confirms"|"task_node_done", "spec": dict, "status": "open"|"met", "met_at": option, "evidence_ref": option str}`. The kind names deliberately match the P2-32 evidence kinds (`test_pass`, `file_exists`, `task_node_done`, `mai_confirms` maps to `owner_confirms`) so P2-31 and P2-32 add `milestones` on top without renaming. Say so in a comment.
  3. Helper `Goal.progress_from_criteria()` returns met over total, or None when there are no criteria.
  4. The `goal` list and get routes (`api/routes/goal.py`) return the new fields. Add `POST /goal/{id}/criteria` (owner adds or edits criteria) and `POST /goal/{id}/criteria/{cid}/confirm` (the owner confirms an `owner_confirms` criterion).
  5. Everything behind `goals_v2_enabled` for behaviour; the schema and fields exist always (option, harmless).
- **Tests:** model round trip with and without the new fields; legacy rows load; `progress_from_criteria`; criteria routes; owner confirm only works on `owner_confirms`; abandoned status accepted by the table.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add stages, milestones, origin objects or `close_reason` (P2-31).

---

**B3-02 Criteria checker and evidence-based progress (T7)**
- **PRD:** 9, finding B2, test T7
- **Tier:** frontier (Phase 2 needs: `P2-32` extends this checker with commits and metrics)
- **Depends on:** B3-01
- **Files:** new `src/aura/engines/goal/evidence.py`, `src/aura/engines/goal/engine.py` (`tick`: replace the mood-increment block when `goals_v2_enabled`; `update_goal_progress` read first), `src/aura/config.py`, new `tests/unit/test_goal_evidence.py`
- **Change:**
  1. `evidence.check(goal, now) -> list[Met]`, code only, no model call: `file_exists` (path under a registered workspace only; read the G3 workspace registry and refuse paths outside), `test_pass` (a delegation or code-node task row with tests passing for the goal id), `task_node_done` (a `task_node` row in `done` state for the graph linked to the goal), `question_resolved` (the `question` row status is `resolved`), `owner_confirms` (set by the route in B3-01).
  2. In `tick`, when `goals_v2_enabled`: remove the emotional-alignment increment. Progress is set to `progress_from_criteria()` (met over total) only when it changed, with the reason "criterion met: <name>" and `last_evidence_at` stamped. A goal without criteria keeps its progress unchanged (T7: matching mood and no work done leaves progress at zero). Completion at 100% requires all criteria met.
  3. Also trigger the check on events (a task node finishing, B2-04's `task_result`), not only the 30-second tick, so progress is prompt.
  4. Leave the mood code path untouched when the flag is off (ablation test).
- **Tests (T7):** a goal with matching mood and no work done stays at 0.0 over many ticks; a `file_exists` criterion met moves progress; each kind positive and negative; a path outside a registered workspace is not evidence; completion only when all met; flag off still raises progress by mood (ablation).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** accept an LLM statement as evidence; implement milestones or stages.

---

**B3-03 Stall and abandonment, remove stale-complete (T8)**
- **PRD:** 9, finding B3, test T8
- **Tier:** bulk
- **Depends on:** B3-02
- **Files:** `src/aura/engines/goal/engine.py` (`tick` stale block, `update_goal_progress`), `src/aura/autonomy/agenda.py` (read), `src/aura/config.py`, new `tests/unit/test_goal_abandonment.py`
- **Change:**
  1. When `goals_v2_enabled`, replace the "older than 24 h with under 10 percent progress is marked complete at 100 percent" block with: a goal whose `last_evidence_at` (or `created` when none) is older than `goal_stall_days` (default 7) and which is not complete becomes `abandoned` with `abandon_reason` "no evidence for N days", a `completed` stamp left empty, and progress unchanged.
  2. An agenda `observation` item with the goal id in `refs` tells the owner once (through `AgendaService`, subject to `may_initiate`).
  3. The owner can reopen an abandoned goal (`POST /goal/{id}/reopen`), which resets `last_evidence_at` to now.
  4. Flag off keeps the old stale-complete branch exactly.
- **Tests (T8):** a goal stalled past the limit becomes `abandoned`, never `completed`, progress not set to 1.0; a goal with fresh evidence is not abandoned; the agenda item is created once; reopen; flag off keeps the old behaviour (ablation). Clock via FakeClock.
- **Done when:** the new tests pass and the full suite passes.

---

**B3-04 Pursuit grants and the risk check (T11)**
- **PRD:** 9, principle 4, rule 7, test T11
- **Tier:** frontier (Phase 2 needs: P2-33 item 3 builds on grants)
- **Depends on:** B3-02, B1-05
- **Files:** `scripts/schema_behavior.surql`, new `src/aura/autonomy/grants.py`, `src/aura/executor/tool_executor.py` (`execute_tool_call`; read the role and tier checks first), `src/aura/executor/tool_registry.py` (read `Risk` only), `src/aura/config.py`, new `tests/unit/test_pursuit_grants.py`
- **Change:**
  1. `pursuit_grant` table: `goal_id`, `scope` (`write`, `execute`, `send`), `budget` object (`tokens`, `minutes`, `calls`, all option), `granted_by`, `granted_at`, `expires_at`, `revoked_at` option<datetime>. Read-only work needs no grant.
  2. `grants.check(goal_id, risk, now) -> bool`: false when no live grant for that risk. A tool with an unknown risk counts as needing a grant (PRD rule 7).
  3. `execute_tool_call` accepts a reserved `_autonomous` context (`{"goal_id": ..., "source": ...}`), passed the same way as `_venue`, `_requester_role` and `_session`, and never in the model-visible schema (see W1-02 and G4-04a). When present and the tool's risk is above `read` and `grants.check` fails: the call is refused with a clear message, a `needs_decision` agenda item is created with `refs=[goal_id, tool_name]` (once per goal and tool, not per call), and an `autonomy_trace` row is written. Owner-initiated calls (no `_autonomous`) are unchanged. The order stays: role, tier, session, then this check.
  4. Grants are revoked automatically at expiry and by the kill switch (B1-06 calls `grants.revoke_all()`).
  5. Behind `goals_v2_enabled`.
- **Tests (T11):** an autonomous write call without a grant is blocked and one `needs_decision` item is created, a second blocked call adds no duplicate; with a live grant it passes; an expired grant blocks; an unknown-risk tool needs a grant; an owner call is unaffected; the schema offered to the model has no `_autonomous` argument; kill revokes grants; flag off changes nothing.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** infer read-only from a tool's name.

---

**B3-05 `request_pursuit` tool, decision to grant (replaces the text tag)**
- **PRD:** 9, finding B4
- **Tier:** frontier
- **Depends on:** B3-04
- **Files:** new `src/aura/tools/request_pursuit.py`, `src/aura/executor/tool_registry.py` (registration; read how `plan_task` is registered and gated), `src/aura/executor/decisions.py` (`answer`: after a `needs_decision` with `action="pursuit"` is allowed, create the grant), `src/aura/autonomy/grants.py`, `src/aura/config.py`, new `tests/unit/test_request_pursuit.py`
- **Change:**
  1. Tool `request_pursuit(goal_id, scope, budget)`: owner role only (guests cannot call it); validates the goal exists and is active, `scope` in `read`, `write`, `execute`, `send`, and the budget numbers are within config caps (`pursuit_max_minutes`, `pursuit_max_tokens`). A `read` scope needs no grant: the tool starts a read-only pursuit under the gate and returns. Other scopes create a `needs_decision` through `DecisionService.create` (`action="pursuit"`, `risk` from scope, `message` stating goal, scope, budget and expiry) plus an agenda item (`kind="needs_decision"`, `refs=[goal_id, decision_id]`), and return "waiting for the owner".
  2. `DecisionService.answer`: when the decision's `action == "pursuit"` and it is allowed, call `grants.create(...)` with the expiry from `pursuit_grant_hours` (default 24); denied creates nothing. The existing early return for `needs_decision` is kept; only add this branch before it.
  3. Tool offered only when `goals_v2_enabled` and the tier profile allows tools (same pattern as `plan_task`). Off means the tool list is exactly as before.
- **Tests:** guest refused; unknown goal refused; read scope starts without a decision; write scope creates exactly one decision and one agenda item; approving creates a grant with an expiry; denying does not; flag off leaves the tool list unchanged.
- **Done when:** the new tests pass and the full suite passes.

---

**B3-06 Remove the pursuit text tag; goal creation under the gate**
- **PRD:** 9 (last bullets), finding B4, principle 1
- **Tier:** bulk
- **Depends on:** B3-05, B2-04
- **Files:** `src/aura/llm/layers.py` (the `GOAL_PURSUIT_REQUEST` prompt blocks near lines 1345 to 1380), `frontend/src/pages/chat.tsx` (`checkForGoalPursuitRequest` and its callers), `src/aura/engines/goal/engine.py` (`_consider_new_goal`, `check_boredom`, `generate_goal_on_demand` callers), `src/aura/config.py`, new `tests/unit/test_goal_tag_removed.py`, frontend test
- **Change:**
  1. When `goals_v2_enabled`: the prompt section that teaches the tag is replaced by two sentences telling Aura to use the `request_pursuit` tool. Off keeps the tag text byte for byte. Do not otherwise edit the prompt (P2-12 rewrites it).
  2. `chat.tsx`: when the server reports `goals_v2` on (read from `GET /autonomy`), skip the tag regex and modal; otherwise unchanged. Remove the regex path entirely only in a later cleanup card, after the flag defaults on (say so in a code comment).
  3. Goal creation by Aura: goals come from the owner, from an accepted drive proposal or (at `open`) from a read-only curiosity question. `_consider_new_goal` under `goals_v2_enabled` returns immediately unless called with an `accepted_proposal` argument. `check_boredom` stays as a read-only getter (an input to drive gains). Leave the hook comment: P2-33 re-adds proposals at its level 2 through `may_initiate`.
- **Tests:** the prompt contains the tag text with the flag off and not with it on; `_consider_new_goal` creates nothing from `boredom` or `idle_exploration` triggers when on; an accepted proposal still creates a goal; frontend test: with `goals_v2` on a `[GOAL_PURSUIT_REQUEST:x]` string in a reply opens no modal.
- **Done when:** the new tests pass, `npm test` and `npm run build` pass, and the full suite passes.
- **Do not:** delete the tag code path while the flag can still be off.

---

**B4-01 Question scoring without learning value (and random ablation)**
- **PRD:** 6.1, 6.2 (relevance and tractability), ablation list; hook for B6 learning value
- **Tier:** frontier
- **Depends on:** B2-04
- **Files:** `scripts/schema_behavior.surql` (option fields on `question`: `score`, `scored_at`, `tractability`, `parked_reason`, `resolved_by`), new `src/aura/autonomy/curiosity.py`, `src/aura/engines/memory/v2/` (read how `question` rows are created and recalled; relevance reads the graph through the existing recall or graph query helpers, not new SQL strings built by hand), `src/aura/config.py`, new `tests/unit/test_question_scoring.py`
- **Change:**
  1. `relevance(question) -> float`: closeness to the owner's active goals, projects and recent topics. Use the question's linked entities from the graph; score by shared entities with active goals and with entities of the last N episodes (`curiosity_recent_episodes`, default 20). Pure arithmetic on rows read once per cycle.
  2. `tractability(question) -> (float, route)`: rule-based, no model: a question linked to a speaker or preference node is `ask_user` (tractability 1.0 for asking, 0 for tools); a question with external-looking entities (libraries, products, urls) is `search`; a question about files in a registered workspace is `read`; otherwise `search` with a low value. Routes: `search`, `read`, `ask_user`, `park`.
  3. `score = learning_value * relevance * tractability` where `learning_value` is the constant `1.0` through one function `learning_value(question)` that B6 replaces. Say so in the docstring.
  4. Only questions visible to the owner and created from owner conversations are scored. Guest-created or guest-visibility questions are never scored or investigated (PRD open item 4 recommended: only the owner; confirm with Mai).
  5. Ablation flag `curiosity_random_choice` (default false): when on, the choice among questions above a minimum is random with a seeded RNG passed in (`random.Random`). The default is the scored choice.
  6. `pick_questions(now, limit)` returns the top scored open questions with their route and writes the score back (option fields). Behind `curiosity_enabled`.
- **Tests:** two questions, one relevant and tractable ranks above one irrelevant; owner-preference question routes to `ask_user`; guest-visibility question excluded; random mode picks differently from scored mode under a seeded RNG (ablation); scoring is stable (same inputs, same order); flag off returns nothing.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add learning-value or prediction-error tracking (B6).

---

**B4-02 Investigations: bounded, read-only, pausable**
- **PRD:** 6.3 (steps 1 to 4), principle 4, tests T11 (shared with B3-04), T12 (shared with B2-04)
- **Tier:** frontier
- **Depends on:** B4-01, B2-04, B3-04
- **Files:** new `src/aura/autonomy/investigation.py`, `src/aura/executor/task_scheduler.py` (read `_run_research`, `_ResearchExecutor` and `_research_tool_definitions`; reuse them, do not copy), `src/aura/engines/memory/v2/facts.py` (`write_facts`, read the provenance handling first), `src/aura/orchestrator/workspace.py` (register the handler for `investigate`), `src/aura/config.py`, new `tests/unit/test_investigation.py`
- **Change:**
  1. `InvestigationRunner.run(question, route, budget, pause_token)`: reuses the research-node loop of the task scheduler with its read-only tool set (search, read, recall). Hard limits from config: `investigation_max_tokens`, `investigation_max_tool_calls`, `investigation_max_minutes`; any limit stops it and records the reason. Every tool call carries `_autonomous={"goal_id": None, "source": "investigation"}` so B3-04 blocks any non-read tool and creates a `needs_decision` item (T11 at investigation level).
  2. Model calls happen only inside the investigation, which is itself an event handler for a winning `investigate` proposal (rule 2); each call goes through the existing budget and cost record. Uses the L2 model, never L3, unless the tier profile says otherwise.
  3. `PauseToken` from B2-04 is checked between steps; a user message pauses within 2 s and the run resumes only on the next winning cycle (state `paused`, progress kept). The runner registers its task with `registry.register_autonomous_task` so the kill switch stops it (T14).
  4. Result: findings written with `write_facts` (provenance `external`, with source urls in the existing sources field). A trace row records cost.
  5. A `question` row ends `resolved`, `partial` or `parked` with a reason (B4-04 handles what follows).
  6. Only registered for owner-visible questions (B4-01 rule). Behind `curiosity_enabled`.
- **Tests:** each limit stops the run and records its reason; a write-tool attempt is blocked and creates one `needs_decision` (T11); a pause token set mid-run pauses within 2 s on fakes (T12); findings are stored with provenance `external` and sources; kill cancels the run; a guest-visibility question is refused; flag off registers no handler. Fake LLM and fake tools only.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** use OpenCode explore agents here (a later card; the research node loop is the read-only path that already exists).

---

**B4-03 Daily budgets and rejection logging (T6)**
- **PRD:** 6.4, rule 4, test T6; hook for P2-33 daily budgets
- **Tier:** bulk
- **Depends on:** B4-02
- **Files:** `scripts/schema_behavior.surql`, new `src/aura/autonomy/budget.py`, `src/aura/orchestrator/workspace.py` (the budget object passed to `attend`), `src/aura/autonomy/investigation.py` (record spend), `src/aura/config.py`, new `tests/unit/test_curiosity_budget.py`
- **Change:**
  1. `curiosity_budget` row per local day (`day` string, `investigations`, `tokens`, `spend_usd`). Ceilings from config: `curiosity_daily_investigations` (default 3), `curiosity_daily_tokens` (default 200000), `curiosity_daily_spend_usd` (default 0.0, meaning no paid spend until Mai sets it; PRD open item 2). With a spend ceiling of 0 only free or zero-cost routes may run, and the test says what that means in practice (tokens counted, spend ignored when the provider cost is zero).
  2. `Budget` object built from today's row and passed into `Workspace.attend`; when any ceiling is reached, `investigate` proposals are rejected and a trace row says "daily budget reached: <which>" (T6). Day rolls over at local midnight from `get_clock()` and `app_timezone`.
  3. `GET /autonomy/budget` returns the remaining budget for the mind panel (B7 shows it later) and publishes `drive_state`-style `autonomy_state` on change.
  4. This is a curiosity budget only. P2-33 adds message and Sage budgets through `may_initiate`; do not add those.
- **Tests (T6):** after the ceiling, further `investigate` proposals are rejected and logged, other kinds are unaffected; each ceiling alone triggers; rollover at midnight with a FakeClock resets; spend and tokens add up across runs; the endpoint reports remaining.
- **Done when:** the new tests pass and the full suite passes.

---

**B4-04 Findings to the agenda, ask-the-owner, share proposals**
- **PRD:** 6.3 steps 5 and 6, 8, test T2 (the setup half; delivery timing is B5-02)
- **Tier:** bulk
- **Depends on:** B4-02, B1-05, B2-02
- **Files:** `src/aura/autonomy/investigation.py` (finish hook), new `src/aura/autonomy/findings.py`, `src/aura/orchestrator/workspace.py` (handlers for `share` and `ask_user`), `src/aura/config.py`, new `tests/unit/test_findings_to_agenda.py`
- **Change:**
  1. After an investigation, `findings.publish(question, result)`: if the finding matters to the owner (relevance from B4-01 at or above `finding_share_relevance`, default 0.5), create an agenda `finding` item whose `content` is drafted by one short L2 call made as part of the investigation event (not on a timer, not on the chat path), `refs` the fact ids and question id, and post a `share` proposal. If the question's route is `ask_user` or the result says only the owner can answer, create a `question_for_you` item with the question as `content` and `refs=[question_id]`. She never guesses an answer for an owner-only question.
  2. Items expire after `finding_expiry_hours` (default 72). A parked question with a reason creates no item.
  3. The `question_resolved` event is sent to the workspace (B2-04), lowering the curiosity drive.
  4. The `share` and `ask_user` handlers only create the agenda delivery work; the actual delivery path is the B1-05 deliverer, still using the stub interruptibility until B5. They honour `may_initiate` and quiet hours.
  5. Guests: items are created only from owner-visible questions; nothing here can send to anyone but the owner.
- **Tests:** a relevant finding creates one `finding` item with refs and one `share` proposal; an irrelevant finding creates none; an owner-only question creates `question_for_you` and no fact is written; a parked question creates no item; the draft call runs once per finding; delivery respects silent and quiet hours; the curiosity drive drops on resolution.
- **Done when:** the new tests pass and the full suite passes.

---

**B5-01 The interruptibility model**
- **PRD:** 8.1, ablation (against a fixed cooldown)
- **Tier:** frontier (Phase 2 needs: `P2-33` item 5)
- **Depends on:** B1-04 (presence), B1-05
- **Files:** new `src/aura/autonomy/interruptibility.py`, `src/aura/autonomy/delivery.py` (replace the stub), `src/aura/autonomy/channel.py` (read `PresenceState`), `src/aura/executor/delegation.py` and `src/aura/executor/task_queue.py` (read only: is a delegated task running and watched), `frontend/src/services/auraChannel.ts` (the `watching` field in presence), `src/aura/config.py`, new `tests/unit/test_interruptibility.py`
- **Change:**
  1. `interruptibility(signals, now) -> float` in 0..1, pure: typing or active in the app now gives a low factor (`interrupt_typing_factor`, default 0.1); a delegated task running and the owner watching its page gives a low factor (0.3); seconds since the last owner message gives a curve that rises over `interrupt_rise_seconds` then falls after `interrupt_absence_hours` of absence; quiet hours return 0 (from `quiet_hours_active`); recent dismissals subtract a decaying penalty (read from the dismissal log of B5-03; until then zero). All factors in config.
  2. `collect_signals()` assembles the inputs from `PresenceState` (B1-04), the task queue and the agenda. The app sends `watching: task_id|null` in its presence message.
  3. Replaces the B1 stub when `interruptibility_model_enabled` is on. Ablation: off uses a fixed cooldown (`interrupt_fixed_cooldown_seconds`, default 600) and the stub value otherwise, which is the control the PRD's ablation compares against.
- **Tests:** each signal moves the value the right way; quiet hours are exactly 0; typing gives a low value and the value recovers after typing stops; the curve rises then falls with a FakeClock; the fixed-cooldown path when off (ablation); the function is pure (same input, same output).
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** add a model call; send presence data anywhere else.

---

**B5-02 Delivery decision and refractory period (T2)**
- **PRD:** 8.1 (threshold), 8.2 (refractory), test T2
- **Tier:** frontier (Phase 2 needs: `P2-33`)
- **Depends on:** B5-01
- **Files:** `src/aura/autonomy/delivery.py`, `src/aura/autonomy/agenda.py` (read), `src/aura/config.py`, new `tests/unit/test_delivery_threshold.py`, `tests/scenarios/test_behavior_b5.py`
- **Change:**
  1. `deliver_due()` delivers an item when `effective_priority * interruptibility >= threshold(kind)`. Per-kind thresholds from config (`delivery_threshold_<kind>`), `needs_decision` for a blocked task uses the lower `delivery_threshold_needs_decision` (default lower than the others). Thresholds are read from the learning state of B5-03 when present, otherwise from config.
  2. Refractory period: after a delivery, no other unprompted message for `delivery_refractory_seconds` (default 900); items wait, they are not dropped.
  3. Re-evaluate on events that change the inputs: typing stopped (presence event), a task finished, the owner's reply, quiet hours ending (one timer to the boundary), item created. No polling loop; the 5-minute fallback remains.
  4. A trace row records the product, the threshold and the decision for every evaluation that delivers or defers.
  5. This card also honours the kill switch and the gate; deferral is silent.
- **Tests (T2):** a question resolved while the owner is typing: the `finding` item is delivered only after typing stops and the threshold is met (FakeClock and presence events); refractory delays a second item; a `needs_decision` item delivers at an interruptibility where a `finding` would not; deferral writes a trace row; with the model off the old fixed cooldown applies (ablation).
- **Done when:** the new tests pass and the full suite passes.

---

**B5-03 Dismissal learning, three-strikes mute (T3)**
- **PRD:** 8.2 (after delivering), test T3, 11 (outcomes feed it)
- **Tier:** frontier
- **Depends on:** B5-02, B1-03
- **Files:** `scripts/schema_behavior.surql`, new `src/aura/autonomy/learning.py`, `src/aura/autonomy/delivery.py`, `src/aura/autonomy/controls.py`, `src/aura/api/routes/agenda.py`, `src/aura/config.py`, new `tests/unit/test_dismissal_learning.py`
- **Change:**
  1. `agenda_kind_stats` table per kind: `threshold_delta` float, `consecutive_dismissals` int, `muted_until` option<datetime>, `delivered`, `acknowledged`, `dismissed`, `ignored` ints.
  2. Acknowledge (or the owner replying about the item, or acting on it) eases the kind's threshold by `dismissal_ease_step` (clamped to a floor); dismiss or ignore (a delivered item unanswered for `agenda_ignore_hours`, default 24, moved to `expired` with `ignored` counted) raises it by `dismissal_raise_step` (clamped to a ceiling) and increments consecutive dismissals. Three in a row (`dismissal_mute_after`, default 3) set `muted_until` to the clock plus a day and trace it; an acknowledgement resets the streak. Muted-by-learning kinds are read by `may_initiate` alongside manual mutes (the owner can lift it).
  3. The recent-dismissal penalty in B5-01 now reads the last dismissals from this log.
  4. Reply-rate per kind (`acknowledged` over `delivered`), exposed by `GET /autonomy/stats`, for the mind panel later and for the PRD's "the number that matters".
  5. Behind `dismissal_learning_enabled`; off keeps the config thresholds fixed (ablation).
- **Tests (T3):** three dismissals of `finding` items mute `finding` for a day and leave `question_for_you` and the others unaffected; an acknowledgement between dismissals resets the streak; the mute ends after a day on the FakeClock; ignore after the timeout counts as a dismissal; thresholds stay inside their clamps; flag off leaves thresholds fixed; stats compute the reply rate.
- **Done when:** the new tests pass and the full suite passes.

---

**B5-04 Working-set offer: bring pending items up inside the reply**
- **PRD:** 8.2 (last bullet)
- **Tier:** frontier
- **Depends on:** B5-03, B1-05
- **Files:** `src/aura/engines/recall/` (read how the Recall Engine builds the context packet and its working-set block; extend with one optional source), `src/aura/orchestrator/coordinator.py` (only where the recall call receives its arguments, inside `_turn_pipeline`), new `src/aura/autonomy/offer.py`, `src/aura/config.py`, new `tests/unit/test_agenda_offer.py`
- **Change:**
  1. `offer.relevant_items(user_text, entities, now, limit)`: pending items (not yet delivered) whose `refs` or content overlap the entities or tokens of the owner's message, by lexical and entity overlap only, no model call and a tight time bound, since this is on the chat hot path.
  2. Offered as a labelled working-set block ("things you were holding for the owner") to the Recall Engine; the reply may mention them. When the reply includes the item (detected by the item id being in the offered block and an explicit `[agenda:id]` marker the block asks the model to return, stripped before display, or, simpler and preferred, by the owner's next message acknowledging), mark it `delivered` and `acknowledged` through the service; otherwise leave it pending.
  3. Behind `interruptibility_model_enabled` and `autonomy_enabled`; guests: the block is built only for the owner's turns (role check).
- **Tests:** an item matching the owner's topic is offered; an unrelated item is not; the block is absent for a guest turn and when the flag is off; the hot-path cost is bounded (no database call beyond one indexed query, asserted with a counting fake); an offered item moves to `delivered`.
- **Done when:** the new tests pass and the full suite passes.
- **Do not:** make a model call on the chat path; interrupt the owner with an item this way.

---

---


## 5. Later waves

Cards for these are written at the start of each wave (see 1.3). Milestone details are in the PRDs.

### Wave 2: foundations for the new systems

| Milestone | What | Tier |
|---|---|---|
| B0 | merge `process_query` and `stream_query` into one pipeline | frontier |
| M2 | Recall Engine skeleton: one entry point, budget, deduplication, trace | frontier design, bulk for wiring |
| V0 | remove the VRM avatar | bulk |
| G1 | tool registry and the single tool loop | frontier |
| M0 remainder | scenario runner and probe set | frontier writes probes, bulk writes the runner |

B0 comes first in this wave. M2 and G1 both edit the turn pipeline and must not start until it lands.

### Wave 3: the new cores

| Milestone | What | Tier |
|---|---|---|
| M3 | indexes, parallel channels, fusion, query building, gate, abstention | mixed |
| M4 | schema v2, extraction, entity resolution, supersession, speakers and visibility | frontier |
| E2, E3 | events, appraisal, causes, new state interface | frontier |
| G2, G3 | OpenCode client, `delegate_work`, agents, policy and approvals | frontier for the client, mixed for the rest |
| V1 to V4 | new stage, controller, affect and cognitive layers | mixed |

### Wave 4: behaviour on top

| Milestone | What | Tier |
|---|---|---|
| M5, M6 | graph and temporal retrieval, recall tools, feedback, dreaming v2 | mixed |
| E4, E5 | mood, relationships | mixed |
| B1 to B5 | outcomes, agenda, workspace, drives, goals v2, curiosity, interruptibility | frontier for B2 and B4, mixed otherwise |
| G4 to G6 | Workbench, removal of the IDE and agent loop, skills v2, distillation | mixed |
| V5 to V7 | animation library, gesture layer, speech | mixed |

### Wave 5: experimental and polish

| Milestone | What |
|---|---|
| M7 | reconsolidation, `co_used`, bisociation |
| B6, B7 | predictions, learning-value scoring, inner thoughts |
| E6, E7 | regulation, recall echo, temperament drift |
| G7, G8 | swarms, generated tools as separate processes, practice |
| V8 | final asset, shading, governor |

Every item in wave 5 ships behind a flag with an ablation test, and is removed if it shows no measured effect.

---

## 6. Things only Mai can do

1. Purge `.aura/` from git history and decide the repository's visibility (after W0-01).
2. Verify finding S1 on a private Discord server before and after W1-01.
3. Set `discord_owner_ids`.
4. Pin an OpenCode version (before wave 3).
5. Build the avatar asset (needed by V8, useful from V1).
6. Answer the open items at the end of each PRD.

---

## Follow-up cards (2026-11-25, from supervisor review notes)

**FU-01 web_search makes its result URLs usable as consult `url:` refs**
- **Tier:** bulk
- **Files:** `src/aura/tools/web_search.py`, new `tests/unit/test_web_search_url_refs.py`
- **Change:**
  1. In `web_search.run`, after the results are formatted, for each result call `aura.tools.consult.note_fetched_url(url, content)` with the result's full `content` (before truncation). Import inside the function. Wrap in `try/except Exception` so search never fails because of it. Only when `settings.consult_enabled` is true.
  2. Replace the footer's `datetime.datetime.now()` with `aura.clock.get_clock().now()`.
- **Tests:** with `consult_enabled` on and the HTTP call faked (monkeypatch `aiohttp.ClientSession` or the function that posts), two results make two URLs resolvable through consult's ref resolver in the same turn (`consult.begin_turn()` first); flag off notes nothing (ablation); a failure inside `note_fetched_url` does not change the search output.
- **Do not:** make any real network call in tests; change the output format apart from the timestamp source.

---

**FU-02 Delegated tasks record goal_id and tests_passed (test_pass evidence)**
- **Tier:** bulk
- **Files:** `src/aura/executor/delegation.py`, `src/aura/tools/delegate_work.py` (or wherever the `delegate_work` tool builds `DelegationConfig`; find it with grep), new `tests/unit/test_delegation_test_pass.py`
- **Change:**
  1. `DelegationConfig` gets `goal_id: Optional[str] = None`. The `delegate_work` tool accepts an optional `goal_id` argument (a `goal:<id>` string) and passes it through; add it to the tool's parameter schema as optional.
  2. When the task is created or finalised, if `config.goal_id` is set, store `goal_id` on the task as a record id (`to_record_id`) through the existing `_merge_task_fields`.
  3. In `_finalize_task`: when `reviewed` is True store `tests_passed: True`; when the outcome is `failed` after a review store `tests_passed: False`. Use `_merge_task_fields`.
  4. `engines/goal/evidence.py::_test_pass` then finds the task; do not change its query except if the test proves it wrong.
- **Tests (EmbeddedSurrealDB with the real schema):** a delegation with `goal_id` whose review passes leaves a task with `goal_id` and `tests_passed = true`, and `_test_pass(db, goal_id, {})` returns that task id; a failed review stores `tests_passed = false` and `_test_pass` returns None; no `goal_id` given changes nothing (ablation).
- **Do not:** change permissions, requester roles or the review logic.

---

**FU-03 Real USD costs for consult helper calls**
- **Tier:** bulk
- **Depends on:** P2-27, P2-28, P2-29
- **Files:** `src/aura/llm/layers.py` (`plain_call`), `src/aura/tools/consult.py`, tests in `tests/unit/test_consult.py`
- **Change:** `plain_call` also returns the provider usage when the provider gives it (tokens in/out and cost in USD, as the OpenRouter non-streaming path already reads it for tool rounds; reuse that code). Keep the old text-only return for existing callers by adding a new `plain_call_with_usage` and having `plain_call` call it. Consult's trace records carry the real `cost_usd` (None when unknown) and real tokens when known, falling back to the estimates. Add the consult cost of the turn to the tier's per-turn USD budget accounting if the tool loop exposes a hook for it (P2-41); if not, record that as an open point.
- **Tests:** a fake provider that returns usage gives real tokens and cost on the record; one that does not keeps the estimates and `cost_usd` None.

---

**FU-04 The finding-summary call counts against the curiosity budget**
- **Tier:** bulk
- **Depends on:** B4-03, B4-04
- **Files:** `src/aura/autonomy/findings.py`, `src/aura/autonomy/budget.py` (read), `tests/unit/test_findings_to_agenda.py`
- **Change:** `_draft_finding_summary` estimates tokens (prompt plus reply length / 4) and records them, with cost 0 unless the client reports a cost, through the budget's existing `record_spend`. If the budget is already exhausted, skip the model call and use the fallback (the first three fact lines joined).
- **Tests:** the draft call adds its tokens to today's budget row; an exhausted budget skips the call and the item still gets content.

---

**FU-05 Seed the Council and Diverge skills at startup**
- **Tier:** bulk
- **Depends on:** P2-28, P2-29
- **Files:** `src/aura/main.py` (lifespan), new `src/aura/engines/learning/builtin_skills.py`, new `tests/unit/test_builtin_skills_seed.py`
- **Change:** `builtin_skills.seed_all(store)` calls `aura.tools.council.seed_council_skill(store)` when `settings.council_enabled` is true and `aura.tools.diverge.seed_diverge_skill(store)` when `settings.diverge_enabled` is true; each call in its own `try/except Exception` with a logged warning. In `main.py` lifespan, after the schema scripts are applied and the database is connected, call it once with a `SkillStore()` (import inside the function, wrap in try/except so startup never fails because of it).
- **Tests (EmbeddedSurrealDB, real schema):** both flags on seeds both skills once; running twice keeps one version each; flags off seeds nothing (ablation); a seeding error in one does not stop the other.

---

**FU-06 Chat page shows pushed `chat_message` events live (Afterthought follow-ups)**
- **Tier:** bulk
- **Depends on:** P2-30, B1-04
- **Files:** `frontend/src/pages/chat.tsx` (the `aura_message` handler near line 856), `frontend/src/services/socketService.ts`, a new pure helper `frontend/src/utils/chatMessageEvent.ts` with `frontend/src/utils/chatMessageEvent.test.ts`
- **Change:** the owner channel already handles `aura_message`. Add handling for `chat_message` (pushed by `orchestrator/afterthought.py`): when its `conversation_id` matches the open conversation and its message id is not already shown, append it as an assistant message. The pure helper decides (`shouldAppendChatMessage(event, conversationId, shownIds) -> boolean`) so it can be unit tested; the component only calls it.
- **Tests (vitest):** the helper accepts a matching new message; rejects another conversation; rejects an id already shown; rejects malformed events. The test must import and exercise the real helper.
- **Do not:** change the `/chat/task-reports` polling.
