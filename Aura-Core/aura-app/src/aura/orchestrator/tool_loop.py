"""
Single Tool Loop (W2-31).

Replaces the two parsing loops in the coordinator with a single,
testable loop that enforces the tool contract:
- Every tool call goes through tool_executor.execute_and_feedback
- The loop does not check roles, does not call execute_tool_call
- Role and approval checks stay in the executor's single gate (rule 4)
"""

import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Literal

from aura.config import settings


MAX_ROUNDS_SUFFIX = "\n\n(Stopped after max tool rounds; ask me to continue if needed.)"
ROUND_SEPARATOR = "\n\n"


@dataclass
class LoopEvent:
    """Event emitted by the tool loop."""
    kind: Literal["delta", "separator", "done"]
    text: str


RoundFn = Callable[[str, int], AsyncIterator[str]]  # (loop_input, round_idx) -> text chunks


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


async def run_tool_loop(
    *,
    user_input: str,
    generate_round: RoundFn,
    tool_executor: Any,
    requester_role: str,
    max_rounds: int | None = None,   # None -> settings.tool_loop_max_rounds
    seed_results: str | None = None,
) -> AsyncIterator[LoopEvent]:
    """
    Run the single tool loop.

    Args:
        user_input: The original user input.
        generate_round: Async function that takes (loop_input, round_idx) and yields text chunks.
        tool_executor: ToolExecutor instance with extract_tool_calls and execute_and_feedback.
        requester_role: "owner" | "trusted" | "guest" passed to execute_and_feedback.
        max_rounds: Override for settings.tool_loop_max_rounds.
        seed_results: Optional seed results from a forced tool call (pre-loop).

    Yields:
        LoopEvent with kind "delta" for text chunks, "separator" for round separators,
        and "done" for the final accumulated response (once, last).
    """
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

        async for chunk in generate_round(loop_input, round_idx):
            yield LoopEvent("delta", chunk)
            round_text += chunk

        calls = tool_executor.extract_tool_calls(round_text)
        if not calls:
            final_text = strip_tool_calls(round_text)
            break

        results = await tool_executor.execute_and_feedback(calls, requester_role=requester_role)
        if not results:
            final_text = strip_tool_calls(round_text)
            break

        blocks.append(f"[Round {round_idx}]\n{results}")
    else:
        # Every round had tool calls; hit max_rounds
        final_text = strip_tool_calls(round_text) + MAX_ROUNDS_SUFFIX
        yield LoopEvent("delta", MAX_ROUNDS_SUFFIX)

    yield LoopEvent("done", final_text)