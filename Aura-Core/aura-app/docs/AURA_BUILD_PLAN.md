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
  1. Setup: from `frontend/`, run `npm ci` first. `node_modules` is not installed in this checkout. Then run `npm run build` once **before** any change, and record whether it passes. If it fails before the change, stop and report the errors. Do not fix unrelated build errors.
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
