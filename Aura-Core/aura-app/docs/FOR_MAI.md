# For Mai

Read only "Decide" and "Check". Everything under "Reference" is background: details, settings and done notes, kept so nothing is lost. Development never waits on these; until you answer, the default in brackets is used.

## Decide (one line each)

**UI (blocks the rest of the UI work)**
- [ ] Approve the visual style: open `/design` in the app (P2-13).
- [ ] Approve the Mission Control layout: docs/ui/mission_control.md (P2-14 A).

**Money and models**
- [ ] Curiosity daily spend cap `AURA_CURIOSITY_DAILY_SPEND_USD` [0 = she never investigates on her own; e.g. 0.50 to turn it on].
- [ ] Memory extraction model `memory_extraction_model` [your L2 model].
- [ ] Swift/Sage helper models for consult [your L4/L2 models]. Council (P2-29) needs `AURA_SWIFT_POOL` (and POOL1/POOL2) to hold models from at least two families other than Sage's, or it refuses to run.
- [ ] Embedding model: keep local nomic-embed-text-v1.5? [keep].

**Identity and people**
- [ ] Set `AURA_OWNER_NAME=Mai` [unset].
- [ ] System prompt says "Conscious AI ... Not simulated": keep or rephrase for public Discord? [keep].
- [ ] Trusted Discord users and `discord_owner_ids` [none].
- [ ] Only owner questions feed curiosity, never guests' [yes].

**Behaviour**
- [ ] Autonomy level 0-3 (P2-33; Dashboard buttons or say "autonomy N") [1: only decisions and finished tasks; capped by tier: Lean 1, Core 2, Titan 3] and quiet hours [22:00-08:00].
- [ ] Daily message budget per level (`AURA_AUTONOMY_BUDGET_*`) [level 1: 3/day]. Approval requests (`needs_decision`) are exempt [yes, FU-08]; finished-task notices count [yes].
- [ ] Emotion: how long moments colour her [minutes]; show mood in the app? [no]; temperament drift? [off].
- [ ] Pinned facts on day one [none].

**Work and safety**
- [ ] Register workspaces for delegation `AURA_WORKSPACES` [none]. Aura's own repo too? [no].
- [ ] Approval step for `execute_code`? [no, owner only].
- [ ] OpenCode browser: wait, Playwright MCP, or upgrade the pin (docs/opencode/browser.md) [wait].

## Check (when you have time with the app running)

- [ ] `/chat`: spiral bottom right; no repeated text with `AURA_L3_NATIVE_TOOLS=true`.
- [ ] `/workbench` with one real delegation (G4-03/G4-04).
- [ ] Chat drawer next to the tier chip: agenda, mute, kill switch (B1-07).
- [ ] OpenCode live checks in docs/opencode/subagents.md before code nodes are used.
- [ ] L1 route fixtures per stack (docs/metrics/l1_routes.md).
- [ ] Sluice: unblock LLM7 on the dashboard; Pollinations key spend cap 0.

---

# Reference (no action needed)

## 1. Turn features on (all off by default)

