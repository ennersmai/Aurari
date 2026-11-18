# PRD: Aura Behaviour, Initiative and Curiosity

**Owner:** Mai
**Status:** v1 draft for review, then agent execution
**Applies to:** `Aura-Core/aura-app/src/aura`
**Depends on:** the `question` and `prediction` nodes and the Recall Engine from `AURA_MEMORY_V2_PRD.md`
**Based on:** a read of the orchestrator's idle and turn pipeline, the goal engine, the message bus and the websocket layer. The identity and reflection engines were outlined, not read line by line.

---

## 1. Summary

Today Aura's inner life runs on timers. This PRD replaces "something fires when the clock says so" with "something happens because she has a reason": a gap she wants to close, a result she wants to share, a prediction that turned out wrong.

Three changes carry it:

1. **An event-driven workspace** where engines propose and one proposal at a time wins attention.
2. **A curiosity loop** that turns what she does not know into investigations, and investigations into things worth saying.
3. **An agenda with a model of when you can be interrupted**, so she speaks first only when she has content and you have room.

---

## 2. Findings in the current code

| # | Finding | Where |
|---|---|---|
| B1 | Initiative is timer-based. A new goal is considered when boredom passes a threshold or idle time passes a limit, at most once an hour. | `engines/goal/engine.py` `tick`, `_consider_new_goal` |
| B2 | Goal progress rises by 0.1% per tick when her mood matches the goal's emotional alignment. Progress measures feeling, not work done. | `goal/engine.py` `tick` |
| B3 | A goal older than 24 h with under 10% progress is marked complete at 100%. | `goal/engine.py` `tick` |
| B4 | Autonomous pursuit is requested by emitting a text tag (`[GOAL_PURSUIT_REQUEST:id]`) inside a chat reply, which the frontend finds with a regular expression. | `llm/layers.py` prompt, `frontend/src/pages/chat.tsx` |
| B5 | The app has no channel for her to speak first. The websockets carry emotion updates and traces only. Discord has an unprompted mode, the app does not. | `api/websocket.py`, `main.py` |
| B6 | The turn pipeline exists twice: `process_query` and `stream_query` are parallel implementations of about 550 lines each, and they have already drifted (memory depth 2 in one, 1 in the other). | `orchestrator/coordinator.py` |
| B7 | The idle loop only moves the system between active, idle, dreaming and sleeping. While sleeping she does nothing until woken. | `coordinator.py` `check_idle_state` |
| B8 | Experiences are logged with `outcome: {"success": True}` whenever no exception occurred, so nothing downstream knows whether a turn went well. | `coordinator.py` `_log_interaction_experience` |

The message bus already has a `PROPOSAL` message type and per-engine subscriptions. The design below builds on that, it does not replace it.

---

## 3. Design principles

1. **No content, no initiative.** She never speaks first because time passed. She speaks first because an item exists that is worth your attention.
2. **Drives choose what to do with free time. They never override a request.**
3. **Emotion modulates, within bounds.** Emotions adjust how strongly a drive pulls, by at most 20% either way. They do not decide actions.
4. **Curiosity is read-only by default.** Investigating may search, read and ask. Anything that writes, runs or sends needs a grant.
5. **Everything autonomous is budgeted, logged and switchable off.**
6. **Model calls happen on events, not on ticks.** State updates between events are arithmetic.

---

## 4. The workspace

A new module `orchestrator/workspace.py`, built on the existing message bus.

### 4.1 Proposals

Any engine may post a proposal:

```python
class Proposal:
    source: str                 # engine id
    kind: Literal["respond", "investigate", "share", "consolidate",
                  "pursue_goal", "ask_user", "practice"]
    summary: str                # one line, for the trace and the mind panel
    refs: list[str]             # ids of the questions, facts, tasks or goals involved
    urgency: float              # 0 to 1
    value: float                # expected benefit, 0 to 1
    cost: Cost                  # tokens, seconds, risk class
    expires_at: datetime | None
```

### 4.2 Attention

One attention step picks at most one winner:

1. A user message always wins and pre-empts anything interruptible.
2. Otherwise score each live proposal as `urgency * value * drive_gain / cost`, where `drive_gain` comes from section 5.
3. Reject proposals over budget or over the current autonomy level.
4. The winner is broadcast on the bus. Engines react, and the outcome is posted back as an event.

### 4.3 What triggers a cycle

Events, not a fixed sleep: a user message, a tool or task result, a settled prediction, a resolved question, a dream cycle finishing, an agenda item coming due. A slow fallback timer (every 5 minutes) only checks that nothing is stuck.

### 4.4 One turn pipeline

`process_query` and `stream_query` are merged into a single async generator with a `stream` flag before any behaviour hooks are added, so each hook is written once. The non-streaming entry point collects the generator's output.

---

## 5. Drives

Five scalars in 0 to 1, updated by arithmetic on events and persisted. No model call.

