# Probe set (placeholder)

The memory PRD (section 8.2) needs at least 60 probes before milestone M0 is complete. They are deliberately not written yet: they must come from Mai.

## What a probe needs
Written from Mai's real usage of Aura, with names changed. Each probe is a short scripted scenario for `tests/scenarios/runner.py` (W2-01): the turns that teach something, the simulated days between them, any dream cycles, then the question and its gold answer.

## Types to cover (PRD 8.2)
Single fact, updated fact, history, temporal, multi-hop, abstention, isolation, shared venue, hearsay, long topic, noise.

## Format
One Python module per type under `tests/scenarios/probes/`, each exposing a list of `Scenario` objects (see `runner.py`). The judge (gold evidence in the packet, plus a model-graded reply) is a separate card once probes exist.

## Why not generated overnight
Probes invented by a model would test the model's idea of Aura rather than Mai's real usage, and would bias every metric that follows.
