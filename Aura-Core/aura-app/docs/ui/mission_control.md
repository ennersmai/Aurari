# Mission Control: inventory and proposed Dashboard layout (P2-14 step A)

Status: proposal for Mai's approval. No code was changed. Step B (the build) starts only after approval.
Sources: `frontend/src/pages/mission-control.tsx` (842 lines) and every component, hook and service it uses, checked against `src/aura/api/routes/*` and `src/aura/main.py`. "Works" is a judgement from the code; nothing was run, so anything that depends on a live service says so.

Findings that shape the layout:

- The page is a legacy second chat (its own `/chat/stream` call and TTS) glued to a pile of collapsed settings panels. The chat duplicates `/chat`.
- The page's tier selector and local toggle POST the whole inference config to `/system/inference-config`. The navbar in chat uses `POST /system/model-stack`. Both set `model_stack_index`; the Dashboard should use the navbar's call plus `/system/tiers`.
- AIProviderPanel's per-layer model switch (`POST /local-ai/layer/config`) writes `settings.l1_model` etc. (the Lean stack fields). The active model is read from `l1_model1` / `l1_model2` on Core and Titan (`config.model_for`), so on those tiers the switch changes nothing while the panel shows success.
- CognitiveStatus is fed by a local `status.cognitive` object that only this page's own send handler changes (layer L1/L3, hard-coded model `mistralai/mistral-7b-instruct`). It never receives real turn data. It is a mock.
- The header shows a hard-coded identity string and `v0.3.0`. The INT counter counts only messages sent from this page.
- The Logs tab reads `EventSource http://localhost:9876/logs/stream`. That server is in the launcher (`aura-launcher/src-tauri/src/log_server.rs`), not in aura-app. It works inside the launcher and shows nothing in a plain browser.
- Small dead code or races: `CulturalPanel.resonanceScore` is never set; `useInferenceConfig` starts from `DEFAULT_INFERENCE_CONFIG`, so a toggle clicked before the first fetch completes would POST defaults.
- Other pages link to `/mission-control` (chat TierChip and a nav button, school, workbench). Step B keeps that URL and adds `/dashboard`.

## 1. Inventory

Legend for "Works": yes = route exists and the fields match what the component reads; partial = works with a caveat; no = broken or mock; live = cannot tell from code, needs a live check.

### 1a. Header and global controls

| # | Item | Shows / does | API (method path) | Route exists | Works | Needed |
|---|---|---|---|---|---|---|
| H1 | Back arrow, CHAT button | Navigate to /chat | none | n/a | yes | duplicate (navbar) |
| H2 | Title, "v0.3.0", identity line | Static text | none | n/a | no (hard-coded) | remove; Overview shows real state |
| H3 | Workbench button | Navigate to /workbench | none | n/a | yes | duplicate (navbar, Workbench) |
| H4 | Tier selector LEAN/CORE/TITAN | Active stack; click switches | POST `/system/inference-config` (full config); initial GET `/system/inference-config` and `/system/model-stack` | yes | yes | duplicate of the navbar selector; replaced by tier cards (P2-14b) |
| H5 | LOCAL / SGLANG toggle | Flips `local_mode_enabled` | POST `/system/inference-config` | yes | yes (runtime only, lost on restart) | keep, in Connections |
| H6 | Voice on/off icon | Local state; enables TTS for this page's chat | none | n/a | yes | remove with the page chat |
| H7 | TTS provider button and voice menu | Edge / Qwen3 / Fish tabs, 9 Edge voices, 9 Qwen speakers, instruct text, temperature / top-p / top-k sliders, APPLY CONFIG | POST `/voice/config`; `/voice/stream` per sentence | yes (`voice.py`) | partial: Edge works; Qwen3 and Fish need local servers (live); the choice is local state, not shared with /chat | keep generation config (Connections > Voice); picker only if /chat shares it (question 4) |
| H8 | SYS ONLINE dot | Backend reachable | GET `/health` (30 s) and emotion WebSocket state | yes (503 when DB down) | yes | keep, Overview |
| H9 | DB dot | `database == "connected"` | GET `/health` | yes | yes | keep, Overview |
| H10 | INT counter | Messages sent from this page | none | n/a | no (misleading) | remove |

