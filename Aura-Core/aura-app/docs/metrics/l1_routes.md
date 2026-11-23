# L1 route accuracy (P2-06)

Status: not yet run.

Fixture: `tests/fixtures/l1_routes.json` (25 messages, 5 per route: chat, tool, think, task, teach).
The unit tests only check parsing and coordinator plumbing with a mocked L1. This table needs a
manual run against each stack's real L1 model.

Command (needs real API keys; set `AURA_MODEL_STACK_INDEX` per stack, 0 Lean, 1 Core, 2 Titan; run from `aura-app`):

```
AURA_L1_ROUTES_ENABLED=true AURA_MODEL_STACK_INDEX=0 .venv/Scripts/python.exe -c "import asyncio,json; from aura.llm.layers import LLMLayers; f=json.load(open('tests/fixtures/l1_routes.json')); L=LLMLayers(); r=asyncio.run(asyncio.gather(*[L.l1_classify_intent(x['message']) for x in f])); ok=sum(a.get('route')==x['route'] for a,x in zip(r,f)); print(ok,'/',len(f)); [print('MISS',x['route'],'->',a.get('route'),x['message']) for a,x in zip(r,f) if a.get('route')!=x['route']]"
```

If `LLMLayers()` needs constructor arguments in your setup, pass the same ones the app uses.
The vector fast path may answer "tool" for some messages; that is expected.

| Stack | L1 model | Accuracy (of 25) | Per-route misses | Date |
|---|---|---|---|---|
| Lean (0) | not yet run | not yet run | | |
| Core (1) | not yet run | not yet run | | |
| Titan (2) | not yet run | not yet run | | |
