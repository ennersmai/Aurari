"""W3-03: Recall Engine query building.

Tests for ``aura.engines.recall.query.build_queries``: joining the previous
user turn when the input is short or contains a pronoun, and removing stop
words from the lexical query.
"""

from aura.config import settings
from aura.engines.recall.query import RecallQueries, build_queries


def _user(content: str) -> dict[str, str]:
    return {"role": "user", "content": content}


def test_long_self_contained_input_is_not_joined():
    user_input = (
        "Explain the tradeoffs between a hash map and a binary tree "
        "for a large in-memory index"
    )
    assert len(user_input.split()) > settings.recall_query_join_max_words

    queries = build_queries(user_input, [_user("Earlier we discussed databases")])

    assert queries.joined is False
    assert queries.dense_text == user_input


def test_pronoun_follow_up_after_rust_turn_is_joined():
    previous = "I have been learning Rust"
    user_input = "and what about it?"

    queries = build_queries(user_input, [_user(previous)])

    assert queries.joined is True
    assert queries.dense_text == previous + "\n" + user_input


def test_short_input_with_no_previous_user_turn_is_not_joined():
    queries = build_queries(
        "what about it?", [{"role": "assistant", "content": "Hello there"}]
    )

    assert queries.joined is False
    assert queries.dense_text == "what about it?"


def test_current_input_repeated_at_end_of_history_is_not_previous():
    previous = "I have been learning Rust"
    user_input = "and what about it?"

    queries = build_queries(user_input, [_user(previous), _user(user_input)])

    assert queries.joined is True
    assert queries.dense_text == previous + "\n" + user_input


def test_stop_words_removed_from_lexical_but_kept_in_dense():
    previous = "I have been learning Rust"
    user_input = "and what about it?"

    queries = build_queries(user_input, [_user(previous)])

    # The dense text keeps every word, stop words included.
    assert queries.dense_text == previous + "\n" + user_input
    assert "and" in queries.dense_text.split()
    assert "what" in queries.dense_text.split()
    assert "it?" in queries.dense_text.split()

    # The lexical text keeps only the content words.
    assert queries.lexical_text == "learning Rust"


def test_all_stop_word_input_gives_empty_lexical_text():
    queries = build_queries("what is it?", [])

    assert queries.joined is False
    assert queries.dense_text == "what is it?"
    assert queries.lexical_text == ""