| Drive | Rises when | Falls when | Proposals it favours |
|---|---|---|---|
| Curiosity | open questions accumulate, a prediction fails, something new is mentioned and not explained | a question is resolved | `investigate` |
| Competence | a task or goal is unfinished, a skill has low measured success | work completes, a practice run passes | `pursue_goal`, `practice` |
| Connection | she holds findings not yet shared, time since a real exchange grows | an item is delivered and acknowledged | `share`, `ask_user` |
| Coherence | contradictions stay unresolved, extraction backlog grows | contradictions are settled | `ask_user`, `consolidate` |
| Rest | consolidation debt grows (episodes not yet processed) | a dream cycle completes | `consolidate` |

`drive_gain` for a proposal is its drive's level, multiplied by a bounded emotion factor: the matching emotion dimensions (for example `curiosity` and `fascination` for the curiosity drive, `boredom` for competence) scale the gain between 0.8 and 1.2.

Boredom stops being a goal generator. It becomes one input to the competence and curiosity gains.

---

## 6. The curiosity loop

### 6.1 Where questions come from

`question` nodes are created by:

- extraction, when a turn mentions something that is never explained
- the conflict check, when two facts contradict
- a failed prediction (the gap between what she expected and what happened)
- a task that hit something she could not do
- dreaming, when a bisociation walk suggests a link (provenance `imagined`)
- Aura herself, during a reply, through a `wonder(question)` tool

### 6.2 Which question to pursue

`score = learning_value * relevance * tractability`

- **Relevance:** closeness to the owner's active projects, goals and recent topics, from the graph.
- **Tractability:** can it be answered with the tools she has? A question about the owner's preferences is only answerable by asking. A question about a library is answerable by reading.
- **Learning value:** the expected drop in her error on that topic. Each entity and theme keeps a running average of prediction error. Topics where the error has been falling are learnable and score high. Topics where it stays high regardless are noise and score low. Topics with almost no error are already known.

That last rule is what separates curiosity from random exploration: she prefers what she is in the middle of getting better at.

### 6.3 Investigating

1. A bounded, read-only investigation: web search, reading documentation, or a read-only explore agent through OpenCode (see `AURA_AGENCY_PRD.md`).
2. Hard limits per investigation: tokens, tool calls and minutes, all from config.
3. Findings are stored as facts with provenance `external` and their sources.
4. The question is marked resolved, partly resolved, or parked with a reason.
5. If the finding matters to the owner, a `share` proposal is posted with the finding attached.
6. If the question can only be answered by the owner, an `ask_user` item goes on the agenda. She never guesses.

### 6.4 Budgets

Per day: a number of investigations, a token ceiling and a spend ceiling. When any is reached, curiosity proposals are rejected until the next day. The mind panel shows the remaining budget.

---

## 7. Predictions

After each turn the background extraction emits up to two short predictions: what the owner is likely to do or ask next, or how a running task will turn out. Each has a confidence.

When a later event settles a prediction:

- the error is recorded on the `prediction` and averaged into its topic
- a large error raises the `surprise` dimension through the emotion engine, replacing the constant 0.5 used today
- it raises the salience of the episodes involved, so they are consolidated first
- it may create a `question`

This gives surprise, memory salience and curiosity one shared source.

---

## 8. The agenda

Things she wants to raise, stored in an `agenda_item` table:

| Field | Meaning |
|---|---|
| `kind` | `finding`, `task_done`, `needs_decision`, `question_for_you`, `reminder`, `observation` |
| `content` | what she would say, drafted when the item is created |
| `refs` | the facts, tasks or questions behind it |
| `priority` | 0 to 1, decays over time at a rate set per kind |
| `venue` | where it may be delivered (app, a specific Discord channel) |
| `expires_at` | after this it is dropped silently |
| `state` | `pending`, `delivered`, `acknowledged`, `dismissed`, `expired` |

An item with no `refs` cannot be created. That is how principle 1 is enforced.

### 8.1 When to deliver

A numeric interruptibility estimate for the owner, 0 to 1, from signals already available:

- typing or active in the app right now (low)
- a delegated task is running that they are watching (low)
- seconds since their last message (rises, then falls after long absence)
- local time against configured quiet hours (zero inside them)
- recent dismissals (lowers it for a while)

Deliver when `priority * interruptibility` passes a threshold. `needs_decision` items for a blocked task use a lower threshold.

### 8.2 After delivering

- A refractory period before the next unprompted message.
- If the owner replies or acts, the item is acknowledged and that kind's threshold eases slightly.
- If the owner dismisses or ignores it, that kind's threshold rises. Three dismissals in a row mute the kind for a day.
- When the owner next speaks, pending items relevant to what they said are offered to the Recall Engine as a working-set block, so she can bring them up naturally inside the conversation instead of interrupting.

### 8.3 Owner controls

- Autonomy level: `silent` (nothing unprompted), `important` (decisions and finished tasks only), `open` (everything).
- Per-kind mute.
- A kill switch that stops all autonomous activity immediately.

### 8.4 Delivery channel

A new websocket `/ws/aura` carrying `aura_message`, `agenda_update` and `drive_state` events, plus `GET /agenda` and `POST /agenda/{id}/ack|dismiss`. In the app, low-priority items show as a quiet indicator the owner can open. High-priority items arrive as a message.

