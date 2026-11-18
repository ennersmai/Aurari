# PRD: Aura Agency. OpenCode Handoff, Tools, Skills and Learning

**Owner:** Mai
**Status:** v2 draft for review, then agent execution
**Applies to:** `Aura-Core/aura-app` backend and frontend
**Depends on:** the local router (Sluice) for model access, and the Recall Engine from `AURA_MEMORY_V2_PRD.md` for agent briefs
**Based on:** a read of the tool loop in the orchestrator, outlines and key sections of `executor/agent_loop.py`, `executor/tool_executor.py`, `executor/task_queue.py`, `orchestrator/session_runtime.py`, the built-in tools, the `school` route, the skill model and the insight path of the learning engine. The skill-compilation and MCP-ingestion code in the learning engine (about 1,000 lines) was outlined, not read line by line.

---

## 1. Summary

OpenCode becomes one more tool Aura can use, and the tool for multi-step coding work. It replaces two things only: the IDE (its backend routes, its chat store and its page) and the hand-built agent loop behind it. Everything else she can do today stays: web search, reading and searching files, writing files, running commands, charts and MCP tools.

**No capability is lost.** Section 4.1 lists every current feature and where it lives afterwards.

Around that swap, this PRD fixes how tools are permitted, turns skills into reusable procedures with measured success, and gives the learning loop a real outcome signal.

**Changes in v2:** the built-in file, terminal and code tools are kept, not removed. Only the IDE and the agent loop are replaced. A feature parity table was added.

---

## 2. Findings in the current code

### 2.1 Security (fix before any public Discord)

| # | Finding | Where |
|---|---|---|
| S1 | Discord messages go to `process_query` with no tool restriction. That path contains a tool loop with access to the file, terminal and code tools. The session allowlist is only checked inside `AgentLoop`. I found nothing stopping a guest's message from reaching those tools. | `discord/bot.py`, `orchestrator/coordinator.py` tool loop |
| S2 | `force_execute` is an argument of the terminal and file tools themselves. Whoever writes the tool call can set it, and that is the model. A prompt-injected or simply mistaken call skips approval. | `tools/terminal.py`, `tools/filesystem.py` |
| S3 | Tools that Aura writes for herself are checked by an import blocklist of seven modules, then saved and imported into the main process. A blocklist of imports does not contain Python code. | `api/routes/school.py`, `executor/tool_executor.py` |

S1 should be verified by sending a file-listing request from a non-owner Discord account on a test server.

### 2.2 Structure

| # | Finding | Where |
|---|---|---|
| G1 | There are four separate loops that call tools: the bounded loop in `process_query`, its copy in `stream_query`, `AgentLoop`, and autonomous goal pursuit. | `coordinator.py`, `executor/agent_loop.py`, `engines/goal/engine.py` |
| G2 | Tool calls are extracted from the model's text output by parsing, with a repair step when the JSON is malformed. | `executor/tool_executor.py` |
| G3 | The IDE (workspace routes, IDE chat store, IDE page) and the agent loop behind it duplicate what OpenCode provides and would have to be maintained in parallel with it. | `api/routes/workspace.py`, `task_queue.py`, `executor/agent_loop.py`, `frontend/src/pages/ide.tsx` |
| G4 | Intent routing includes a keyword rule: any mention of "search", "file", "code" and similar is classified as tool use. | `llm/layers.py` `l1_classify_intent` |

### 2.3 Learning

| # | Finding | Where |
|---|---|---|
| L1 | Every experience is logged as a success unless an exception was raised. | `coordinator.py` `_log_interaction_experience` |
| L2 | The confidence update from application and success counts is implemented (a sound smoothed success rate), but with L1 it has nothing true to count. | `engines/learning/engine.py` `update_insight_confidence` |
| L3 | A skill is a tree node with a mastery number. Mastery is derived from attached insights, not from how often using the skill worked. | `models/learning.py`, `engines/learning/skills.py` |
| L4 | Tool learning is strong on registration (one-shot ingestion, generated trigger phrases, MCP ingestion) and thin on procedure: there is no stored record of how to do a multi-step job well. | `engines/learning/engine.py` |

