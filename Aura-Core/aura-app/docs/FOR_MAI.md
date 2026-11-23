# For Mai: decisions, settings and checks waiting for you

Kept current by the supervisor. Everything that needs you goes here instead of the chat. Tick items off or leave notes inline; we go through it together at the end of the work.

Settings go in Aura's `.env` unless noted.

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

## 2. Decisions

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
- [x] OpenCode version pin: v2.3.2, Aura runs her own server (decided 2026-11-20).

## 3. Checks only you can do

- [ ] With `AURA_L3_NATIVE_TOOLS=true`, chat on each stack and check for repeated text; record which stack L3 models support native tools here (P2-07).
- [ ] Open `/chat` and check the spiral shows at the bottom right (W2-25, VRM removed).
- [ ] Review two intentional behaviour changes: W2-20 (retrieval once per turn with the real user id; cold-start and latent blocks reach the prompt) and W2-38 (keywords no longer force tool use; only learned trigger phrases do).
- [ ] Verify finding S1 on a private Discord server (build plan section 6 item 2).
- [ ] The probe set needs your real usage (docs/metrics/probes/README.md).
- [ ] Avatar asset for V8 (build plan section 6 item 5).
- [ ] Open `/workbench` (G4-03, replaces the IDE link) and check the layout with a real delegation: task list, live steps, diff summary, approve/deny, guidance, abort.
- [ ] Agency manual acceptance (G4-04): from the chat, ask Aura to add a small feature to a test repository. She delegates, a permission request appears in the Workbench, the change lands, the review passes, and a week later (simulated) she recalls what was done and why. Parity gaps found are in docs/metrics/g4_parity.md.
- [ ] Before P2-10 code nodes are used live: with the pinned OpenCode binary installed and `AURA_OPENCODE_COMMAND` set, check two things in docs/opencode/subagents.md: that a child session inherits the parent's directory, and that child permission requests arrive on the child's session id.
- [ ] P2-10 live checks, also in docs/opencode/subagents.md "As built": whether `aura-build` must be `mode: all` to run as a child session; whether child reports wake the lead before its final report; and the timing gap where a very fast session can finish before Aura opens its event stream.
- [ ] Run the L1 route fixture set against each stack's L1 model (command in docs/metrics/l1_routes.md).
- [ ] Don't resume old Aura sessions in the OpenCode app while cards run: on 2026-11-20 an old W2-30 session ran in the same folder as W3-05 (it only added a log note).

## 4. Sluice (separate repo)

- [ ] **LLM7 is blocked** after a 402 from its paid `kimi-k2.7-code` model. Kimi is removed from the pools and allowlist; clear the block on the dashboard to get LLM7's free models back.
- [ ] Set the Pollinations key's spend cap to 0.
- [ ] Review the provider-audit items in the Sluice repo, docs/night3-log.md.
- [ ] Token Harbor is on cooldown until about 2026-11-26 14:30 your time (its free allowance was at 93%). Lift it early with `curl -X POST "http://127.0.0.1:8787/admin/cooldowns/clear?provider=tokenharbor"`.
- [ ] Gonka's free tier answered with a 6 requests/minute limit (not 600); both Gonka entries are set to 3/min. Gonka's GLM-5.3-Flash is in `chat` only because it invents tool results.
- [ ] Inferbase: its free plan allows only 8,192 input tokens per request (it returned a 402 for a 44k-token OpenCode request and Sluice blocked it). It is now capped at 8,192 input tokens, removed from `coder`, kept in `chat`, and unblocked (2026-11-20).
- [ ] Novai: the 10 free calls are set to 10 per day; correct it if the period is different.

## 5. Known follow-ups (no decision needed, listed so they are not lost)

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