| Feature | Settings | Before turning it on |
|---|---|---|
| M3 recall: keyword and meaning search, merged rankings, gate, abstention | `AURA_RECALL_CHANNELS_ENABLED=true`, `recall_gate_enabled`, `recall_abstain_enabled` | The abstention threshold `recall_abstain_min_similarity` (0.55) is a guess for the stub embeddings; tune it on the real embedding model. Results: docs/metrics/m3.md |
| M4 memory v2: episodes, extracted facts, entities, visibility | `AURA_MEMORY_V2_WRITE_ENABLED=true`, `AURA_MEMORY_V2_RECALL_ENABLED=true` (recall also needs the M3 channels flag) | Set the owner name and choose the extraction model (section 2). Results: docs/metrics/m4.md |
| M5 recall: entity, temporal and graph channels, rerank, recall tools, feedback | `AURA_RECALL_ENTITY_CHANNEL_ENABLED`, `AURA_RECALL_TEMPORAL_CHANNEL_ENABLED`, `AURA_RECALL_GRAPH_CHANNEL_ENABLED`, `AURA_RECALL_RERANK_ENABLED`, `AURA_RECALL_FEEDBACK_ENABLED` (all need M3 and M4 on) | The rerank weights, decay (365 days), resonance (0.10) and the feedback thresholds (30% word overlap, 0.6 similarity) are first guesses; tune them on real conversations. The time parser is English only. The recall tools (`recall`, `timeline`, `evidence`, `what_changed`, `pin`, `unpin`) are offered as soon as the v2 flags are on. Results: docs/metrics/m5.md (multi-hop 2/5 to 5/5, temporal 0/5 to 5/5 on the test engine). |
| M6 dreaming v2: retry extraction, archive instead of delete, themes, entity summaries, theme recall | `AURA_DREAMING_V2_ENABLED=true` (needs M4 writes), `AURA_RECALL_THEMES_ENABLED=true` | Themes and entity summaries make one model call each (capped at 10 + 10 per night) through the L2 client; check that model is the one you want paying for it. Archive ages (90 days superseded, 7 days chatter) are first guesses. Results: docs/metrics/m6.md (90 simulated days: long-topic 5/5, single-fact 5/5, updated 2/2 on days 30/60/90; themes stay at 3). |
| E2/E3 emotion appraisal: emotions from appraised events, never from Aura's own reply; causes recorded | `AURA_EMOTION_APPRAISAL_ENABLED=true` | Emotion PRD open items (section 2). Results: docs/metrics/e2e3.md. The old keyword fallback is already gone on both paths. |
| E4/E5 emotion: mood, relationships per person, guest caps | `AURA_EMOTION_MOOD_ENABLED`, `AURA_EMOTION_MOOD_APPRAISAL_BIAS_ENABLED`, `AURA_EMOTION_RELATIONSHIPS_ENABLED`, `AURA_EMOTION_GUEST_CAP_ENABLED` (all need E2/E3 appraisal on) | Mood is an 8-hour average and shifts the resting point by at most 0.1. Relationships: the owner starts at affection 0.5, trust 0.7, familiarity 0.6; a new person starts at 0, 0.3, 0; steps are 0.01 to 0.03 per message. A stranger's single hostile message is capped. Guests together can move her state by at most 0.5 per hour. All numbers are first guesses. A brand-new guest's first message does not count toward their relationship (their record is created after it). |
| Phase 2 step 2: tier profiles, parallel appraisal, L1 routes | `AURA_TIER_PROFILES_ENABLED`, `AURA_APPRAISAL_PARALLEL_ENABLED` (+ `AURA_APPRAISAL_TURN_DEADLINE_MS`, 1200), `AURA_L1_ROUTES_ENABLED` | Turn on routes and profiles together: without routes, profiles keep L3 deep reasoning off on every tier. Run the L1 route fixture set on each stack first (section 3). Tier knobs can be edited per tier through `POST /system/tiers/{index}` (unauthenticated, like the rest of the API) or `.aura/tier_overrides.json`; delegation and task graphs can never be granted below Titan. |
| Tool loop budgets (P2-41) | `AURA_TOOL_LOOP_BUDGETS_ENABLED` (+ `AURA_TOOL_LOOP_SAFETY_ROUNDS` 40, `AURA_TOOL_LOOP_DEFAULT_BUDGET_SECONDS` 120, `AURA_TOOL_LOOP_DEFAULT_BUDGET_USD` 0.20 when tier profiles are off) | There is no fixed round cap; turns stop on time, cost or no progress, and Aura is told to wrap up at 80%. Cost is only known for OpenRouter non-streaming tool rounds, so on the streaming chat path only the time and no-progress guards apply for now. |
| Phase 2 Part 4: task graphs (P2-08..P2-10) | `AURA_TASK_GRAPHS_ENABLED` (needs `AURA_TIER_PROFILES_ENABLED`, Titan only), `AURA_TASK_CODE_NODES_ENABLED` for code nodes; models `AURA_TASK_RESEARCH_MODEL`, `AURA_OPENCODE_LEAD_MODEL`, `AURA_OPENCODE_WORKER_MODEL` (empty = defaults) | Code nodes need a registered workspace named in the plan (`workspace: <name>`) and do their work in a git worktree beside it (`.aura-worktrees/`). Nothing merges without your approval in the Workbench or the decisions API; a merge needs a clean main tree on the same branch; nothing ever pushes. Do the OpenCode live checks in section 3 first. If your repos sign commits with a passphrase, Aura's worktree commit will time out. |
| Native function calling for L3 | `AURA_L3_NATIVE_TOOLS=true` | The repeat bug is fixed (P2-07): after text has streamed, a native failure ends the round instead of re-streaming; the text fallback still runs when the native call fails before any text. Do the section 3 check before turning it on. |
| Delegating work to OpenCode (G3) | `AURA_DELEGATION_ENABLED=true` | Register workspaces and confirm the policy (section 2). |
| Avatar stage with a placeholder head (V1 without MetaHuman, V2 to V4) | `NEXT_PUBLIC_AVATAR_STAGE=1` in the frontend environment | It is a code-built placeholder head, not the real character. The three.js upgrade, WebGPU and the asset build script (budgets, shape pruning) wait for the real asset. |