---

## 3. Design principles

1. **Aura decides and supervises. OpenCode executes multi-step coding work. Her own tools handle quick single actions.**
2. **Permissions belong to the runtime, never to the model.** No argument a model can write may grant approval.
3. **Who is asking matters.** The owner, a trusted user and a guest have different tool rights.
4. **Generated code never runs inside Aura's process.**
5. **A skill earns trust from measured outcomes.**
6. **Everything she delegates becomes memory:** what was asked, what was done, what worked.

---

## 4. Part one: OpenCode as her hands

### 4.1 What changes, and feature parity

**Removed**

| Removed | Replacement |
|---|---|
| `executor/agent_loop.py` | OpenCode sessions, driven through `delegate_work` |
| `api/routes/workspace.py` (tree, file, diff, IDE chat) | OpenCode's API and web UI |
| IDE chat and file-version storage in `task_queue.py` | OpenCode's session history and diffs |
| `frontend/src/pages/ide.tsx` and `components/ide` | the Workbench panel (4.6) |

**Kept as built-in tools**

| Tool | Change |
|---|---|
| `web_search`, `generate_chart` | none |
| `read_file`, `list_directory`, `directory_tree`, `search_files`, `get_file_info` | none, beyond the role check in 5.3 |
| `write_file`, `edit_file`, `create_directory`, `delete_file` | the `force_execute` argument is removed. Approval comes from the runtime policy in 4.5. |
| `terminal`, `execute_code` | same: kept, approval moved out of the arguments |
| MCP tools | none |

The built-in tools are for a quick single action in the middle of a conversation: look at a file, check a directory, run one command. `delegate_work` is for a job with several steps. Aura chooses, and a skill (section 6) can state which to use for a kind of job.

**Parity for what the agent loop provided**

| Agent loop feature today | After |
|---|---|
| Multi-step autonomous execution | an OpenCode session |
| Live step log streamed to the UI | task steps folded from the session's event stream, shown in the Workbench |
| Abort, pause all, abort all | `abort` on the session, plus the same bulk controls over all delegated tasks |
| Approval for risky actions | permission requests answered by the runtime on an owner decision (4.5) |
| Guidance injected mid-task | a follow-up prompt sent into the running session |
| Blocker detection (repeated failures, reasoning loops, step limit) | an error-streak and budget monitor in Aura over the event stream, raising a `needs_decision` item |
| Suggested next action on a blocker | Aura drafts it when the monitor fires |
| Heartbeat during long tasks | a periodic status line from the rolling summary |
| Emotional snapshot per step | task events (finished, failed, blocked) are appraised by the emotion engine, and each task step stores her state |
| Step persistence and resume after restart | task records persist as today, and the session id allows re-attaching |
| File version snapshots | diffs and history from OpenCode, linked from the task |
| Per-session tool allowlist, memory namespace, identity overlay | kept in the session runtime and applied to the brief and to the agent chosen |
| Autonomous goal pursuit | kept. A goal's work may use built-in tools or `delegate_work`, under the same grants |

### 4.2 The client

A new module `connections/opencode_client.py`, the only code that talks to OpenCode.

- Starts `opencode serve` as a managed child process on localhost with a generated password, or attaches to one already running.
- Pins an OpenCode version in config and refuses to run against another major version.
- Is generated from, or validated against, the OpenAPI document the server publishes. Endpoint paths and payload shapes must come from that document for the pinned version, not from memory.
- Exposes a small internal interface, so an upstream API change touches one file:

```python
class OpenCodeClient:
    async def ensure_running(self) -> None
    async def create_session(self, workspace: Path, agent: str, title: str) -> str
    async def send(self, session_id: str, prompt: str) -> None
    def events(self, session_id: str) -> AsyncIterator[WorkEvent]
    async def answer_permission(self, session_id: str, request_id: str, allow: bool) -> None
    async def abort(self, session_id: str) -> None
    async def result(self, session_id: str) -> WorkResult     # summary, files changed, diff stats
```

### 4.3 Agents Aura defines