### 1b. Collapsed panel stack

| # | Panel | Shows | API | Route exists | Works | Needed |
|---|---|---|---|---|---|---|
| P1 | InferenceCockpit | Stack selector, local/SGLang toggles, active model per layer, sliders (temperature, top-p, min-p, frequency and presence penalty, max tokens, context length 8k-128k with a "3090 VRAM risk" bar), L1-L5 enable toggles | GET/POST `/system/inference-config`, GET `/system/model-stack` | yes | yes. The risk bar is a frontend formula on context length only. Settings are runtime only. | partly duplicate: stack selector and active models duplicate the navbar and tier cards. Keep sampling, context and layer toggles under Tiers > Inference. Layer toggles overlap tier knobs (question 2). |
| P2 | SettingsPanel | Commander identity, memory depth slider (5-100), reset | none (localStorage via SettingsContext) | n/a | yes | keep, System > Preferences |
| P3 | AIProviderPanel | Ollama up/down and URL, local model list with sizes, Pull model, Qwen3-TTS and FishAudio availability, per-layer cloud/local model switch | GET `/local-ai/status`, POST `/local-ai/ollama/pull`, POST `/local-ai/layer/config` | yes (`local_ai.py`) | status and pull: yes. Layer switch: no on Core and Titan. | keep status, models, pull in Connections; remove layer switch |
| P4 | VoiceClonePanel | Reference audio upload, test text, instruct, speaker, language; plays a generated clip | POST `/voice/clone` | yes | yes if the Qwen3 server runs (live) | keep, Connections > Voice (collapsed lab) |
| P5 | CulturalPanel | Cultural node list (style, collective weight, restraint bias, principles), active node, last routing decision, switch node | GET `/cultural/nodes`, GET `/cultural/active`, POST `/cultural/route` | yes (`cultural.py`) | yes by field match; live check for a populated node set | keep, Mind > Culture |
| P6 | MemoryIntrospectionPanel | Health gauge, totals (memories, core, pending pruning, abstractions, insights, graph edges), strongest and most emotional memory, domains, last dream, "Trigger dream" with report | GET `/memory/introspect/default`, POST `/memory/dream` | yes (`memory.py`) | yes (fields match `MemoryIntrospection`); hard-codes user `default`; dream returns 503 if the engine is down (shown as error) | keep, Mind > Memory and Dreaming; depth to Inspector P2-16 |

### 1c. Main grid

| # | Panel | Shows | API | Route exists | Works | Needed |
|---|---|---|---|---|---|---|
| G1a | NeuralSidebar > EMOTION | Radar of the emotion vector plus physics values | GET `/emotion/current`; WebSocket `/ws/emotion` (heartbeat 25 s, reconnect 5 s) | yes | yes (initial state is a hard-coded fake until the first fetch) | keep, Mind > Emotion; depth to Inspector P2-17 |
| G1b | NeuralSidebar > CORTEX | Learned insights (type, content, confidence, use count, domain), refresh 30 s, delete | GET `/learning/insights?limit=50`, DELETE `/learning/insights/{id}` | yes (fields match) | yes (`confidence_min` defaults to 0.5, so weak insights are hidden) | keep count in Mind > Learning; list and delete to Inspector P2-17 (drawer until then) |
| G1c | NeuralSidebar > EPISODIC | 10 most recent memories (importance, emotion, time); refresh 120 s and after each send | GET `/memory/recent?limit=10&user_id=` | yes | yes | duplicates the planned Inspector memory view (P2-16); Mind keeps the latest 3 |
| G1d | NeuralSidebar > LOGS (SystemConsole) | Streaming log lines, pause, last 2000 | EventSource `localhost:9876/logs/stream` | not in aura-app (launcher) | live: launcher only | keep, System > Logs |
| G2 | CognitiveStatus | L1/L2/L3/Dream lights, model, status, latency, tokens, confidence | none (local mock state) | n/a | no (mock) | remove; Inspector turn view (P2-15) replaces it |
| G3 | Goal engine | Active count; per goal name, priority, description, progress, type, reasoning; delete; "+ GENERATE GOAL" | GET `/goal/active` (60 s), DELETE `/goal/{id}`, POST `/goal/generate` | yes (`goal.py`) | yes (generate gives no feedback on failure: `generateGoal` returns null) | keep, Mind > Goals; full list to Inspector P2-17 later |
| G4a | Chat messages | Local chat log with layer tags | `/chat/stream` (fallback `/chat/message`), then GET `/emotion/current` | yes | yes, but separate from real conversations (not in `/api/conversations`) | remove (duplicates /chat) |
| G4b | Chat input and send | Sends with identity and context window; TTS per sentence | POST `/chat/stream`, POST `/voice/stream` | yes | yes | remove (duplicates /chat) |
| G4c | Footer: layer, model, last latency | From the mock cognitive state | none | n/a | no | remove |
| G5 | Expand/minimize (cognitive, goals) | Full-screen overlay | none | n/a | yes | remove |