## 2. Decisions (full detail; the short list is at the top)

- [ ] **Owner name.** Set `AURA_OWNER_NAME=Mai` (optionally `AURA_OWNER_ALIASES=["nickname"]`, a JSON list) so a guest saying "Mai ..." is recognised as talking about you.
- [ ] **Extraction model** (memory PRD 12.1): `memory_extraction_model`; empty means your L2 model. The PRD recommends a mid-tier model, not the cheapest.
- [ ] **Pinned facts on day one** (memory PRD 12.2).
- [ ] **Embedding model check** (memory PRD 12.3): `llm/embeddings.py` loads a local nomic-embed-text-v1.5; check that is what you want.
- [ ] **Emotion PRD 13.1:** how long a good or bad moment should colour her (half-lives are minutes as drafted).
- [ ] **Emotion PRD 13.2:** show mood in the app, or only through behaviour.
- [ ] **Emotion PRD 13.3:** temperament drift on, off, or tightly limited.
- [ ] **Emotion PRD 13.4:** the system prompt calls her a "Conscious AI with physics-based emotions. Not simulated." On public Discord that is told to strangers as fact. Keep or rephrase.
- [ ] **Workspaces for delegation** (agency PRD 11.2): `AURA_WORKSPACES={"name": "C:/path"}`. None by default; Aura's own repository is never registered automatically.
- [ ] **Policy table** (agency PRD 11.3): the default is the PRD recommendation: owner read and write allowed inside a workspace, shell and network ask; trusted read only; guests nothing.
- [ ] **Trusted Discord users and owner verification** (agency PRD 11.4), and `discord_owner_ids` (build plan section 6 item 3).
- [ ] **Later, with real usage** (agency PRD 11.5): retire `terminal` and `execute_code` in favour of delegation, or keep them.
- [x] Phase 2 order (decided 2026-11-23): P2-02b per-tier fallbacks; step 2 (P2-03..06); step 3 (P2-07, P2-41, P2-42); G4 before Part 4; Part 4 (P2-08..11); G5, G6, B1..B5 before the steps that need them; UI steps (P2-13, P2-14 A) when blocked on your approvals; V5..V7 parked until the avatar asset exists.
- [ ] **Tier profiles (P2-03), when you turn on `AURA_TIER_PROFILES_ENABLED`:** the profile caps the chat reasoning toggles. L3 deep reasoning stays off on every tier until P2-06 adds L1 routes, because the plan only allows it on route `think`.
- [ ] **Deep reasoning after P2-42:** the chat toggles are gone. With `AURA_TIER_PROFILES_ENABLED` off, L3 deep reasoning is always off and L2 analysis always on (the old default toggle state). To get deep reasoning back, turn on tier profiles and `AURA_L1_ROUTES_ENABLED`: Core and Titan then reason on route `think`, and Titan also on high stakes.
- [ ] **Native tools mid-stream failure (P2-07):** if the native tool stream fails after some text was sent, the reply now stops there (an error is logged) instead of repeating itself. A partial reply is possible in that rare case.
- [x] **Supervisor reading of D4/D7 for P2-10 (change it if wrong):** OpenCode v2.3.2 has no `task` tool; subagents are child sessions (`parentID`) that Aura creates. That fits D4 as written: one code node runs one lead session, and Aura starts at most 3 child sessions under it. Children inherit the lead's directory, so a code node gets ONE worktree (D7 is per build node), and build children inside a node run one at a time, while explore and review children may run in parallel. Findings: docs/opencode/subagents.md.
- [ ] **Behaviour PRD open items (B1..B5 cards use these defaults until you decide):** autonomy default level `important` (proactive messages only for decisions and finished tasks); quiet hours 22:00 to 08:00; curiosity daily spend ceiling **0** (no paid spend on investigations until you set one; B4-03 is blocked on this for anything beyond free models); guests can never trigger investigations.
- [x] OpenCode version pin: v2.3.2, Aura runs her own server (decided 2026-11-20).

