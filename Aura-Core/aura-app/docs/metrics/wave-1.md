# Wave 0-1 review (section 1.4)

Reviewed by the overnight supervisor on branch overnight-wave-0-1.

## 1. Test suite and probes
- Full suite: 47 passed (pytest from Aura-Core/aura-app).
- Probe set: not written yet (M0 remainder, frontier). No probe metrics to record.

## 2. Diffs against cards
Every card diff was read against its card. Nothing outside card scope was accepted.
Scans over the whole wave: no new f-string values in SQL (the one f-string builds `$idN` placeholders), no direct time reads outside `clock.py`, no dependency changes.

## 3. Done-when checks and notes for Mai
- W0-01: satisfied by repository setup. `.aura/` was ignored from the first commit and never pushed, so this repository needs no history purge.
- W0-04 / W0-05: the recording tests rewrite `docs/metrics/*_before.json` on every pytest run. W1-06 briefly committed post-change values; restored in bccf884. Suggested follow-up card: write the file only when it does not exist.
- W1-05: landed in two commits (f0bae54 code, 10809b4 test) because an earlier long session was stopped mid-card.
- W1-10: `set_core` catches every database error and only logs it, so the pin and unpin routes report success even when the write fails. It follows the existing style in manager.py; a later card should surface the error.
- W1-13: the concurrency test uses a fake database with a lock. Atomicity on a real SurrealDB rests on the single UPDATE and is not tested against a live server.
- W1-16: the done-when grep still matches a comment in a different handler (around line 1529). Left unchanged on purpose (rule 3).

## 4. Metrics
Baselines: docs/metrics/emotion_before.json and docs/metrics/memory_before.json, frozen at W0-04 and W0-05.

## 5. Wave 2 status (dependency order, section 5)
| Milestone | Status tonight |
|---|---|
| B0 merge `process_query` and `stream_query` | frontier, listed for Mai. Blocks M2 and G1. |
| M2 Recall Engine skeleton | blocked on B0 |
| G1 tool registry and single tool loop | blocked on B0, and touches tool execution (excluded tonight) |
| V0 remove the VRM avatar | held: Mai asked to leave avatar work for now |
| M0 remainder: scenario runner | carded as W2-01 (bulk) |
| M0 remainder: probe set (60+ probes from real usage) | frontier, needs Mai: written from real usage |
