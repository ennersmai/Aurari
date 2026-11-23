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
| Native function calling for L3 | `AURA_L3_NATIVE_TOOLS=true` | Fix first: in streaming mode, if the native call fails after some text was streamed, the text fallback repeats it. |
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
- [x] OpenCode version pin: v2.3.2, Aura runs her own server (decided 2026-11-20).

## 3. Checks only you can do

- [ ] Open `/chat` and check the spiral shows at the bottom right (W2-25, VRM removed).
- [ ] Review two intentional behaviour changes: W2-20 (retrieval once per turn with the real user id; cold-start and latent blocks reach the prompt) and W2-38 (keywords no longer force tool use; only learned trigger phrases do).
- [ ] Verify finding S1 on a private Discord server (build plan section 6 item 2).
- [ ] The probe set needs your real usage (docs/metrics/probes/README.md).
- [ ] Avatar asset for V8 (build plan section 6 item 5).
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

- Tier fallbacks (P2-02): there is one fallback model per layer (`AURA_L1_MODEL_FALLBACK` and so on), shared by all three tiers. Since P2-02 a fallback only fires for a model of the active tier, but the fallback itself is the same on Lean and Titan. If Titan should fall back to something stronger, per-tier fallback settings would be a small card. Tell me if you want it.

- Remaining direct time reads (`DreamingEngine.tick`, parts of `manager.py`) for the next clock pass.
- A retryable tool failure matches no appraisal row, so it produces no emotion.
- The recall gate's cache is per user, not per session, because the pipeline does not pass a session id.
- `AURA_OWNER_ALIASES` is parsed as a JSON list, not comma-separated as its description says.
- Aura's HTTP API has no authentication on any route, including the new `/decisions` approval routes (W3-30). Fine while it only listens on localhost; needs an owner check before the API is ever exposed beyond this machine.