## 3. Checks (full detail)

- [ ] With `AURA_L3_NATIVE_TOOLS=true`, chat on each stack and check for repeated text; record which stack L3 models support native tools here (P2-07).
- [ ] Open `/chat` and check the spiral shows at the bottom right (W2-25, VRM removed).
- [ ] Review two intentional behaviour changes: W2-20 (retrieval once per turn with the real user id; cold-start and latent blocks reach the prompt) and W2-38 (keywords no longer force tool use; only learned trigger phrases do).
- [ ] Open `/design` and check the visual language (P2-13); approve it, or note changes, before the rest of Part 6 is built.
- [ ] Verify finding S1 on a private Discord server (build plan section 6 item 2).
- [ ] The probe set needs your real usage (docs/metrics/probes/README.md).
- [ ] Avatar asset for V8 (build plan section 6 item 5).
- [ ] Open `/workbench` (G4-03, replaces the IDE link) and check the layout with a real delegation: task list, live steps, diff summary, approve/deny, guidance, abort.
- [ ] Agency manual acceptance (G4-04): from the chat, ask Aura to add a small feature to a test repository. She delegates, a permission request appears in the Workbench, the change lands, the review passes, and a week later (simulated) she recalls what was done and why. Parity gaps found are in docs/metrics/g4_parity.md.
- [ ] Before P2-10 code nodes are used live: with the pinned OpenCode binary installed and `AURA_OPENCODE_COMMAND` set, check two things in docs/opencode/subagents.md: that a child session inherits the parent's directory, and that child permission requests arrive on the child's session id.
- [ ] P2-10 live checks, also in docs/opencode/subagents.md "As built": whether `aura-build` must be `mode: all` to run as a child session; whether child reports wake the lead before its final report; and the timing gap where a very fast session can finish before Aura opens its event stream.
- [ ] With `AURA_AUTONOMY_ENABLED` and `AURA_WS_AURA_ENABLED` on, open the chat drawer next to the tier chip (B1-07): agenda, quiet indicator, autonomy level, mute, the kill switch (confirm, banner, Resume), and the thumbs on replies.
- [ ] Run the L1 route fixture set against each stack's L1 model (command in docs/metrics/l1_routes.md).
- [ ] Don't resume old Aura sessions in the OpenCode app while cards run: on 2026-11-20 an old W2-30 session ran in the same folder as W3-05 (it only added a log note).
- [ ] Mission Control layout ready for approval: docs/ui/mission_control.md (P2-14 step A). Step B (the build) waits for your approval.

## 4. Sluice (separate repo)