Tally: 14 panels (voice menu, P1-P6, G1a-d, G2, G3, G4 chat) plus 10 header and global controls. Works: 10 (P1, P2, P4, P5, P6, G1a, G1b, G1c, G3, G4; P4, P5 and the Qwen/Fish parts need live checks). Partial: 3 (voice menu, P3 with its broken layer switch, G1d logs, launcher only). Mock: 1 (G2). Duplicate something: 4 panels (G4 duplicates /chat; P1's stack part duplicates the navbar; G1c and G2 duplicate the planned Inspector) and 4 controls (H1, H3, H4, H6).

## 2. Proposed information architecture

Five sections as the plan proposes, shown as tabs (one section on screen at a time). Style per 6.1: `.aura-page` scope, GlassCard for panels, StatTile for numbers (with Sparkline where history exists), GlowLine for trends, Legend for multi-series, subsystem accents (memory cyan, emotion rose, goals amber, tools violet, learning green, decisions blue). 1280 px window, no horizontal scroll: content max width 1180 px, 12-column grid, 3 to 4 tiles per row. Deep-linkable as `/dashboard?section=tiers`; `/mission-control` renders the same page.

Data source key: "API" exists today. "needs backend" does not exist; P2-14 adds no backend, so the tile shows "not available yet" and the entry is a later card.

### 2.1 Overview

Purpose: Aura's state in one glance. Only editable thing is the tier shortcut.

| Content | Data source |
|---|---|
| Online and DB dots | API: GET `/health` |
| Active tier and its models | API: GET `/system/tiers` (`active_index`, `tiers[].models`) |
| System state (ACTIVE / SLEEPING / DREAMING), uptime | API: GET `/system/state` (`state`, `session_started_at`, `last_user_interaction`) |
| Mood sentence (dominant emotion, valence, arousal) | API: GET `/emotion/current` and WebSocket `/ws/emotion`; sentence composed in the page from `dominant` and `valence` (no LLM) |
| Counts: memories, goals, insights | API: GET `/memory/introspect/default` (`total_memories`, `insights_count`), GET `/goal/active` |
| Current task graphs | needs backend: global task graph list (today `/chat/task-reports` is per conversation) |
| Today's cost | needs backend: cost per day from traces |
| Last error | needs backend: error ring buffer endpoint |

```
+------------------------------------------------------------------------------------------+
| AURA DASHBOARD   [Overview] Tiers  Mind  Connections  System            * online  * db ok |
+------------------------------------------------------------------------------------------+
| +---------------------------+  +------------------------------------------------------+ |
| | STATE                     |  |  "Curious and a little warm. Interested, calm."      | |
| | ACTIVE   up 3h 12m        |  |  valence +0.31    arousal 0.42        [emotion rose] | |
| | Tier: [Lean][CORE][Titan] |  |  ~~~~~~ GlowLine: valence, last 30 min ~~~~~~~~~~~~  | |
| +---------------------------+  +------------------------------------------------------+ |
| +--------------+ +--------------+ +--------------+ +--------------+                      |
| | Task graphs  | | Cost today   | | Memories     | | Goals        |                      |
| | not yet (-)  | | not yet (-)  | | 1,284        | | 3 active     |                      |
| +--------------+ +--------------+ +--------------+ +--------------+                      |
| +--------------------------------------------------------------------------------------+ |
| | Last error:  not available yet                                                        | |
| +--------------------------------------------------------------------------------------+ |
+------------------------------------------------------------------------------------------+
```

The tier shortcut calls the navbar's `POST /system/model-stack`.

### 2.2 Tiers (P2-14b)

Purpose: choose a tier, tune its knobs, see what the next turn uses.

| Content | Data source |
|---|---|
| Three tier cards (Lean, Core, Titan): models per layer L1-L5, compact capability summary, active marker, click to activate | API: GET `/system/tiers`; activate with POST `/system/model-stack` |
| Tier editor for the selected tier: every 3.1 knob as slider, toggle or select, default tick, per-knob reset, reset tier | API: POST `/system/tiers/{index}` (partial profile), POST `/system/tiers/{index}/reset` |
| Effective config (read-only): what the next turn uses | API: GET `/system/tiers` (merged profile). Context-budget split of the last turn (P2-40) and turn budget actuals (P2-41): needs backend |
| Global inference settings: temperature, top-p, min-p, penalties, max tokens, context length with VRAM bar, L1-L5 toggles (moved from InferenceCockpit) | API: GET/POST `/system/inference-config` |
| Cost today and this week by tier and by layer | needs backend: cost from traces |

Editor groups (knob names from 3.1): Reasoning (`l3_reasoning`, `l3_stakes_threshold`, `l2_post_analysis`, `afterthought`); Budgets (`turn_budget_seconds`, `turn_budget_usd`, `context_budget_tokens`, `history_floor_exchanges`); Tools (`tools_offered_max`, `full_tools_max`, `stub_tools_max`, `consult_swift_per_turn`, `consult_sage_per_turn`); Delegation and tasks (`allow_delegate`, `allow_task_graph`, `task_graph_max_nodes`, `task_budget_usd`, `task_budget_minutes`); Autonomy (`autonomy_max_level`). Defaults for the tick marks come from the per-tier defaults in the `/system/tiers` payload (`profile` merged vs `overrides`), so the page needs no frontend table beyond knob ranges.

```
+------------------------------------------------------------------------------------------+
|  Overview [Tiers] Mind  Connections  System                                              |
+------------------------------------------------------------------------------------------+
| +--------------+ +==============+ +--------------+                                       |
| | LEAN         | | CORE  active | | TITAN        |    models per layer on each card     |
| | L1 .. L5     | | L1 .. L5     | | L1 .. L5     |    tools 3/6/10, $0.03/0.20/1.00     |
| | no tasks     | | no tasks     | | tasks+delegate                                     |
| +--------------+ +==============+ +--------------+                                       |
| +-----------------------------------------+ +------------------------------------------+ |
| | Editor: CORE            [Reset tier]    | | Effective config (next turn)             | |
| | Reasoning                               | | L3 reasoning: think only                 | |
| |  l3_reasoning   (think)         [r]     | | turn budget: 120 s / $0.20               | |
| |  l2_post_analysis (on)   [x]    [r]     | | tools offered: 6   context: 10000 tok    | |
| | Budgets                                 | | overrides: 2 knobs changed               | |
| |  turn_budget_s |---*---:---|  120  [r]  | | context split, last turn: not yet (-)    | |
| |  ...   (: default tick, [r] reset knob) | +------------------------------------------+ |
| +-----------------------------------------+ | Inference: temp 0.7, ctx 32k, VRAM ok     | |
| | Cost today / week by tier: not yet (-)  | | layers L1[x] L2[x] L3[x] L4[x] L5[x]      | |
| +-----------------------------------------+ +------------------------------------------+ |
+------------------------------------------------------------------------------------------+
```

Per-knob reset: `POST /system/tiers/{index}` merges the patch into the overrides and cannot drop a single key (`set_tier` in `tiers.py`). Step B resets a knob by posting its default value; "Reset tier" uses the reset route. If Mai wants an override removed completely per knob, that is a small backend change (a later card).

### 2.3 Mind

Purpose: one glass card per engine with its key number, a few lines of state, and a link into the Inspector.

| Card (accent) | Key number and content | Data source | Inspector link |
|---|---|---|---|
| Emotion (rose) | dominant emotion, valence, arousal; the existing EmotionRadar | API: `/emotion/current`, WebSocket `/ws/emotion` | P2-17 |
| Memory (cyan) | health score, total and core memories, pending pruning, latest 3 memories | API: `/memory/introspect/default`, `/memory/recent?limit=3` | P2-16 |
| Goals (amber) | active count, top goal with progress; generate and delete stay here until P2-17 | API: `/goal/active`, POST `/goal/generate`, DELETE `/goal/{id}` | P2-17 |
| Dreaming (cyan) | last dream time, "Trigger dream", last report numbers | API: `/memory/introspect/default` (`last_dream_cycle`), POST `/memory/dream` | P2-16 |
| Learning (green) | insight count, newest 3; list with delete in a drawer until P2-17 | API: `/learning/insights`, DELETE `/learning/insights/{id}` | P2-17 |
| Culture (blue) | active node, how it was chosen, switch node | API: `/cultural/nodes`, `/cultural/active`, POST `/cultural/route` | none |
| Striatum (violet) | key number | needs backend: a Striatum summary endpoint (P2-39); shows "not available yet" | P2-39 |

```
+------------------------------------------------------------------------------------------+
|  Overview  Tiers [Mind] Connections  System                                              |
+------------------------------------------------------------------------------------------+
| +----------------------+ +----------------------+ +----------------------+              |
| | EMOTION       rose   | | MEMORY        cyan   | | GOALS         amber  |              |
| |  curiosity           | |  health 82    1,284  | |  3 active            |              |
| |  [radar]             | |  core 41  prune 12   | |  Learn Rust   40%    |              |
| |  valence +0.31       | |  latest: "..."       | |  [generate]          |              |
| |            Inspect > | |            Inspect > | |            Inspect > |              |
| +----------------------+ +----------------------+ +----------------------+              |
| +----------------------+ +----------------------+ +----------------------+              |
| | DREAMING      cyan   | | LEARNING      green  | | CULTURE       blue   |              |
| |  last: 6h ago        | |  57 insights         | |  default node        |              |
| |  [Trigger dream]     | |  newest: PREFERENCE  | |  chosen: language    |              |
| |            Inspect > | |            Inspect > | |  [switch node v]     |              |
| +----------------------+ +----------------------+ +----------------------+              |
| +----------------------+                                                                 |
| | STRIATUM      violet |   not available yet (-)                                         |
| +----------------------+                                                                 |
+------------------------------------------------------------------------------------------+
```

### 2.4 Connections

Purpose: is everything Aura talks to up, with a health dot each.

| Content | Data source |
|---|---|
| Cloud provider reachability | needs backend: a provider health probe |
| Local inference: Ollama up/down, URL, local models with sizes, Pull model, LOCAL/SGLANG toggle | API: GET `/local-ai/status`, POST `/local-ai/ollama/pull`, POST `/system/inference-config` (`local_mode_enabled`, `sglang_enabled`) |
| OpenCode: running or not, URL, delegations count | API: GET `/delegations/opencode-url`, GET `/delegations` (link to Workbench) |
| MCP servers | needs backend: no MCP status endpoint exists |
| Discord: bot status, bot user, guilds, enabled flag; link to the Discord page | API: GET `/discord/status` |
| Voice: Edge/Qwen3/Fish availability, TTS config (temperature, top-p, top-k, Apply), clone lab | API: `/local-ai/status` (`qwen3_tts_available`, `fishaudio_available`), GET and POST `/voice/config`, POST `/voice/clone` |

```
+------------------------------------------------------------------------------------------+
|  Overview  Tiers  Mind [Connections] System                                              |
+------------------------------------------------------------------------------------------+
| +--------------------------------+ +---------------------------------------------------+ |
| | o Cloud providers  not yet (-) | | * Local inference (Ollama)  up  [LOCAL] [SGLANG]  | |
| +--------------------------------+ |   llama3.2 2.0GB   qwen2.5:14b 9.0GB   [Pull ..]  | |
| | * OpenCode  running            | +---------------------------------------------------+ |
| |   http://127.0.0.1:4096  1 task| | * Voice   Edge ok   Qwen3 down   Fish down        | |
| |                    Workbench > | |   temp |--*--| 0.9   top-p |---*| 1.0   [Apply]   | |
| +--------------------------------+ |   [ Clone lab v ]                                 | |
| | o MCP servers      not yet (-) | +---------------------------------------------------+ |
| +--------------------------------+                                                       |
| | * Discord  connected  2 guilds |                                                       |
| |                   Discord page >|                                                      |
| +--------------------------------+                                                       |
+------------------------------------------------------------------------------------------+
```

### 2.5 System

Purpose: housekeeping and diagnostics.

| Content | Data source |
|---|---|
| Feature flags: read-only list with on/off | needs backend: an endpoint listing the `*_enabled` settings (none exists; `/system/inference-config` covers only layer and local flags) |
| Logs | EventSource `http://localhost:9876/logs/stream` (launcher log server); shows "launcher only" when it does not connect |
| State, Sleep, Wake, Restart (with confirm) | API: GET `/system/state`, POST `/system/state/sleep`, POST `/system/state/wake`, POST `/system/restart` |
| Browser preferences: commander identity, memory depth | localStorage (SettingsContext), no API |

```
+------------------------------------------------------------------------------------------+
|  Overview  Tiers  Mind  Connections [System]                                             |
+------------------------------------------------------------------------------------------+
| +------------------------------------+ +-----------------------------------------------+ |
| | Feature flags (read only)          | | State  ACTIVE   [Sleep] [Wake]  [Restart ...] | |
| |  not available yet (-)             | +-----------------------------------------------+ |
| +------------------------------------+ | Preferences (this browser)                    | |
| | Logs                      [pause]  | |  Identity [Mai         ]   Memory depth 20    | |
| |  12:01:03 INFO coordinator ...     | +-----------------------------------------------+ |
| |  12:01:04 INFO tool_loop ...       |                                                   |
| +------------------------------------+                                                   |
+------------------------------------------------------------------------------------------+
```

## 3. Move, merge, remove

| Current panel / control | Destination | Reason |
|---|---|---|
| H1 back arrow, CHAT; H3 Workbench button | removed | the app navbar already links to chat and Workbench |
| H2 title, version, identity line | removed | hard-coded strings; Overview shows live state |
| H4 tier selector | merged into Tiers cards and the Overview shortcut | duplicates the navbar selector; one API |
| H5 LOCAL/SGLANG | Connections (local inference) | provider setting |
| H6 voice toggle, H7 voice menu | Connections > Voice (config and availability); picker only if /chat shares it | per-sentence playback goes with the removed page chat |
| H8, H9 SYS and DB dots | Overview | state at a glance |
| H10 INT counter | removed | counts only this page's messages |
| P1 InferenceCockpit | split: stack and models into Tiers cards; sampling, context, layer toggles into Tiers > Inference; local toggles into Connections | stack part duplicates the navbar; the rest works |
| P2 SettingsPanel | System > Preferences | browser-local settings |
| P3 AIProviderPanel | Connections (status, models, pull); layer switch removed | switch is a no-op on Core and Titan; models per layer belongs in a stack-aware tier editor later |
| P4 VoiceClonePanel | Connections > Voice (collapsed lab) | works, rarely used |
| P5 CulturalPanel | Mind > Culture | not an Inspector topic |
| P6 MemoryIntrospectionPanel | Mind > Memory and Dreaming; depth to Inspector P2-16 | key numbers here, depth there |
| G1a Emotion tab | Mind > Emotion; depth to Inspector P2-17 | |
| G1b Cortex tab | Mind > Learning (drawer); list to Inspector P2-17 | nothing that works is lost before the Inspector exists |
| G1c Episodic tab | Inspector P2-16; Mind keeps latest 3 | duplicates the planned memory view |
| G1d Logs tab | System > Logs | diagnostics |
| G2 CognitiveStatus | removed (Inspector P2-15) | mock, never shows real turns |
| G3 Goal engine | Mind > Goals; full list to Inspector P2-17 | works, no loss |
| G4 Chat (messages, input, footer) | removed | duplicates /chat; turns never reach real conversations |
| G5 Expand/minimize | removed | sections replace overlays |
| Inline glows and CSS | replaced by `.aura-page` and the P2-13 tokens | 6.1 visual language |

## 4. Open questions for Mai

1. Remove the page's own chat and its per-sentence voice playback? It duplicates /chat and its turns never appear in your conversations. Proposed: yes.
2. The InferenceCockpit layer toggles (L1-L5 on/off) overlap the tier knobs (`l2_post_analysis`, `l3_reasoning`). Keep them as global switches under Tiers > Inference, or drop them once the tier editor exists? Proposed: keep for now.
3. The per-layer model switch does nothing on Core and Titan. Remove it now (proposed) and give models-per-layer a stack-aware editor in a later card, or fix the backend inside P2-14 (a backend change outside this card)?
4. Does /chat have its own TTS provider and voice picker? Mission Control and /chat each hold their own state today. Proposed: Connections > Voice shows only availability and generation config; the picker lives in /chat.
5. Several tiles have no data yet (task graphs, today's cost, last error, MCP servers, provider health, feature flags, Striatum). Show them greyed with "not available yet" now (proposed), or hide them until the backend cards land?

## 5. APIs the new page will call

Called by the old page and still called by the new page:

| API | New home |
|---|---|
| GET `/health` | Overview |
| GET `/emotion/current` | Overview, Mind |
| WebSocket `/ws/emotion` | Overview, Mind |
| GET `/goal/active` | Overview, Mind |
| POST `/goal/generate` | Mind > Goals |
| DELETE `/goal/{goal_id}` | Mind > Goals |
| GET `/memory/recent` | Mind > Memory (limit 3) |
| GET `/memory/introspect/default` | Overview, Mind |
| POST `/memory/dream` | Mind > Dreaming |
| GET `/learning/insights` | Mind > Learning |
| DELETE `/learning/insights/{insight_id}` | Mind > Learning drawer |
| GET `/cultural/nodes` | Mind > Culture |
| GET `/cultural/active` | Mind > Culture |
| POST `/cultural/route` | Mind > Culture |
| GET `/system/inference-config` | Tiers > Inference, Connections |
| POST `/system/inference-config` | Tiers > Inference, Connections |
| GET `/system/model-stack` | Tiers, Overview |
| GET `/local-ai/status` | Connections |
| POST `/local-ai/ollama/pull` | Connections |
| POST `/voice/config` | Connections > Voice |
| POST `/voice/clone` | Connections > Voice |
| EventSource `http://localhost:9876/logs/stream` (launcher) | System > Logs |

Listed as removed (P2-14 B's test accepts these as no longer called):

| API | Reason |
|---|---|
| POST `/chat/stream` | page chat removed, duplicates /chat |
| POST `/chat/message` | fallback of the removed chat |
| POST `/voice/stream` | per-sentence playback went with the page chat |
| POST `/local-ai/layer/config` | per-layer switch removed (no-op on Core and Titan) |

New calls (all exist today):

| API | Use |
|---|---|
| GET `/system/tiers` | Tier cards, editor, effective config, Overview tier |
| POST `/system/tiers/{index}` | Tier editor knob changes |
| POST `/system/tiers/{index}/reset` | Reset tier |
| POST `/system/model-stack` | Activate a tier (same as the navbar) |
| GET `/system/state` | Overview state and uptime; System |
| POST `/system/state/sleep`, POST `/system/state/wake`, POST `/system/restart` | System actions |
| GET `/voice/config` | Connections > Voice initial values |
| GET `/discord/status` | Connections |
| GET `/delegations/opencode-url`, GET `/delegations` | Connections (OpenCode) |

Needs backend (later; the page renders "not available yet"): global task graph list, cost today and week by tier and layer (from traces), last error, provider health, MCP server status, feature flag list, Striatum summary, context-budget split of the last turn (P2-40), turn budget actuals (P2-41), drop-one-override per knob.
