# Wave 2 review (section 1.4)

Reviewed by the supervisor on branch overnight-wave-0-1, 2026-11-20.

## 1. Test suite and probes
- Full suite: 261 passed (pytest from Aura-Core/aura-app) at e1e43fc.
- Frontend: `npm ci` then `npm run build` passes after W2-25.
- Probe set: still a placeholder (docs/metrics/probes/README.md). It has to be written from Mai's real usage, so no probe metrics are recorded for this wave. The scenario runner (W2-01) stands in for it, and the M3 cards add noise, abstention and latency scenarios.

## 2. Diffs against cards
Every card diff was read against its card. Out-of-scope work was rejected or reverted (W2-29 attempt 1, BF-03 attempt 1, partial W2-30 and W2-32 attempts lost to provider failures).

## 3. Milestones
| Milestone | Cards | Status |
|---|---|---|
| M0 remainder: scenario runner | W2-01, W2-27 | done |
| B0 one turn pipeline | W2-02..W2-11 | done |
| SurrealDB query fixes found by the runner | W2-12, W2-13, W2-26, BF-01 | done |
| M2 Recall Engine skeleton | W2-14..W2-24 | done |
| V0 remove the VRM avatar | W2-25 | done on 2026-11-20, after Mai decided to remove VRM without restoring its missing lib files |
| G1 tool registry and the single tool loop | W2-28..W2-38 | done |
| Bug fixes | BF-01..BF-07 | done |
| M0 remainder: probe set | none | needs Mai |

## 4. Done-when checks and notes for Mai
- W2-20 changes behaviour on purpose: retrieval runs once per turn with the real user id, and the cold-start and latent blocks reach the prompt.
- W2-25: the last check (open `/chat` and see the spiral at the bottom right) needs a person at the screen. `@gltf-transform/core` is unused but not listed by the PRD, so it was left in `package.json`.
- W2-33 and W2-34: the supervisor's done-when greps for `counts` also match the prompt sentence "even small progress counts" (prose, not code), and the W2-34 grep for `_remove_tool_calls_from_text` matches a docstring in `tool_loop.py` that says the function was copied from it. Both are wording in the cards, not leftovers.
- W2-36 and W2-37: native function calling is behind `AURA_L3_NATIVE_TOOLS`, off by default. Follow-up before turning it on: in streaming mode, if the native call fails after some text was already streamed, the fallback reruns the round as text and that text would be shown twice.
- W2-38 changes routing on purpose: keywords no longer force tool use, and only learned trigger phrases seed a forced tool call. The model now decides from the offered tools (W2-35).
- Remaining direct time reads (for example `DreamingEngine.tick`, parts of `manager.py`) are still to be carded with the next clock pass.

## 5. Next: wave 3, in section 5 order
M3 is carded (W3-01..W3-08). Every M3 mechanism ships behind a flag that is off by default; turning them on is Mai's decision after W3-08 records the noise, abstention and latency results.
