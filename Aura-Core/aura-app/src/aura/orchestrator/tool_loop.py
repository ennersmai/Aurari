"""
Single Tool Loop (W2-31).

Replaces the two parsing loops in the coordinator with a single,
testable loop that enforces the tool contract:
- Every tool call goes through tool_executor.execute_and_feedback
- The loop does not check roles, does not call execute_tool_call
- Role and approval checks stay in the executor's single gate (rule 4)
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Literal

from aura.config import settings

logger = logging.getLogger(__name__)


# Used only on the flag-off path (tool_loop_budgets_enabled False). P2-41 removes
# it from the budgeted path; delete it when the flag becomes the default.
MAX_ROUNDS_SUFFIX = "\n\n(Stopped after max tool rounds; ask me to continue if needed.)"
ROUND_SEPARATOR = "\n\n"


@dataclass
class LoopEvent:
    """Event emitted by the tool loop."""
    kind: Literal["delta", "separator", "done"]
    text: str
    # Set on the "done" event of a budgeted loop (P2-41): rounds, elapsed_seconds,
    # cost_usd, stop_reason. None on the flag-off path.
    stats: dict | None = None


@dataclass
class NativeCalls:
    """Native tool calls reported by a round (W2-37).

    A round generator may yield this once, last, instead of leaving the calls
    inside its text. The calls use the executor's
    ``{"tool": ..., "arguments": {...}}`` shape.
    """
    calls: list[dict]


@dataclass
class RoundUsage:
    """Cost of a round in USD, yielded by a round generator when the provider reports it (P2-41)."""
    cost: float


BUDGET_NOTE = (
    "You have used most of this turn's budget. Finish now: say what you did, "
    "what is left, and how to continue."
)
BUDGET_NOTE_TITAN = BUDGET_NOTE[:-1] + ", or plan the rest with plan_task."

_STOP_REASON_TEXT = {
    "time": "the time budget for this turn is used up",
    "cost": "the cost budget for this turn is used up",
    "no_progress:repeat_call": "the same tool was called with the same arguments three times",
    "no_progress:consecutive_failures": "three tool calls in a row failed",
    "no_progress:repeated_results": "three rounds in a row returned results already seen",
    "safety_breaker": "the safety limit on tool rounds was reached",
}

_cost_unreported_logged = False


RoundFn = Callable[[str, int], AsyncIterator["str | NativeCalls"]]  # (loop_input, round_idx) -> text chunks or one NativeCalls


def strip_tool_calls(text: str) -> str:
    """
    Remove tool call JSON blocks from text to clean up the response.

    Copied verbatim from Orchestrator._remove_tool_calls_from_text.
    """
    # Remove JSON code blocks that look like tool calls
    text = re.sub(r'```(?:json)?\s*\{[^{}]*"tool"[^{}]*\}\s*```', '', text, flags=re.DOTALL)

    # Remove inline tool call JSON objects
    text = re.sub(r'\{[^{}]*"tool"[^{}]*\}', '', text, flags=re.DOTALL)

    # Clean up extra whitespace
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)

    return text.strip()


def build_loop_input(user_input: str, blocks: list[str]) -> str:
    """Build the L3 input for a tool loop round."""
    return user_input if not blocks else f"{user_input}\n\n[Tool Execution Results]\n" + "\n\n".join(blocks)


def _call_succeeded(results: str, tool_name: str) -> bool:
    """Whether a tool's result in the executor's joined text looks successful."""
    # The executor formats failures as "❌ Tool {tool_name} failed:".
    if results.lstrip().startswith("❌"):
        return False
    return f"❌ Tool {tool_name} failed" not in results


def _call_key(call: dict) -> str:
    """Tool name plus normalised arguments, for the repeat-call guard."""
    try:
        args = json.dumps(call.get("arguments", {}), sort_keys=True, default=str)
    except (TypeError, ValueError):
        args = repr(call.get("arguments"))
    return f"{call.get('tool', 'unknown')}|{args}"


async def _run_budgeted(
    *,
    user_input: str,
    generate_round: RoundFn,
    generate_final: "RoundFn | None",
    tool_executor: Any,
    requester_role: str,
    venue: str,
    breaker: int,
    seed_results: str | None,
    on_tool_result: Callable[[str, bool], Awaitable[None]] | None,
    budget_seconds: float,
    budget_usd: float,
    allow_task_graph: bool,
    monotonic: Callable[[], float],
) -> AsyncIterator[LoopEvent]:
    """Tool loop ended by budgets and lack of progress, not a round count (P2-41)."""
    global _cost_unreported_logged

    blocks: list[str] = []
    if seed_results:
        blocks.append(f"[Seed]\n{seed_results}")

    start = monotonic()
    cost = 0.0
    rounds = 0
    stop: str | None = None
    note_sent = False
    call_counts: dict[str, int] = {}
    fail_streak = 0
    seen_hashes: set[str] = set()
    dup_streak = 0
    final_text = ""
    last_round_text = ""

    def elapsed() -> float:
        return monotonic() - start

    for round_idx in range(1, breaker + 1):
        if round_idx > 1:
            if elapsed() >= budget_seconds:
                stop = "time"
                break
            if budget_usd > 0 and cost >= budget_usd:
                stop = "cost"
                break
            yield LoopEvent("separator", ROUND_SEPARATOR)

        loop_input = build_loop_input(user_input, blocks)
        if not note_sent and (
            elapsed() >= 0.8 * budget_seconds or (budget_usd > 0 and cost >= 0.8 * budget_usd)
        ):
            note_sent = True
            note = BUDGET_NOTE_TITAN if allow_task_graph else BUDGET_NOTE
            loop_input += f"\n\n[System note]\n{note}"

        round_text = ""
        native_calls: list[dict] | None = None
        reported_cost = False
        rounds += 1

        async for chunk in generate_round(loop_input, round_idx):
            if isinstance(chunk, NativeCalls):
                native_calls = chunk.calls
                continue
            if isinstance(chunk, RoundUsage):
                cost += max(0.0, float(chunk.cost or 0.0))
                reported_cost = True
                continue
            yield LoopEvent("delta", chunk)
            round_text += chunk
        last_round_text = round_text

        if not reported_cost and budget_usd > 0 and not _cost_unreported_logged:
            _cost_unreported_logged = True
            logger.info(
                "Tool loop: the provider did not report cost for a round; the cost "
                "budget cannot be enforced for rounds without cost data."
            )

        calls = native_calls if native_calls is not None else tool_executor.extract_tool_calls(round_text)
        if not calls:
            final_text = strip_tool_calls(round_text)
            break

        results = await tool_executor.execute_and_feedback(
            calls, requester_role=requester_role, venue=venue
        )
        if not results:
            final_text = strip_tool_calls(round_text)
            break

        for call in calls:
            tool_name = call.get("tool", "unknown")
            ok = _call_succeeded(results, tool_name)
            if on_tool_result is not None:
                await on_tool_result(tool_name, ok)
            fail_streak = 0 if ok else fail_streak + 1
            key = _call_key(call)
            call_counts[key] = call_counts.get(key, 0) + 1
            if stop is None:
                if call_counts[key] >= 3:
                    stop = "no_progress:repeat_call"
                elif fail_streak >= 3:
                    stop = "no_progress:consecutive_failures"

        digest = hashlib.sha256(results.encode("utf-8", "replace")).hexdigest()
        if digest in seen_hashes:
            dup_streak += 1
        else:
            dup_streak = 0
            seen_hashes.add(digest)
        if stop is None and dup_streak >= 3:
            stop = "no_progress:repeated_results"

        blocks.append(f"[Round {round_idx}]\n{results}")
        if stop is not None:
            break
    else:
        stop = "safety_breaker"
        logger.error(
            "INCIDENT: tool loop hit the safety breaker after %d rounds (elapsed %.1fs, cost $%.4f)",
            rounds, elapsed(), cost,
        )

    stats = {
        "rounds": rounds,
        "elapsed_seconds": round(elapsed(), 3),
        "cost_usd": round(cost, 6),
        "stop_reason": stop,
    }

    if stop is not None:
        logger.warning("Tool loop stopped: %s (%s)", stop, stats)
        final_input = (
            build_loop_input(user_input, blocks)
            + "\n\n[System note]\nTool use for this turn has stopped because "
            + _STOP_REASON_TEXT.get(stop, stop)
            + ". Do not call tools. Say what you did, what is left, and how to continue."
        )
        yield LoopEvent("separator", ROUND_SEPARATOR)
        final_round = generate_final or generate_round
        text = ""
        try:
            async for chunk in final_round(final_input, rounds + 1):
                if isinstance(chunk, (NativeCalls, RoundUsage)):
                    continue
                yield LoopEvent("delta", chunk)
                text += chunk
            final_text = strip_tool_calls(text)
        except Exception as exc:  # the closing call must not lose the turn
            logger.error("Tool loop closing call failed: %s", exc)
            final_text = strip_tool_calls(text or last_round_text)

    yield LoopEvent("done", final_text, stats)


async def run_tool_loop(
    *,
    user_input: str,
    generate_round: RoundFn,
    tool_executor: Any,
    requester_role: str,
    venue: str = "app",
    max_rounds: int | None = None,   # None -> settings.tool_loop_max_rounds
    seed_results: str | None = None,
    on_tool_result: Callable[[str, bool], Awaitable[None]] | None = None,
    turn_budget_seconds: int | None = None,
    turn_budget_usd: float | None = None,
    generate_final: "RoundFn | None" = None,
    allow_task_graph: bool = False,
    monotonic: Callable[[], float] = time.monotonic,
) -> AsyncIterator[LoopEvent]:
    """
    Run the single tool loop.

    Args:
        user_input: The original user input.
        generate_round: Async function that takes (loop_input, round_idx) and yields
            text chunks, optionally ending with one :class:`NativeCalls` marker.
        tool_executor: ToolExecutor instance with extract_tool_calls and execute_and_feedback.
        requester_role: "owner" | "trusted" | "guest" passed to execute_and_feedback.
        max_rounds: Override for settings.tool_loop_max_rounds.
        seed_results: Optional seed results from a forced tool call (pre-loop).
        on_tool_result: Optional callback called once per executed tool call with
            (tool_name, success). Called when the executor reports per-call success.
        turn_budget_seconds: The tier's tool-use time budget per turn (P2-03).
            Enforced only with ``tool_loop_budgets_enabled`` (P2-41); None means
            ``settings.tool_loop_default_budget_seconds``.
        turn_budget_usd: The tier's cost budget per turn. Same flag; None means
            ``settings.tool_loop_default_budget_usd``; 0 or less means no cost cap.
        generate_final: Round function for the closing no-tools call when a guard
            stops the loop. None reuses ``generate_round`` (its tool calls are ignored).
        allow_task_graph: Titan only; adds the plan_task sentence to the 80% note.
        monotonic: Clock for the time budget (injectable for tests).

    With ``tool_loop_budgets_enabled`` on, ``max_rounds`` is only the safety breaker
    (default ``settings.tool_loop_safety_rounds``); the turn ends on a budget, the
    no-progress guard, or when the model stops calling tools.

    Yields:
        LoopEvent with kind "delta" for text chunks, "separator" for round separators,
        and "done" for the final accumulated response (once, last).
    """
    if settings.tool_loop_budgets_enabled:
        async for ev in _run_budgeted(
            user_input=user_input,
            generate_round=generate_round,
            generate_final=generate_final,
            tool_executor=tool_executor,
            requester_role=requester_role,
            venue=venue,
            breaker=max_rounds if max_rounds is not None else settings.tool_loop_safety_rounds,
            seed_results=seed_results,
            on_tool_result=on_tool_result,
            budget_seconds=(turn_budget_seconds if turn_budget_seconds is not None
                            else settings.tool_loop_default_budget_seconds),
            budget_usd=(turn_budget_usd if turn_budget_usd is not None
                        else settings.tool_loop_default_budget_usd),
            allow_task_graph=allow_task_graph,
            monotonic=monotonic,
        ):
            yield ev
        return

    if max_rounds is None:
        max_rounds = settings.tool_loop_max_rounds

    blocks: list[str] = []
    if seed_results:
        blocks.append(f"[Seed]\n{seed_results}")

    final_text = ""

    for round_idx in range(1, max_rounds + 1):
        if round_idx > 1:
            yield LoopEvent("separator", ROUND_SEPARATOR)

        loop_input = build_loop_input(user_input, blocks)
        round_text = ""
        native_calls: list[dict] | None = None

        async for chunk in generate_round(loop_input, round_idx):
            if isinstance(chunk, NativeCalls):
                native_calls = chunk.calls
                continue
            yield LoopEvent("delta", chunk)
            round_text += chunk

        if native_calls is not None:
            calls = native_calls
        else:
            calls = tool_executor.extract_tool_calls(round_text)
        if not calls:
            final_text = strip_tool_calls(round_text)
            break

        results = await tool_executor.execute_and_feedback(
            calls, requester_role=requester_role, venue=venue
        )
        if not results:
            final_text = strip_tool_calls(round_text)
            break

        # Report per-call success to on_tool_result callback if provided
        # The executor's execute_and_feedback returns joined text; we consider a call
        # successful if the result block does not start with an error marker.
        # The executor uses "❌ Tool <name> failed:" as an error prefix for tool failures.
        if on_tool_result is not None:
            for call in calls:
                tool_name = call.get("tool", "unknown")
                await on_tool_result(tool_name, _call_succeeded(results, tool_name))

        blocks.append(f"[Round {round_idx}]\n{results}")
    else:
        # Every round had tool calls; hit max_rounds
        final_text = strip_tool_calls(round_text) + MAX_ROUNDS_SUFFIX
        yield LoopEvent("delta", MAX_ROUNDS_SUFFIX)

    yield LoopEvent("done", final_text)