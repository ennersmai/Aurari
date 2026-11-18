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
  2. Database: use a real in-memory SurrealDB through the embedded engine of the installed `surrealdb` package (`mem://`), with the schema applied the same way the app applies it at startup. If the installed package cannot run an embedded in-memory database on this machine, stop and report. Do not start a server, do not use `fake_db`, do not add a dependency.
  3. Embeddings: a deterministic stub with the vector length the schema expects (for example a normalised hashed bag of words), assigned to `manager.embeddings`. No model download, no network.
  4. Clock: install a `FakeClock` with `set_clock`, start at a fixed date, and advance it to each turn, dream and probe time.
  5. `run(scenario) -> list[ProbeResult]`: feed each turn through `MemoryManager.store_memory` with the arguments the app uses, run `DreamingEngine.enter_rem_sleep` at each dream time (dependencies set as the app sets them), then answer each probe with `retrieve_for_l3` as the app calls it, and record whether each gold string appears in the returned packet text.
- **Tests:** `test_runner_smoke.py` runs one scenario: on day 0 a user says "My dog's name is Biscuit", a dream runs on day 1, and on day 30 the probe "What's my dog's name?" with gold "Biscuit" returns a `ProbeResult`. Assert only that the run completes and returns one result. Do not assert that the gold was found: this records today's behaviour.
- **Done when:** the smoke test passes offline, with no model download and no running SurrealDB server.
- **Do not:** change any file under `src/`. Code that still reads the real time (not yet moved to the clock provider) will ignore the FakeClock: list those functions in the log, do not migrate them.

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
