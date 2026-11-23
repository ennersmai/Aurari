# OpenCode v2.3.2: subagents (P2-10 step 1)

Research only; no code changed. Sources: `docs/opencode/openapi-v2.3.2.json` (cited as `spec:<line>`),
`src/aura/connections/opencode_agents.py`, `src/aura/config.py`. The binary is not on PATH here and
`AURA_OPENCODE_COMMAND` is empty (`config.py:1378`), so no `--help` was run. Web docs were not consulted.
Note: this v2 API differs from older OpenCode docs (`task` tool, markdown agents). Do not assume those.

## Q1. How does a primary agent start a subagent?

Answer. The v2.3.2 spec describes no built-in `task` tool (the word "task" appears nowhere as a tool name).
The documented mechanism is a child session: `POST /api/session` with `parentID` "creates a subagent
session at the parent's location; set `agent` to choose its agent (otherwise it uses the default) and start
it with `session.prompt`. After each completed round, the child sends a `<subagent>` report to the parent's
inbox and wakes the parent unless it has a staged revert" (spec:1132). So Aura, or a tool inside OpenCode,
can create children through the API. Whether the lead model itself has a tool that does this is not shown in
the spec. Related evidence: a background job kind `subagent` with `childSessionID`, `agent`, `description`
(`Job.Subagent`, spec:19735; `Job.Kind`, spec:20472). Automations can start "a permitted child that does not
report back" via `send.to.subagent` (spec:20285).

Agent config (`Config.AgentEncoded`, spec:18649), under top-level `agents` in the config (spec:17166).
Allowed fields only (`additionalProperties: false`): `model` (string "provider/model[#variant]" or
`{providerID, model, variant}`), `request {headers, body}`, `system` (the prompt), `description`,
`mode` (`subagent` | `primary` | `all`), `hidden`, `color` (#rrggbb), `steps` (max steps), `disabled`,
`permissions` (array of `{action, resource, effect: allow|deny|ask}`). There is no `tools` or `prompt` field
in v2; the prompt is `system`, and tool gating is `permissions`. Aura's three agents already use this shape
(`opencode_agents.py:91-158`): aura-explore and aura-review are `mode: subagent`, aura-build is `primary`.

Confidence: high that child sessions with `parentID` + `agent` exist and report back through the inbox;
medium-low on whether the lead LLM can spawn them itself via a tool (not in the spec; needs a live check).

## Q2. Parallel subagents in one session? Limit?

Answer. Nothing forbids it: children are independent sessions (each has its own `session.execution.*`
events), and the jobs API can include jobs "owned by child and nested subagent sessions" (spec:14305). The
only limit in the spec is `experimental.subagent_depth` (integer >= 0, spec:17514), which bounds nesting
depth, not breadth. No max-parallel setting was found. The "up to 3" in P2-10 would have to be enforced by
Aura (or the lead's prompt and `steps`), not by OpenCode.
Confidence: medium (inferred from the session model; not stated).

## Q3. Different working directory or worktree for a subagent?

Answer. By the spec, a child created with `parentID` is "at its parent's location" (spec:1105, 1132), so it
inherits the session directory. A location is `Location.PublicRef {directory}` (spec:16945).
`POST /api/session` also takes an optional `location`, but with `parentID` the parent's location is the
documented one; whether an explicit `location` overrides it is unclear. A session can be relocated
afterwards: `POST /api/session/{id}/move` "Move a session to another project directory at the requested
delivery boundary" (spec:2054). A child could probably be created then moved, but that is unverified. There
is also a worktree API: `/api/worktree` list, create, remove, refresh (spec:15008-15252; create "creates a
local worktree using its selected strategy, then runs the project's setup script"), keyed by `projectID`.
Session list filters by `directory` and `subpath`.
Confidence: high that the default is inheritance; low on override via `location` or `move` for children.

## Q4. How do subagent steps appear in the event stream?

Answer. `GET /api/event` (spec:10730) is one stream; its only query parameter is `types`. Session events
carry `data.sessionID` (for example `session.tool.called`, `session.execution.started`, `session.step.*`,
`session.text.*`), so a child's events carry the child's own sessionID, not the parent's. `session.created`
carries `data.parentID` and `agent`; `Session.Info.parentID` (spec:35027) comes from `GET /api/session/{id}`;
`GET /api/session?parentID=...` lists children (spec:941). Aura can attribute events: learn the child on
`session.created` (parentID + agent), then map `data.sessionID` to agent and node. `session.inbox.enqueued`
and `session.inbox.delivered` show the `<subagent>` report reaching the parent.
Confidence: high.

## Q5. Per-subagent model?

Answer. Yes. `Config.AgentEncoded.model` is per agent (spec:18649), `POST /api/session` accepts `model` and
`agent` (spec:1150-1170), and `/api/session/{id}/model` changes it later. Aura currently sets one model for
all three agents (`opencode_agents.py:43-46`); a per-agent override is a config change only.
Confidence: high.

## Q6. Do subagent permission requests reach the same endpoints?

Answer. Yes by design. `Permission.Request` has a required `sessionID` (the child's id for child requests);
`GET /api/permission/request?location[directory]=` lists pending requests per location (spec:9040); replies
go to `POST /api/session/{sessionID}/permission/{requestID}/reply` (spec:9688). The reply path is per
session, so Aura must reply on the child's sessionID, not the lead's. `POST /api/session` also accepts a
per-session `permissions` ruleset (spec:1190), and the agent's `permissions` apply.
Confidence: medium-high (schema-based; not seen live).

## Design implications for P2-10

1. Starting subagents. Safest spec-backed path: Aura creates the children (or a thin tool exposed to the
   lead does). aura-lead is a `mode: primary` agent; for workers Aura calls
   `POST /api/session {parentID: lead, agent: "aura-build"|"aura-explore"|"aura-review", model?}` then
   `session.prompt` with the brief, at most 3 at once (Aura-enforced). Results arrive as `<subagent>` inbox
   reports that wake the lead. Verify live (one throwaway session) whether the lead can spawn children itself
   and whether a lead mid-run accepts the wake.
2. Mismatch to watch: aura-build is `primary`. If it must run as a child it should be `all`, or use a new
   `aura-worker` with `mode: subagent`. Unverified whether a child's `agent` must be `subagent` or `all`.
3. Worktrees per build node. Do not rely on children overriding the directory. Preferred design: one
   OpenCode session per build node, each created with `location.directory` set to that node's git worktree
   (made by Aura with `git worktree add`, or via `/api/worktree`), coordinated by Aura. Use `parentID` only
   for linkage if the cwd override works; otherwise nodes are independent root sessions and Aura keeps the
   node-to-session map. Attribute events by sessionID (Q4); reply to permissions per session (Q6). Two live
   checks: (a) `POST /api/session` with `parentID` plus a different `location`; (b) `session.move` on a
   fresh child.
4. D4 ("one OpenCode session at a time"). One server can host many sessions across locations, so server
   count is not the issue; the concurrency rule is. Parallel build nodes need D4 relaxed to "one server, one
   session per build node, at most N active (N = 3), with the per-worktree location as isolation". If D4
   must stay strict, nodes run sequentially (one session, one worktree at a time) and subagents (read-only
   explore/review in the same directory) are the only parallelism. This is a decision for Mai.
