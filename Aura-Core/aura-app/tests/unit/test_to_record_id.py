import pytest
from surrealdb import RecordID
from aura.db.query_utils import to_record_id


def test_to_record_id_converts_table_id_string():
    """"memory:abc" becomes RecordID("memory", "abc")."""
    result = to_record_id("memory:abc")
    assert isinstance(result, RecordID)
    assert str(result) == "memory:abc"


def test_to_record_id_returns_bare_table_name_unchanged():
    """"memory" (no colon) is returned unchanged."""
    result = to_record_id("memory")
    assert result == "memory"
    assert not isinstance(result, RecordID)


def test_to_record_id_returns_existing_record_id_unchanged():
    """A value that is already a RecordID is returned unchanged."""
    original = RecordID("memory", "abc")
    result = to_record_id(original)
    assert result is original


def test_to_record_id_handles_non_string_input():
    """Non-string values are returned unchanged."""
    assert to_record_id(123) == 123
    assert to_record_id(None) is None
    assert to_record_id([]) == []