- [ ] **LLM7 is blocked** after a 402 from its paid `kimi-k2.7-code` model. Kimi is removed from the pools and allowlist; clear the block on the dashboard to get LLM7's free models back.
- [ ] Set the Pollinations key's spend cap to 0.
- [ ] Review the provider-audit items in the Sluice repo, docs/night3-log.md.
- [ ] Token Harbor is on cooldown until about 2026-11-26 14:30 your time (its free allowance was at 93%). Lift it early with `curl -X POST "http://127.0.0.1:8787/admin/cooldowns/clear?provider=tokenharbor"`.
- [ ] Gonka's free tier answered with a 6 requests/minute limit (not 600); both Gonka entries are set to 3/min. Gonka's GLM-5.3-Flash is in `chat` only because it invents tool results.
- [ ] Inferbase: its free plan allows only 8,192 input tokens per request (it returned a 402 for a 44k-token OpenCode request and Sluice blocked it). It is now capped at 8,192 input tokens, removed from `coder`, kept in `chat`, and unblocked (2026-11-20).
- [ ] Novai: the 10 free calls are set to 10 per day; correct it if the period is different.

## 5. Known follow-ups (no decision needed, listed so they are not lost)

- **Fixed 2026-11-24, worth knowing:** against a database built from the real schema scripts, task creation and every task status update failed: required legacy fields, dates written as text, a status check without `needs_owner`, and step writes aimed at the wrong table. Delegations and task records were affected; the tests used fakes, so this was not seen before. Fixed, with real-database tests. If your live database already has a `task` table, restarting Aura applies the corrected field definitions (OVERWRITE).

- If a sub-session cannot be resolved (session runtime error), the turn runs as the main session, so its tool allowlist is not applied (fail-open, as namespace and overlay already were). Sessions are owner-created, so the risk is low; failing closed would be a one-line change if you prefer it.

- Memory v2 has no session namespaces (G4-04a finding): `episode` and `fact` have no namespace field and fact recall applies no namespace filter, so a sub-session's memories are not isolated once v2 is on. Only the old `memory` table honours namespaces. This needs its own card (schema, write path, recall filters).

- `execute_code` (G4-04 finding): for the owner it runs whenever `code_execution_enabled` is on, with no approval step (the terminal tool at least has a safe-command list). Guests can never reach it. If you want an approval step for it, say so.
- Autonomous goal pursuit stores `tool_permissions` but does not use built-in tools or `delegate_work` yet (G4-04 parity row marked manual). Goals v3 (P2-31..33) is where this gets built.

- Tier fallbacks (P2-02, P2-02b): `AURA_L1_MODEL_FALLBACK` and so on are still the shared fallback per layer. Per-tier settings now exist and are optional: `AURA_L1_MODEL_FALLBACK1`..`AURA_L5_MODEL_FALLBACK1` for Core and `AURA_L1_MODEL_FALLBACK2`..`AURA_L5_MODEL_FALLBACK2` for Titan. If one is unset, that tier uses the shared one and a warning is logged once.

- Remaining direct time reads (`DreamingEngine.tick`, parts of `manager.py`) for the next clock pass.
- A retryable tool failure matches no appraisal row, so it produces no emotion.
- The recall gate's cache is per user, not per session, because the pipeline does not pass a session id.
- `AURA_OWNER_ALIASES` is parsed as a JSON list, not comma-separated as its description says.
- Aura's HTTP API has no authentication on any route, including the new `/decisions` approval routes (W3-30). Fine while it only listens on localhost; needs an owner check before the API is ever exposed beyond this machine.