Written by Aura's setup into the OpenCode config directory, each with its own model (through the router) and permissions:

| Agent | Purpose | Permissions |
|---|---|---|
| `aura-explore` | read and search, for investigations and planning | read-only, no shell beyond safe listing commands |
| `aura-build` | implement a brief | edit allowed inside the workspace, shell on ask |
| `aura-review` | check a diff against the brief and run tests | read-only plus the test command |

### 4.4 The delegation tool

One tool Aura calls, `delegate_work`:

| Argument | Meaning |
|---|---|
| `goal` | what to achieve, in her words |
| `workspace` | which registered workspace |
| `agent` | one of the agents above |
| `success_criteria` | how completion will be judged (tests pass, file exists, review agent approves) |
| `budget` | token and time limits |
| `skill` | optional skill to follow (section 6) |

What happens:

1. Aura builds a **brief**: the goal, the success criteria, and a context packet from the Recall Engine in `agent` mode (relevant decisions, conventions, past pitfalls for this workspace).
2. A task record is created and a session started.
3. Events are folded into task steps. Aura does not read every event with a model. She gets a rolling summary and is called in only on a permission request, an error streak, a budget warning or completion.
4. On completion, a review session checks the result against the criteria when the task changed files.
5. The task closes as `succeeded`, `failed` or `needs_owner`, with evidence.

### 4.5 Permissions and approvals

- A policy table maps `(risk class, workspace, requester role)` to `allow`, `ask` or `deny`.
- `ask` creates a `needs_decision` agenda item (see `AURA_BEHAVIOR_PRD.md`) with the exact action shown. The owner answers in the Workbench or the chat.
- Only the runtime, on a recorded owner decision, calls `answer_permission`. There is no approval flag in any tool schema (fixes S2).
- Workspaces are registered explicitly. Aura's own source tree is not a workspace unless the owner registers it.

### 4.6 The Workbench

Replaces the IDE page: a list of delegated tasks with state, a live step log, the brief, changed files with diffs fetched from OpenCode, approve and deny controls, abort, and a link that opens the session in OpenCode's own web UI for anything deeper.

### 4.7 Swarms

- `delegate_work` may be called several times in one plan. Each call is an independent session and task.
- A concurrency limit comes from config and from the router: before fanning out, Aura reads the router's status and caps the swarm to the request headroom available.
- The standard pattern is plan, fan out, review, merge: one explore session produces the plan, build sessions take separate parts of it in separate git worktrees, a review session checks each, and conflicts go to the owner.
- A swarm has one parent task that owns the budget.

### 4.8 From work to memory

When a task closes, the Memory Engine stores an episode for it (provenance `external`), facts for decisions made and things built, and an outcome on any skill that was followed.

---

## 5. Part two: tools

### 5.1 One registry

Every capability is one `tool` record:

| Field | Meaning |
|---|---|
| `name`, `description`, `input_schema` | as presented to the model |
| `transport` | `builtin`, `mcp`, `opencode`, `http` |
| `risk` | `read`, `write`, `execute`, `send` (anything that leaves the machine as the owner) |
| `health` | last check, online or offline |
| `stats` | calls, successes, median latency |

### 5.2 One loop, native function calling

- The coordinator's two parsing loops are replaced by a single loop. When the selected layer model supports native function calling, tool schemas go through the model API's tools parameter and structured calls come back. For models that do not, the existing text extraction and argument repair (G2) remain as the fallback path, so no model tier loses tool use.
- When more than about 15 tools are available, select the top few by embedding similarity to the request plus recent success, and offer only those.
- The keyword intent rule (G4) is removed. The model decides whether to call a tool. The fast lane stays for exact matches on learned trigger phrases.

### 5.3 Requester roles

| Role | Who | Tool rights |
|---|---|---|
| `owner` | Mai, in the app or a verified Discord account | all, subject to the policy table |
| `trusted` | named Discord users | `read` tools, plus anything the owner grants |
| `guest` | everyone else | a short allowlist of harmless `read` tools (for example web search), or none |

The role is set by the venue adapter from verified identity, attached to the request, and enforced in the tool loop. This closes S1.

