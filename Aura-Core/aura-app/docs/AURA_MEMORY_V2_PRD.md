# PRD: Aura Memory v2 and the Recall Engine

**Owner:** Mai
**Status:** v2 draft for review, then agent execution
**Applies to:** `Aura-Core/aura-app/src/aura`
**Based on:** a read of the memory, dreaming, emotion and latent engines, the insight and experience paths of the learning engine, and the prompt assembly in `llm/layers.py`. The goal, identity, reflection and skill-compilation code was only outlined, not read line by line.

---

## 1. Summary

Aura's memory has the right ideas: gated formation, multi-signal retrieval, graph clusters, dreaming, recall tools. Three things hold it back.

1. **Calibration bugs make her forget.** As written, every memory is soft-deleted about nine days after formation unless it is recalled, and nothing can become a protected core memory.
2. **The graph stores what the vector index already knows.** Most edges are similarity links. There are no entities, no facts with validity, and no record of what replaced what.
3. **Retrieval is five separate injectors.** Memory, insights, cold start, latent intuition and the recall tools each fetch and inject on their own, with no shared budget, ranking or deduplication.

This PRD fixes the bugs first, then turns the store into a temporal knowledge graph with provenance, and adds a dedicated Recall Engine that owns the entire read path.

### Division of responsibility after this work

| Engine | Owns |
|---|---|
| Memory Engine | The write path: episodes, extraction, entity resolution, supersession, lifecycle |
| Recall Engine (new) | The read path: when to recall, what to fetch, how to rank, what fits the budget |
| Dreaming Engine | Offline consolidation: themes, summaries, replay, archiving |
| Learning Engine | Skills and behavioural patterns. Its user facts move into the shared fact store |
| Latent Engine | Unchanged. Its summary becomes one block the Recall Engine budgets |

---

## 2. Findings in the current code

Each row names the file and function so the fix can be located directly.

### 2.1 Critical

| # | Finding | Where |
|---|---|---|
| F1 | Non-core memories are soft-deleted when decay drops below 0.05. With a 48 h half-life that is about 8.6 days. Each recall adds roughly 2 days. | `engines/dreaming/engine.py` `_tiered_pruning`, `_compute_decay` |
| F2 | Emotional intensity is the vector norm divided by 5.2 (the norm of 27 dimensions at 1.0). Three dimensions at 0.8 give 0.27. The 0.7 protection threshold needs 14 dimensions at full strength, so emotional protection never triggers. | `engines/memory/manager.py` `_compute_emotional_intensity`, `_compute_decay_factor` |
| F3 | Core memories cannot form. On the conversation path the formation score tops out near 0.60 against a threshold of 0.75, and no other code sets `core_memory`. | `manager.py` `_compute_formation_score`, `store_memory` |
| F4 | Semantic memories produced by dreaming are stored as ordinary memories and decay on the same clock, after their source episodes were deprecated. | `dreaming/engine.py` `_abstract_episodic_clusters` |
| F5 | A changed fact is treated as a duplicate. Above the similarity threshold only the confidence is updated and the old content is kept. Below it, both versions stay active. There is no supersession. | `engines/learning/engine.py` `create_insight` |
| F6 | Retrieval is not scoped by user. Both `retrieve_for_l3` call sites omit `user_id`, so Discord users can receive each other's memories. | `llm/layers.py` (two call sites) |
| F7 | The live database is committed to git, including three dated backups. | `aura-app/.aura/data/` |

### 2.2 Significant

