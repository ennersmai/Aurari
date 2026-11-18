"""Recall Engine — block renderers.

The renderers that turn a block's payloads into the prompt XML. W2-16 moves the
insights rendering out of ``aura.llm.layers`` so that the Recall Engine owns it
(insights are one of the five injectors). The output is byte-for-byte the string
today's ``# 1.1 Knowledge / Insights`` block appends, so moving it changes
nothing the model sees.
"""

from typing import Any


def render_insights(insights: list[Any], mastery_level: float) -> str:
    """Render the ``<relevant_knowledge>`` block for ``insights``.

    Returns exactly the string today's block appends:

    - ``"<relevant_knowledge>\\n"``
    - the PRIORITY instruction line
    - one ``<insight ...>`` line per item
    - the ``<mastery .../>`` line when ``mastery_level > 0.7``
    - ``"</relevant_knowledge>\\n\\n"``

    The caller passes the list already cut to ``[:8]``; the renderer does not cut
    it again. Returns ``""`` when ``insights`` is empty.
    """
    if not insights:
        return ""

    text = "<relevant_knowledge>\n"
    text += (
        "  <instruction>PRIORITY: The following facts are specific to this "
        "user/session. Prioritize these over your generic training or core "
        "narrative defaults.</instruction>\n"
    )
    for insight in insights:
        text += (
            f"  <insight type='{insight.type}' confidence='{insight.confidence:.2f}'>"
            f"{insight.content}</insight>\n"
        )

    if mastery_level > 0.7:
        text += f"  <mastery level='{mastery_level:.2f}'/>\n"
    text += "</relevant_knowledge>\n\n"
    return text
