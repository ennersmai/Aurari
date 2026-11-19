"""Query building for the Recall Engine fast path (M3, W3-03).

Memory PRD 6.3 step 2 turns a user input into the texts the candidate
channels search with.  This module implements the first two query kinds:

* the user input as written, and
* the input joined with the previous user turn when the input is short or
  contains a pronoun whose antecedent is probably in that turn.

The lexical text is the dense text with English stop words removed, so a
BM25 search is not dominated by words that nearly every memory contains.

The other two query kinds in 6.3 step 2 — entities found by matching known
aliases in the last two turns, and a date range from a time expression — wait
for milestones M4 and M5 and are not built here.

Nothing in this module calls a model or the database.
"""

import re
import string
from dataclasses import dataclass

from aura.config import settings


@dataclass
class RecallQueries:
    """The query texts built for one turn (PRD 6.3 step 2)."""

    dense_text: str
    lexical_text: str
    joined: bool


# Pronouns whose antecedent may be in the previous user turn (PRD 6.3 step 2).
_PRONOUNS = frozenset(
    {
        "it",
        "this",
        "that",
        "they",
        "them",
        "he",
        "she",
        "him",
        "her",
        "those",
        "these",
    }
)

_PRONOUN_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_PRONOUNS)) + r")\b",
    re.IGNORECASE,
)

# About 100 common English words, including the question words and the
# pronouns above.  These are dropped from the lexical query only.
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "after",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "may",
        "me",
        "might",
        "mine",
        "more",
        "most",
        "must",
        "my",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "only",
        "or",
        "other",
        "our",
        "out",
        "over",
        "shall",
        "she",
        "should",
        "so",
        "some",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "up",
        "us",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "whether",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


def _previous_user_turn(
    user_input: str, recent_turns: list[dict[str, str]]
) -> str | None:
    """Return the last user turn's content that is not the current input.

    The pipeline passes history that may already end with the current input,
    so an entry equal to ``user_input`` is skipped.
    """
    for turn in reversed(recent_turns):
        if turn.get("role") != "user":
            continue
        content = turn.get("content")
        if content is not None and content != user_input:
            return content
    return None


def _lexical_text(dense_text: str) -> str:
    """Remove stop words and collapse whitespace."""
    kept = [
        token
        for token in dense_text.split()
        if token.strip(string.punctuation).lower() not in _STOP_WORDS
    ]
    return " ".join(kept)


def build_queries(
    user_input: str, recent_turns: list[dict[str, str]]
) -> RecallQueries:
    """Build the dense and lexical query texts for one turn.

    The input is joined with the previous user turn when that turn exists and
    either the input is at most ``settings.recall_query_join_max_words`` words
    long or it contains a pronoun as a whole word.  No model call is made.
    """
    previous = _previous_user_turn(user_input, recent_turns)

    short_input = len(user_input.split()) <= int(
        settings.recall_query_join_max_words
    )
    has_pronoun = bool(_PRONOUN_RE.search(user_input))
    joined = previous is not None and (short_input or has_pronoun)

    dense_text = f"{previous}\n{user_input}" if joined else user_input

    return RecallQueries(
        dense_text=dense_text,
        lexical_text=_lexical_text(dense_text),
        joined=joined,
    )