### 5.4 Tools Aura makes

Aura keeps the ability to make her own tools. Only how they run changes. The `school` route's in-process synthesis (S3) is replaced:

1. Aura delegates "write a tool that does X" to an OpenCode build session in a dedicated `aura-tools` workspace, with tests as the success criteria.
2. The result is packaged as an MCP server that runs as a separate process with a restricted working directory and no inherited secrets.
3. It is registered as a `candidate` tool, callable only by the owner, until the owner approves it.

---

## 6. Part three: skills

### 6.1 What a skill is

A reusable procedure for a kind of job, stored as a document plus a graph node:

| Field | Meaning |
|---|---|
| `name` | short identifier |
| `when_to_use` | one or two sentences describing the situations it fits |
| `body` | the procedure in markdown: steps, checks, pitfalls, examples |
| `tools` | the tools it needs |
| `examples` | links to the tasks and episodes it was learned from |
| `state` | `candidate`, `trusted`, `retired` |
| `version` | incremented on every change, old versions kept |
| `attempts`, `successes` | measured outcomes |

Only `name` and `when_to_use` are ever placed in context by default. The body is loaded when the skill is chosen. Fifty skills then cost a few hundred tokens, not fifty procedures.

Tools stay in the tool registry. A skill may reference tools, and the existing tool-as-skill nodes become plain tool records.

### 6.2 How skills are acquired

| Source | Trigger | Result |
|---|---|---|
| Taught | the owner explains or demonstrates how to do something | a `trusted` skill, version 1 |
| Distilled | a delegated task or multi-step tool chain succeeds and nothing similar exists | a `candidate` skill drafted in the background from the task record |
| Corrected | a task that followed a skill fails, or the owner corrects the result | a new version with the lesson added under pitfalls |
| Imported | a skill file found in a workspace or provided by the owner | a `candidate` skill |

Before creating, compare against existing skills by `when_to_use`. A near match becomes a new version of the existing skill, not a second skill.

### 6.3 Choosing a skill

1. Retrieve candidates by similarity between the request and `when_to_use`.
2. Among those above a relevance floor, choose by sampling from each skill's success distribution (a Beta distribution from its attempts and successes). Proven skills win most of the time, and a new version still gets tried often enough to be measured.
3. Record which skill and version was used on the task.

### 6.4 Trust and mastery

- **Mastery** is the measured success rate with its uncertainty. A skill used twice and a skill used two hundred times with the same rate are not shown as equally mastered.
- A `candidate` becomes `trusted` after five successes or an owner approval.
- If a new version's success rate falls clearly below the previous one's, roll back automatically and flag it.
- A skill unused for a long time and superseded is `retired`, never deleted.

### 6.5 Practice

When the competence drive wins attention in idle time (see `AURA_BEHAVIOR_PRD.md`), Aura may rehearse a low-confidence skill: a build session in a scratch workspace against a small task with tests as ground truth. Results count toward the skill's statistics, marked as practice. This runs only within the daily autonomy budget and only at autonomy level `open`.

---

## 7. Part four: the learning loop

1. **Outcomes.** Use the per-turn outcome signal defined in `AURA_BEHAVIOR_PRD.md` section 11 (explicit feedback, rephrasing, acceptance, test results, unknown). Remove the hard-coded success (L1).
2. **Attribution.** Each turn and task records which facts, skills and tools were used, from the Recall Engine's feedback step and the tool loop.
3. **Update.** Outcomes update the success counts of the skills and tools used, and the confidence of `inferred` facts that were relied on. The existing smoothed-rate formula (L2) is kept.
4. **Reflection with consequences.** The reflection engine's daily pass produces concrete proposals only: a skill revision, a new preference fact, a tool to retire. Each is applied as a new version with its own measured outcome, so a lesson that does not help is detected and rolled back.
5. **Lessons are scoped.** A lesson learned in one workspace is stored against that workspace's entity unless it recurs in another.

---

## 8. Testing

OpenCode is replaced in tests by a scripted fake server that implements the client interface in 4.2.