| # | Finding | Where |
|---|---|---|
| F8 | The memory unit is the raw transcript `User: ... Aura: ...`. Retrieval matches Aura's own past wording and injects her old replies as context, unbounded in length. | `orchestrator/coordinator.py` (memory store block), `manager.py` `_format_memories_xml` |
| F9 | Novelty is measured against the five most recent memories. In a long single-topic session later turns score as redundant and can become ephemeral, hidden from retrieval and deleted after 24 h. | `manager.py` `_compute_formation_score` |
| F10 | Thought-cluster chronology picks the latest experience in the conversation (or the latest overall), not the one nearest the memory, then labels its neighbours as before and after "THIS MEMORY". | `manager.py` `_fetch_thought_cluster` |
| F11 | Surprise is always 0.5 because the coordinator never passes `pre_retrieval_ids`. | `coordinator.py`, `manager.py` |
| F12 | Emotional resonance is cosine similarity on all-positive vectors, which is high for any two states sharing the usual active dimensions. The 0.30 weight mostly adds a similar bonus to everything. No damping exists for negative moods. | `manager.py` `_emotion_resonance` |
| F13 | Every retrieved memory gains importance and lifespan, whether or not the reply used it. The update is a non-atomic read then write. | `manager.py` `boost_on_recall` |
| F14 | `related_to` edges are created from cosine similarity, so they duplicate the vector index. | `manager.py` `_create_related_edges` |

### 2.3 Minor

- Vector queries use `ORDER BY vector::similarity::cosine(...)`, a full scan that bypasses the index.
- Several queries build SurrealQL with f-strings containing `user_id` and memory ids.
- The retrieval query is the raw user message, so short replies such as "yes, do that" retrieve noise.
- `_fetch_thought_cluster` issues about five sequential queries per seed while its docstring describes one.
- The memory-failure handler applies an emotion named `concern`, which is not one of the 27 dimensions.
- Cold start injects every core memory in full with no cap.

---

## 3. Design principles

1. **Emotion shapes how she remembers, not what is true.** Emotion sets encoding weight and consolidation priority. It gets only a small, damped role in ranking.
2. **Nothing true is deleted by a clock.** Time lowers a memory's rank. Removal happens only by supersession, abstraction or an explicit request.
3. **The graph stores what vectors cannot.** Identity, time, causality, contradiction, replacement and usage. Similarity stays in the vector index.
4. **Every memory knows where it came from.** Observed, inferred, imagined or external. Imagined content never becomes fact without evidence.
5. **One door in, one door out.** All writes go through the Memory Engine, all reads through the Recall Engine.
6. **Measured, not assumed.** Every mechanism has a switch and a test that shows what it changes.

---

## 4. Data model v2

### 4.1 Node tables

| Table | What it holds | Notes |
|---|---|---|
| `episode` | One conversational turn or event, stored verbatim with user and Aura text in separate fields | Replaces `memory` rows of type episodic. Immutable. The evidence layer. |
| `fact` | One atomic statement in plain language, plus optional subject, predicate and object | Absorbs `insight` rows and semantic memories. This is what gets injected most. |
| `entity` | A person, project, place, tool or concept, with canonical name, aliases and a generated summary | New. |
| `theme` | A cluster of related facts and entities with a generated summary | New. Produced by dreaming. |
| `question` | Something Aura does not know or has found contradictory | New. Feeds curiosity later. |
| `prediction` | Something Aura expects about the user or a task, with an outcome once known | New. The source of real surprise. |
| `experience`, `skill`, `latent_state` | Unchanged | |

### 4.2 Fields on `fact`

| Field | Purpose |
|---|---|
| `content` | The statement as one self-contained sentence |
| `kind` | `fact`, `preference`, `pattern`, `decision`, `event` |
| `provenance` | `observed` (the person said it about themselves or their own world), `hearsay` (someone said it about another person), `inferred` (Aura concluded it), `imagined` (dream or creative output), `external` (tool or web) |
| `visibility` | `owner`, `private:<person>` or `guild:<id>`, see section 4.4 |
| `confidence` | 0 to 1 |
| `valid_from`, `valid_to` | When the statement was true in the world. `valid_to` empty means still true. |
| `recorded_at` | When Aura learned it |
| `embedding` | 768-dim, same model as today |
| `salience` | Encoding weight from emotion and prediction error at the time of learning |
| `pinned` | Protected from archiving, always eligible for the stable context block |
| `use_count`, `last_used_at` | Updated only when a reply demonstrably used the fact |

### 4.3 Edge tables

