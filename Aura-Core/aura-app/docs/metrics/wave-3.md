# Wave 3 review (section 1.4)

Reviewed by the supervisor on branch overnight-wave-0-1, 2026-11-20.

## 1. Tests
- Python suite: 655 passed, 3 skipped (the skips are two symlink tests on Windows and the real-OpenCode integration test, which runs only with `AURA_OPENCODE_REAL_COMMAND` set; it passed when run against v2.3.2).
- Frontend: `npm test` 67 passed (new runner, W3-34); `npm run build` passes.
- Probe set: still a placeholder; scenario tests stand in for the probes.

## 2. Milestones
| Milestone | Cards | Result |
|---|---|---|
| M3 recall channels, fusion, gate, abstention | W3-01..W3-08 | done; fast path p50 17.7 ms, p95 19.8 ms on the test engine (docs/metrics/m3.md) |
| M4 memory v2 | W3-09..W3-18, W3-15a | done; stale-fact rate 0% over a 40-turn script with 10 updates (docs/metrics/m4.md) |
| E2, E3 appraisal, causes, state interface | W3-19..W3-26 | done; T15 signature similarity -0.17 (docs/metrics/e2e3.md) |
| G2 OpenCode client | W3-27, W3-28 | done; v2.3.2 pinned, spec saved in docs/opencode/ |
| G3 delegation | W3-29..W3-33, W3-31a, W3-31b | done; agents load through an Aura-owned config dir, checked against the real binary |
| V1 (without the MetaHuman steps) to V4 | W3-34..W3-38 | done behind `NEXT_PUBLIC_AVATAR_STAGE=1`; placeholder head; three not upgraded; asset build script (T13, T14) waits for a real asset |

All new behaviour is behind flags that are off by default; docs/FOR_MAI.md lists them.

## 3. What the review caught
Workers' tests passed in several cards where the code was wrong; each was fixed in a later card or by the supervisor:
- fake servers written to match wrong assumptions (OpenCode output lines in W3-27/W3-31a; the config PATCH in W3-31, which a real v2.3.2 server rejects);
- a SCHEMAFULL table missing a field the code wrote (`emotion_event.size`), invisible to fake databases;
- double scaling (appraisal intensity), double counting (the fear row), an always-firing row (boredom);
- the L4 switch ignored by message appraisal; delegation facts stored as `observed` instead of `external`;
- a test fixture that set the global clock to `None` and broke later tests;
- the build plan briefly held three copies of W3-01..W3-31a (a supervisor script bug, fixed in 09743a4).

Process changes made during the wave: workers no longer run tests or commit (the supervisor does); the card runner has a watchdog for OpenCode startup hangs and stalls; anything that talks to an external program is checked against the real program before acceptance.

## 4. Next: wave 4, in section 5 order
M5 and M6 (graph and temporal retrieval, recall tools, feedback, dreaming v2), E4 and E5 (mood, relationships), B1 to B5, G4 to G6, V5 to V7.