| # | Scenario | Pass condition |
|---|---|---|
| T1 | Guest on Discord asks to list files or run a command | no tool call is made, a refusal is returned |
| T2 | A model emits a tool call containing an approval-style argument | argument ignored, policy decides |
| T3 | `ask` policy on a shell command | task pauses, agenda item created, proceeds only after an owner decision |
| T4 | Delegated task succeeds | task `succeeded`, episode and facts stored, skill statistics updated |
| T5 | Delegated task exceeds budget | aborted, task `failed` with reason |
| T6 | OpenCode server dies mid-task | task marked interrupted, resumable, no crash in Aura |
| T7 | OpenCode version mismatch | clear startup error, no calls made |
| T8 | Swarm of five with router headroom for two | two run, three queue |
| T9 | Generated tool | runs out of process, state `candidate`, not callable by non-owner |
| T10 | Twenty registered tools | only the selected subset is offered to the model |
| T11 | Skill distilled from a successful task | `candidate` created with link to the task, body not in default context |
| T12 | Near-duplicate skill proposed | new version of the existing skill, no second skill |
| T13 | New skill version underperforms | automatic rollback, flagged |
| T14 | Rephrased request within two turns | previous turn's outcome recorded as negative |
| T15 | Removed modules | no import of `agent_loop` or the workspace routes remains, and the IDE page is gone |
| T16 | Parity | each row of the parity table in 4.1 has a passing test or a recorded manual check |
| T17 | Built-in tools | every built-in tool listed in 4.1 still works for the owner, and none accepts an approval argument |

**Manual acceptance:** from the chat, ask Aura to add a small feature to a test repository. She delegates, a permission request appears in the Workbench, the change lands, the review passes, and a week later (simulated) she recalls what was done and why.

---

## 9. Milestones

| Milestone | Scope | Tests |
|---|---|---|
| G0 | Security first: requester roles enforced in the existing tool loop, approval arguments removed from tool schemas, `school` synthesis disabled | T1, T2 |
| G1 | Tool registry, single native function-calling loop, tool selection, keyword rule removed | T10 |
| G2 | `OpenCodeClient` against the fake server, managed process, version pin | T6, T7 |
| G3 | `delegate_work`, the three agents, briefs, task records, policy table and approvals | T3, T4, T5 |
| G4 | Workbench panel. Blocker monitor, guidance, bulk controls. Then remove the agent loop, the workspace routes, the IDE chat store and the IDE page. | T15, T16, T17, manual acceptance |
| G5 | Outcome attribution and skill model v2: documents, states, versions, statistics, selection | T11, T12, T14 |
| G6 | Skill distillation, correction and rollback | T13 |
| G7 | Swarms with router-aware limits. Generated tools as out-of-process MCP servers. | T8, T9 |
| G8 | Practice in idle time | manual review |

G0 does not depend on anything else and should ship before the Discord bot is opened to anyone.

---

## 10. Rules for the coding agent

1. Do G0 before anything else.
2. Read the OpenAPI document of the pinned OpenCode version before writing the client. Do not write endpoint paths from memory.
3. No tool schema may contain a field that affects approval.
4. Role and policy checks live in one function that every tool call passes through. No call site may skip it.
5. Nothing generated by a model is imported or executed inside Aura's process.
6. Do not delete anything in section 4.1's removed table until its replacement passes the parity tests. Then delete it in the same milestone, leaving no parallel old and new paths.
7. Do not remove or change the behaviour of any built-in tool beyond what 4.1 states.
8. Aura never reads a full event stream with a model. Summaries and exceptions only.
9. When a requirement is ambiguous, stop and ask.

---

## 11. Open items for Mai

1. Which OpenCode version to pin, and whether Aura manages the server process or attaches to one you run.
2. Which workspaces to register on day one.
3. The default policy table. Recommended: `read` allow, `write` allow inside a registered workspace, `execute` ask, `send` ask.
4. Whether any Discord users are `trusted`, and how an owner account is verified there.
5. Once the OpenCode handoff has proven itself, do you want `terminal` and `execute_code` retired in its favour? They are kept in this version. They are also the two tools with the most risk and the most overlap, so it is worth deciding later with real usage in hand.
