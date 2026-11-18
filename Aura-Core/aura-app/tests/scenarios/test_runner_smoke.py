"""Smoke test for the scenario runner (card W2-01).

Runs one scenario end-to-end through the real MemoryManager and
DreamingEngine over an in-memory embedded SurrealDB, and asserts only
that the run completes and returns exactly one probe result.

Per the card: do **not** assert that the gold string was found — this
records today's behaviour, it does not grade it.
"""

import pytest

from tests.scenarios.runner import Probe, ProbeResult, Scenario, Turn, run


@pytest.mark.asyncio
async def test_runner_smoke_completes_and_returns_one_result():
    scenario = Scenario(
        name="biscuit_smoke",
        turns=[
            Turn(
                user_id="alice",
                conversation_id="conv-1",
                text="My dog's name is Biscuit",
                at_day=0.0,
            ),
        ],
        dream_at_days=[1.0],
        probes=[
            Probe(
                user_id="alice",
                question="What's my dog's name?",
                gold=["Biscuit"],
                at_day=30.0,
            ),
        ],
    )

    results = await run(scenario)

    # The run completed and returned exactly one probe result.
    assert isinstance(results, list)
    assert len(results) == 1
    assert isinstance(results[0], ProbeResult)
    assert results[0].question == "What's my dog's name?"
    assert set(results[0].gold_found.keys()) == {"Biscuit"}
    assert isinstance(results[0].packet_chars, int)