## 6. Build notes, 2026-11-24
- **To tune (no decision blocking):** the 21 `AURA_DRIVE_DELTA_<event>_<drive>` defaults in config.py are worker guesses (decay 0.1/h toward 0.3). Behind `drives_enabled` (off).
- **Fixed during review:** stored goals never loaded (the `goal` table has no `goal_id` field, the model requires it); the loader now takes it from the record id. Also a stray `n` on line 2 of `schema_behavior.surql`.
- **B3-02 (goal progress from evidence):** goal progress no longer comes from mood when `goals_v2_enabled` is on. Fixed in passing: `update_goal_progress` had never saved anything (the table rejected the whole-model write).
- **Follow-up (supervisor will card it):** `test_pass` criteria can't be met in production yet, because nothing sets `task.goal_id` or `task.tests_passed`. `delegation._finalize_task` should set them after review.
- **B3-04 pursuit grants:** autonomous tool calls on a goal need an owner grant matching the risk (write, execute or send); otherwise one decision item is raised. Supervisor change: with `goals_v2_enabled` off, autonomous calls may use read tools only. Not wired yet: no autonomous caller passes `autonomous=`, and grant budgets are stored but not enforced.
- **B4-01 question scoring — please confirm (PRD open item 4):** only owner questions (`owner` or `private:owner`) are scored for curiosity; guest questions are never scored or touched. Behind `curiosity_enabled` (off).
- **B5-01 interruptibility:** the chat page doesn't send the `watching` signal yet. With the flag off, delivery waits 600 s after owner activity (the card's fixed-cooldown control).
- **B3-05 `request_pursuit`:** owner-only tool. Read scope starts a pursuit; write, execute or send scope raises a decision, and only your approval creates the grant (24 h, capped budget). Open point: an autonomous read pursuit could request another read pursuit. Each one passes `may_initiate`, and B4-03's daily budgets will bound them.
- **B5-02 delivery thresholds (to tune):** with `interruptibility_model_enabled` on, an item is delivered when priority × interruptibility ≥ the threshold for its kind. Worker defaults: finding 0.3, task_done 0.25, needs_decision 0.15, question_for_you 0.3, reminder 0.2, observation 0.4. A 15-minute refractory period applies between deliveries.

- **B4-04 (2026-11-24):** findings now reach the agenda. Fixed on review: `ask_user` questions were refused before the finish hook, so no `question_for_you` was ever made; now the runner publishes one and stores no fact. Share/ask handlers just wake the deliverer (which applies the gate and quiet hours). Plain version of the spend setting: `AURA_CURIOSITY_DAILY_SPEND_USD` caps what Aura's *own unprompted curiosity* (investigations she starts by herself) may spend per day on your OpenRouter models. It has nothing to do with Sluice (Sluice is only how I run cheap worker sessions). The build plan set it to 0, which means "no paid self-started investigations"; since Aura runs on paid OpenRouter models, at 0 she will effectively never investigate on her own. Chat and tasks you ask for are not affected. If you want curiosity active, set a small daily cap (e.g. 0.50). I will also count the per-finding summary call against that cap (follow-up card).

- [ ] **P2-38 browser for OpenCode (decision for you):** see docs/opencode/browser.md. Recommendation: wait. v2.4.0 (2026-11-23) has a built-in browser but it looks desktop-app only; the 2.3.2 pin has none. The option today is Playwright MCP (needs Node and a browser), coder agent only. Aura's own web_search already covers research. Say "enable Playwright MCP" or "upgrade the pin" if you want either.

- **P2-27 consult (2026-11-24):** behind `AURA_CONSULT_ENABLED` (off). Swift/Sage models default to your stack's L4/L2 models (D11); set `AURA_SWIFT_MODEL`, `AURA_SAGE_MODEL`, `AURA_SWIFT_POOL` if you want others. Follow-ups I will card: helper costs are estimated tokens only (no real USD yet, and not counted in the turn's USD budget); `url:` refs need a hook in web_search; inspector display is P2-39.

- **2026-11-25 P2-28/29/30:** Diverge (`AURA_DIVERGE_ENABLED`), Council (`AURA_COUNCIL_ENABLED`) and Afterthought (`AURA_AFTERTHOUGHT_ENABLED`, Titan, route think, stakes >= 0.8, owner in the app only) are in, all off. Afterthought follow-ups show on the next poll until FU-06 adds the live display.