| Edge | From and to | Meaning |
|---|---|---|
| `derived_from` | fact to episode | Evidence for the fact |
| `about` | fact to entity | What the fact concerns |
| `mentions` | episode to entity | Who or what appeared in the turn |
| `next` | episode to episode | Order within a conversation |
| `supersedes` | fact to fact | The newer statement replaced the older |
| `contradicts` | fact to fact | Unresolved conflict, also raises a `question` |
| `led_to` | episode or fact to episode or fact | Causal link (extends the existing causality weaving) |
| `member_of` | fact or entity to theme | Cluster membership |
| `answers` | fact to question | Resolution of an open question |
| `co_used` | fact to fact | Both were used in the same successful reply. Weight grows with repetition. |
| `abstracted_into` | episode to fact | Kept from today's design |

`related_to` is retired. `co_used` replaces it with a link learned from behaviour.

### 4.4 Speakers and visibility

Aura talks to many people, in the app and across Discord servers, and must tell them apart without leaking one person's private words to another.

- Every person is an `entity` of type `person`, keyed by a stable id (`owner`, `discord_<id>`).
- Every `episode` records its `speaker` (a person entity) and its `venue`: `app`, `dm:<person>` or `guild:<id>/channel:<id>`.
- Every `fact` carries a `visibility` taken from where it was learned:

| Learned in | Visibility | May be recalled |
|---|---|---|
| The app, by the owner | `owner` | only in owner venues |
| A direct message | `private:<person>` | only in a direct message with that person |
| A server channel | `guild:<id>` | anywhere in that server |

- The Recall Engine filters by visibility before ranking. A fact never surfaces in a venue wider than the one it was learned in.
- In a channel Aura can therefore refer to what someone said earlier in that channel, address people by name, and keep a separate picture of each person, while direct messages stay between her and that person.
- **Hearsay.** When speaker Y states something about person X, the fact gets provenance `hearsay` and low confidence. It never overwrites what X said about themselves, and nothing a guest says can change facts about the owner.
- **Emotional influence by venue.** Guests can move her mood only within a capped range per hour, so a public channel cannot push her state, and therefore her memory salience, to extremes.

### 4.5 Indexes

- HNSW vector index on `fact.embedding`, `episode.embedding` and `entity.embedding`, queried with the KNN operator.
- Full-text index with BM25 on `fact.content`, `episode.user_text` and `entity` names and aliases.
- Standard indexes on `user_id`, `valid_to`, `provenance` and `recorded_at`.

The exact index and operator syntax must be checked against the documentation for the installed SurrealDB version before any schema is written.

---

## 5. Write path (Memory Engine)

### 5.1 During the turn (no model call)

1. Store the `episode` with separate `user_text` and `aura_text`, the embedding of the user text plus a short tail of the reply, the emotional signature and the `next` edge from the previous episode.
2. Compute `salience` (section 5.4).
3. Return. Nothing in this step may add more than 30 ms to the turn, excluding the embedding.

### 5.2 After the turn (background, one structured model call)

"Extraction" here means a language-model call that reads a turn and pulls out structured knowledge. It is separate from embedding, which still runs on every episode and fact as it does today.

Run through one of the existing layer models, selectable in the tier settings like the others. Input: the episode plus the two previous turns. Output, as JSON:

- entities mentioned, each with a type and the surface form used
- facts stated or implied, each marked with who asserted it
- questions raised and left open
- predictions Aura made about what happens next

Then, without further model calls where possible:

1. **Entity resolution.** Match by exact alias, then by embedding similarity above a high threshold. Call the model only when two candidates are close. A new alias is added to the existing entity.
2. **Provenance.** A statement by the user about themselves or their world is `observed`. Anything Aura concluded is `inferred`. Aura's own statements in a reply are never stored as facts about the world.
3. **Conflict check.** For each new fact, fetch current facts about the same entities and classify the relation as one of:
   - *duplicate:* raise confidence, add a `derived_from` edge, store nothing new
   - *update:* store the new fact, set `valid_to` on the old one, add `supersedes`
   - *contradiction:* store the new fact, add `contradicts`, create a `question`
   - *new:* store it
4. **Predictions.** When a later turn settles an earlier prediction, record the outcome and the error.

Extraction failures are retried by the dream cycle. An episode is never lost because extraction failed.

### 5.3 Lifecycle

