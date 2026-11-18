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
