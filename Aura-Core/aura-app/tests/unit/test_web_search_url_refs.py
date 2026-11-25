"""Tests for FU-01: web_search makes its result URLs usable as consult `url:` refs."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.tools import consult, web_search


class MockResponse:
    """Mock aiohttp response."""

    def __init__(self, status: int, json_data: dict[str, Any]):
        self.status = status
        self._json_data = json_data

    async def json(self):
        return self._json_data

    async def text(self):
        return "error"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockPostContext:
    """Mock async context manager for session.post()."""

    def __init__(self, response: MockResponse):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        pass


class MockSession:
    """Mock aiohttp ClientSession."""

    def __init__(self, response: MockResponse):
        self._response = response

    def post(self, *args, **kwargs):
        return MockPostContext(self._response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture(autouse=True)
def _setup_clock(monkeypatch):
    """Set up fake clock and restore after."""
    set_clock(FakeClock(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)))
    yield
    set_clock(Clock())


@pytest.fixture(autouse=True)
def _reset_consult():
    """Reset consult turn state before and after each test."""
    consult.begin_turn()
    yield
    consult.begin_turn()


@pytest.fixture(autouse=True)
def _mock_tavily_key(monkeypatch):
    """Set TAVILY_API_KEY so web_search doesn't fail early."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")


@pytest.fixture
def mock_tavily_response():
    """Mock Tavily API response with two results."""
    return {
        "answer": "Test answer",
        "results": [
            {
                "title": "Result 1",
                "url": "https://example.com/result1",
                "content": "Full content of result 1 that is quite long and detailed",
            },
            {
                "title": "Result 2",
                "url": "https://example.com/result2",
                "content": "Full content of result 2 with different information here",
            },
        ],
    }


async def test_url_refs_resolvable_with_consult_enabled(monkeypatch, mock_tavily_response):
    """Two results make two URLs resolvable through consult's ref resolver in the same turn."""
    monkeypatch.setattr(settings, "consult_enabled", True)
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)

    mock_response = MockResponse(200, mock_tavily_response)
    mock_session = MockSession(mock_response)
    monkeypatch.setattr("aiohttp.ClientSession", lambda: mock_session)

    # Run web_search
    result = await web_search.run({"query": "test query"})

    # Check search output contains results
    assert "Result 1" in result
    assert "Result 2" in result
    assert "https://example.com/result1" in result
    assert "https://example.com/result2" in result

    # Now verify URLs are resolvable through consult's ref resolver
    # Start a new turn (consult.begin_turn() is called in fixture)
    # The URLs should be in the fetched_urls for this turn
    state = consult._state()
    assert "https://example.com/result1" in state.fetched_urls
    assert "https://example.com/result2" in state.fetched_urls
    assert state.fetched_urls["https://example.com/result1"] == "Full content of result 1 that is quite long and detailed"
    assert state.fetched_urls["https://example.com/result2"] == "Full content of result 2 with different information here"

    # Test that consult can resolve the url: refs
    ref1_id, ref1_content = await consult.resolve_ref("url:https://example.com/result1")
    ref2_id, ref2_content = await consult.resolve_ref("url:https://example.com/result2")

    assert ref1_id == "url:https://example.com/result1"
    assert ref1_content == "Full content of result 1 that is quite long and detailed"
    assert ref2_id == "url:https://example.com/result2"
    assert ref2_content == "Full content of result 2 with different information here"


async def test_consult_disabled_does_not_note_urls(monkeypatch, mock_tavily_response):
    """Flag off (consult_enabled=false) notes nothing - ablation test."""
    monkeypatch.setattr(settings, "consult_enabled", False)
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)

    mock_response = MockResponse(200, mock_tavily_response)
    mock_session = MockSession(mock_response)
    monkeypatch.setattr("aiohttp.ClientSession", lambda: mock_session)

    # Run web_search
    result = await web_search.run({"query": "test query"})

    # Check search output still works
    assert "Result 1" in result
    assert "Result 2" in result

    # URLs should NOT be in fetched_urls
    state = consult._state()
    assert "https://example.com/result1" not in state.fetched_urls
    assert "https://example.com/result2" not in state.fetched_urls


async def test_note_fetched_url_failure_does_not_affect_search(monkeypatch, mock_tavily_response):
    """A failure inside note_fetched_url does not change the search output."""
    monkeypatch.setattr(settings, "consult_enabled", True)
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)

    # Make note_fetched_url raise an exception
    def failing_note_fetched_url(url: str, content: str) -> None:
        raise RuntimeError("Simulated failure in note_fetched_url")

    monkeypatch.setattr(consult, "note_fetched_url", failing_note_fetched_url)

    mock_response = MockResponse(200, mock_tavily_response)
    mock_session = MockSession(mock_response)
    monkeypatch.setattr("aiohttp.ClientSession", lambda: mock_session)

    # Run web_search - should not raise
    result = await web_search.run({"query": "test query"})

    # Search output should be normal
    assert "Result 1" in result
    assert "Result 2" in result
    assert "https://example.com/result1" in result
    assert "https://example.com/result2" in result
    assert "Search performed at" in result


async def test_timestamp_uses_clock_provider(monkeypatch, mock_tavily_response):
    """Timestamp in footer uses get_clock().now() not datetime.now()."""
    monkeypatch.setattr(settings, "consult_enabled", True)
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)

    mock_response = MockResponse(200, mock_tavily_response)
    mock_session = MockSession(mock_response)
    monkeypatch.setattr("aiohttp.ClientSession", lambda: mock_session)

    # Run web_search
    result = await web_search.run({"query": "test query"})

    # Check timestamp format (from FakeClock: 2026-01-02 03:04:05)
    assert "Search performed at 2026-01-02 03:04:05" in result