- **Active:** eligible for recall.
- **Superseded:** kept, excluded from recall unless the question is about the past.
- **Archived:** low rank, searched only by the deep path. Replaces time-based soft deletion.
- **Deleted:** only on explicit user request, with everything derived solely from it.

Ephemeral episodes (greetings, acknowledgements) are detected by a cheap rule, not by the formation score, and archived after 7 days.

### 5.4 Salience

`salience = 0.4 * emotional_intensity + 0.4 * prediction_error + 0.2 * depth`

- `emotional_intensity` is the RMS of the active dimensions (those at or above 0.1) of the state minus Aura's rolling baseline, so three strong dimensions score high and the everyday resting state scores near zero.
- `prediction_error` is 0.5 until predictions exist, then the measured error for the turn.
- `depth` is unchanged from today.

Salience affects encoding weight, replay priority in dreaming and how slowly rank decays. It does not gate storage: every episode is stored.

### 5.5 Reconsolidation (experimental, behind a flag)

When a fact is used in a reply, its stored emotional signature moves 5% toward Aura's current state. Memories recalled in calmer moments gradually lose their charge, and vice versa. Must ship with an ablation test.

---

## 6. Read path (Recall Engine)

A new engine at `engines/recall/`. It is the only code allowed to query the memory tables for prompt context.

### 6.1 Interface

```python
class RecallRequest:
    user_id: str
    session_id: str
    user_input: str
    recent_turns: list[Turn]        # last 3 to 6
    emotional_state: EmotionVector
    mode: Literal["chat", "task", "agent"]
    token_budget: int
    latency_budget_ms: int

class ContextPacket:
    stable_blocks: list[Block]      # identity core, pinned facts, user profile
    dynamic_blocks: list[Block]     # recalled facts, evidence, themes, intuition, open items
    abstain: bool                   # nothing relevant was found
    trace: RecallTrace              # every candidate, its channel, scores and fate
```

`llm/layers.py` stops calling `retrieve_for_l3`, `retrieve_relevant` and `get_cold_start_context`, and renders a `ContextPacket`.

### 6.2 Two speeds

- **Fast path:** runs on every turn that needs recall, with no model call. Target under 250 ms at p95 on the reference machine, to be measured.
- **Deep path:** multi-hop, model-driven. Runs when the gate asks for it or when the reasoning layer calls a recall tool.

### 6.3 Fast path stages

1. **Gate.** Decide whether this turn needs recall at all. Greetings, acknowledgements and pure follow-ups to the previous turn skip retrieval and reuse the last packet. Rules first, with a small classifier later if needed.
2. **Query building.** No model call by default:
   - the user input as written
   - the input joined with the previous user turn when the input is short or contains a pronoun with no antecedent
   - entities found by matching known aliases in the last two turns
   - a date range when the input contains a time expression
3. **Candidate channels, run in parallel:**

   | Channel | Finds |
   |---|---|
   | Dense | KNN over `fact` and `episode` embeddings |
   | Lexical | BM25 over fact and episode text, for names, ids and code symbols |
   | Entity | current facts `about` each matched entity |
   | Graph | Personalised PageRank from the hits of the first three channels, over typed edges, on a subgraph capped at 500 nodes |
   | Temporal | facts and episodes inside the detected date range |
   | Working set | the last session summary and open agenda items |

   Graph channel rules: edge weights differ by type (`supersedes` is never followed forward, `co_used` and `about` are strong, `mentions` is weak), and high-degree nodes are damped by degree so a hub such as the user's own entity does not swallow the ranking.
4. **Fusion.** Reciprocal Rank Fusion across channels.
5. **Rerank on features:**
   - drop superseded facts unless the query is about the past
   - drop `imagined` facts unless mode is creative
   - weight by provenance (`observed` above `inferred` above `external`)
   - weight by confidence, salience and a slow rank decay
   - emotional resonance at a weight of 0.10, computed on baseline-subtracted vectors, and capped at zero when Aura's current state is dominated by negative dimensions
   - diversity by maximal marginal relevance so five versions of one fact do not fill the packet