---

## 9. Goals v2

- A goal has **success criteria** that can be checked: a test passes, a file exists, a question is resolved, the owner confirms.
- **Progress comes only from evidence:** completed task steps and met criteria. The mood-based increment (B2) is removed.
- A goal that stalls becomes `abandoned` with a reason. It is never marked complete (B3).
- Goals come from the owner, or from a drive proposal the owner has accepted, or (at autonomy `open`) from a read-only curiosity question.
- Pursuit is requested through a structured tool call, `request_pursuit(goal_id, scope, budget)`, which creates a `needs_decision` agenda item. The text tag (B4) is removed.
- A grant has a scope: read-only work needs no grant. Writing, running commands or sending anything needs one, per goal, with an expiry.

---

## 10. Inner thoughts

Not a continuous monologue. When an internal proposal wins (a question resolved, a prediction badly wrong, two memories linked), one small model call produces a short thought. It is stored as an episode with speaker `aura` and provenance `inferred` or `imagined`, and shown in a "mind" panel in the app.

Thoughts are capped per hour. They are never treated as facts, and the Recall Engine excludes them from normal recall unless the owner asks what she has been thinking about.

---

## 11. Real outcomes

Replace the hard-coded success flag (B8) with a signal per turn:

- explicit: a thumbs control in the app, or a correction ("no, I meant...")
- implicit negative: the owner rephrases the same request within two turns
- implicit positive: the owner builds on the answer, accepts a diff, or a task's tests pass
- unknown: when there is no evidence either way

Outcomes are attached to the experience and feed prediction settlement, skill statistics and the dismissal learning in section 8.2.

---

## 12. Testing

All scenarios run on the simulated clock from the memory PRD's harness.

| # | Scenario | Pass condition |
|---|---|---|
| T1 | Idle for six simulated hours with no questions and no findings | zero unprompted messages |
| T2 | A question is resolved while the owner is typing | item delivered only after typing stops and the threshold is met |
| T3 | Three dismissals of `finding` items | that kind muted for a day, other kinds unaffected |
| T4 | Quiet hours | nothing delivered, items wait or expire |
| T5 | Autonomy `silent` | no investigation, no delivery, drives still update |
| T6 | Daily budget reached | further curiosity proposals rejected and logged |
| T7 | Goal with matching mood and no work done | progress stays at zero |
| T8 | Goal stalled past its limit | state `abandoned`, not complete |
| T9 | Failed prediction | surprise rises, question created, episode salience raised |
| T10 | Two topics, one with falling error and one with flat high error | investigations go to the first |
| T11 | Investigation tries a write tool without a grant | blocked, `needs_decision` item created |
| T12 | User message during an investigation | investigation pauses within 2 s, reply proceeds |
| T13 | Streaming and non-streaming turn on the same input | identical context packet and hooks |
| T14 | Kill switch | all autonomous tasks stop within 2 s |

**Ablations**, each behind a flag: emotion modulation of drives, learning-value scoring (against random question choice), interruptibility model (against a fixed cooldown), predictions.

**The number that matters in real use:** the share of unprompted messages the owner replies to or acts on. Logged per kind and shown in the mind panel. If it stays low for a kind, that kind is wrong and should be cut.

---

## 13. Milestones

| Milestone | Scope | Tests |
|---|---|---|
| B0 | Merge `process_query` and `stream_query` into one pipeline. No behaviour change. | T13 |
| B1 | Real outcome signals. `/ws/aura` channel, agenda table and endpoints, owner controls, kill switch. Manual agenda items only. | T4, T5, T14 |
| B2 | Workspace: proposals, attention, event triggers. Drives as persisted scalars. | T1, T12 |
| B3 | Goals v2: criteria, evidence-based progress, abandonment, structured pursuit requests and grants | T7, T8, T11 |
| B4 | Curiosity loop: question scoring without learning value, investigations, budgets, findings to agenda | T2, T6 |
| B5 | Interruptibility model and dismissal learning | T2, T3 |
| B6 | Predictions and learning-value scoring | T9, T10 |
| B7 | Inner thoughts and the mind panel | manual review |

B4 onward requires the `question` node from the memory PRD (its milestone M4).

---

## 14. Rules for the coding agent

1. Do B0 first. No behaviour hook may be added to two pipelines.
2. No model call inside a timer loop. Model calls are made in response to an event that carries a reason.
3. An agenda item without `refs` must be rejected at creation.
4. Autonomous code paths take the simulated clock and the budget object as parameters, never read wall time or config directly.
5. Every autonomous action writes a trace record: what proposed it, why it won, what it cost.
6. Thresholds, decay rates and budgets live in config.
7. When unsure whether an action counts as read-only, treat it as needing a grant.

---

## 15. Open items for Mai

1. Default autonomy level for a fresh install. Recommended: `important`.
2. Daily curiosity budget in money terms.
3. Quiet hours.
4. Should guests on Discord be able to trigger investigations, or only the owner? Recommended: only the owner.