6. **Budgeted assembly:**
   - stable blocks first and in a fixed order, so providers with prompt caching can reuse the prefix
   - facts as single sentences with age, provenance and confidence attached
   - episodes only as evidence, cut to the matched span plus one turn either side, never the whole transcript
   - each block has a share of the token budget, and unused share flows to the next block
7. **Abstention.** If the best candidate scores below a threshold, set `abstain` and inject a one-line note that nothing relevant is stored, so the reply layer does not invent a memory.

### 6.4 Deep path and tools

Tools exposed to the reasoning layer and to agents:

| Tool | Returns |
|---|---|
| `recall(query, filters)` | ranked facts with provenance |
| `timeline(entity or date range)` | ordered episodes and facts |
| `evidence(fact_id)` | the episodes a fact was derived from |
| `what_changed(entity)` | the supersession chain for an entity |
| `pin(fact_id)` and `unpin(fact_id)` | protect or release a fact |

`traverse_timeline` and `fetch_supporting_evidence` are reimplemented on these.

### 6.5 Feedback

After the reply is produced, mark which injected items it used (lexical and embedding overlap between the reply and each item, above a threshold). Then:

- increment `use_count` only for used items, in one atomic update
- strengthen `co_used` between items used together
- items injected and unused five times in a row for similar queries get a small rank penalty

### 6.6 Trace

Every `ContextPacket` trace is kept for the last 200 turns and exposed at `GET /recall/trace/{turn_id}`: the queries built, each candidate with its channel and scores, and why it was kept or dropped. The existing memory debug page shows it.

---

## 7. Dreaming v2

Changes to the existing cycle:

1. **Retry extraction** for episodes that have none.
2. **Prioritised replay.** Choose what to consolidate by `salience * recency`, not by clusters of similar text alone.
3. **Themes.** Detect communities over the fact and entity graph, write a short summary for each as a `theme`, and refresh entity summaries that have new facts.
4. **Archive, do not delete.** Remove the time-based soft delete (F1). Archive superseded facts older than 90 days and ephemeral episodes older than 7 days.
5. **Emotional reprocessing** stays as it is.
6. **Bisociation walks (experimental).** Random walks with restart from recent facts to distant ones. Any link found is stored as a `question` with provenance `imagined`, never as a fact.

---

## 8. Evaluation harness

Built first, before any behaviour changes.

### 8.1 Tools

- **Injectable clock.** All time reads go through one provider so tests can advance days in milliseconds.
- **Scenario runner.** Feeds scripted conversations through the real write path, advances the clock, runs dream cycles, then asks probe questions through the real read path.
- **Judge.** Checks that the gold evidence is in the packet (no model needed) and that the reply is correct (model-graded).

### 8.2 Probe set

At least 60 probes, written from Mai's real usage with names changed:

| Type | Example | Passing means |
|---|---|---|
| Single fact | "What's my dog's name?" after 30 simulated days | gold fact in packet |
| Updated fact | told A, later told B, asked now | B returned, A absent |
| History | same, asked "what was it before?" | A returned as past |
| Temporal | "what did we decide last week?" | only items in range |
| Multi-hop | answer needs two linked facts | both in packet |
| Abstention | never told | `abstain` set, no invented answer |
| Isolation | fact told by X in a direct message, asked by Y or asked in a channel | never returned |
| Shared venue | fact told by X in a channel, asked by Y in that channel | returned, attributed to X |
| Hearsay | Y claims something about X, then X is asked | X's own statement wins |
| Long topic | 40 turns on one subject | facts from turns 30 to 40 retrievable |
| Noise | "ok thanks" | no retrieval performed |

### 8.3 Metrics

- gold evidence recall at packet level
- reply accuracy
- stale-fact rate (a superseded fact presented as current)
- irrelevant items per packet
- tokens injected per turn
- fast-path latency, p50 and p95

### 8.4 Baselines

1. The current system, measured before any change.
2. Long-context dump: the most recent history that fits the budget, with no retrieval. Published comparisons show this can beat memory systems at small history sizes, so v2 has to earn its complexity against it.

### 8.5 Ablations

Each of these has a config flag and a test run with it off: emotional resonance, graph channel, lexical channel, query joining, reconsolidation, `co_used` reinforcement, the recall gate.

---

## 9. Fresh start

Development runs against a new, empty database. Nothing is migrated from the current one.

1. Remove `aura-app/.aura/` from the repository and its history, and add it to `.gitignore`.
2. Create the v2 schema in a fresh namespace.
3. The old tables and the code paths that read them (`memory`, `insight`, `related_to`) are deleted once the v2 probes pass, not kept in parallel.
4. Seed data for development comes from the scenario runner, never from real conversations.

## 10. Milestones

Each milestone ends with tests green, the probe metrics recorded, and no regression against the previous milestone.

| Milestone | Scope | Gate |
|---|---|---|
| M0 | Remove `.aura/` from git and its history, add to `.gitignore`. Injectable clock. Scenario runner. Probe set. Baseline numbers for both baselines. | Baselines recorded |
| M1 | Fixes F1 to F6 and F9 to F13 in the existing code. Parameterise queries. Cap injected length. | 30-day single-fact probes pass, isolation probes pass |
| M2 | Recall Engine skeleton. One entry point wrapping today's stores, with budget, deduplication and trace. All five injectors routed through it. No new retrieval logic. | Same accuracy as M1, fewer tokens per turn |
| M3 | HNSW and BM25 indexes, parallel channels, fusion, query building, gate, abstention | Noise and abstention probes pass |
| M4 | Schema v2 in a fresh database: `episode`, `fact`, `entity`. Extraction, entity resolution, provenance, supersession, speakers and visibility. | Updated-fact, history and visibility probes pass, stale-fact rate under 2% |
| M5 | Entity, graph and temporal channels. Recall tools. Feedback loop. | Multi-hop and temporal probes pass |
| M6 | Dreaming v2: retry, prioritised replay, themes, archive | Long-topic probes pass, memory stable over 90 simulated days |
| M7 | Experimental: reconsolidation, `co_used`, predictions, questions, bisociation. Each flagged. | Each shows a measured effect or is removed |

---

## 11. Rules for the coding agent

1. Build M0 before touching behaviour. No change ships without a probe that would catch its regression.
2. Read the SurrealDB documentation for the installed version before writing any index, KNN or full-text query. Do not write query syntax from memory.
3. All queries are parameterised. No f-string or string concatenation with ids or user input.
4. Only `engines/recall/` may read memory tables for prompt context. Only `engines/memory/` may write them.
5. Never store Aura's own reply text as a fact about the world.
6. Never promote `imagined` content to `fact` without an `observed` or `external` source.
7. Every new mechanism gets a config flag and an ablation test in the same change.
8. Weights and thresholds live in config, not in source.
9. No change may add a model call to the fast path.
10. When a requirement here conflicts with existing behaviour and it is unclear which is intended, stop and ask.

---

## 12. Open items for Mai

1. Which layer model handles extraction by default? A weak model here pollutes the graph, so the recommendation is a mid-tier model, not the cheapest.
2. Which facts should be pinned on day one?
3. `llm/embeddings.py` loads a local `nomic-embed-text-v1.5` model. If a paid embedding model is meant to be in use, the config path that selects it needs checking.

## 13. Research this draws on

- Temporal knowledge graphs with validity windows on facts, and tiers of episodes, entities and communities: Zep and Graphiti. https://dev.to/jonathanfarrow/the-10-best-ai-memory-layers-for-agents-in-2026-448e
- Graph retrieval by Personalised PageRank over facts and passages, with filtering before seeding: HippoRAG 2. https://arxiv.org/pdf/2502.14802
- The hub problem in graph memory and type-aware PageRank combined with nearest-neighbour search: GAAMA. https://arxiv.org/html/2603.27910
- Memories that link and evolve after writing: A-MEM. https://arxiv.org/pdf/2502.12110
- Provenance-aware memory that abstains when evidence is missing: Agent Zero Memory. https://www.alphaxiv.org/abs/2608.29606
- Fact-based memory against long-context inference, the source of baseline 2: https://arxiv.org/html/2603.04814
- Benchmarks and why vendor numbers disagree: https://mem0.ai/blog/state-of-ai-agent-memory-2026
