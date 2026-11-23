"""Unit tests for timeexpr.py (W4-02)."""

from datetime import datetime, timezone

from aura.engines.recall.timeexpr import parse_range


def test_today():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do today", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 15, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_yesterday():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I say yesterday", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 14, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_last_week():
    # 2026-11-15 is a Sunday. Last week is Mon Nov 9 - Sun Nov 15? 
    # Wait: "last week" means the previous week (Mon-Sun before this week)
    # This week starts Mon Nov 9, so last week is Mon Nov 2 - Sun Nov 8
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)  # Sunday
    result = parse_range("what happened last week", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)  # Monday
    assert end == datetime(2026, 11, 8, 23, 59, 59, 999999, tzinfo=timezone.utc)  # Sunday


def test_this_week():
    # 2026-11-15 is a Sunday. This week is Mon Nov 9 - Sun Nov 15
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what happened this week", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)  # Monday
    assert end == datetime(2026, 11, 15, 23, 59, 59, 999999, tzinfo=timezone.utc)  # Sunday


def test_last_month():
    # November 2026 -> last month is October 2026
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do last month", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_this_month():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do this month", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 30, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_days_ago():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I say 3 days ago", now)
    assert result is not None
    start, end = result
    # 3 days ago from Nov 15 is Nov 12
    assert start == datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 12, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_weeks_ago():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what happened 2 weeks ago", now)
    assert result is not None
    start, end = result
    # 2 weeks ago from Nov 15 (Sun) -> Nov 1 (Sun). Week of Nov 1 is Oct 26 - Nov 1
    assert start == datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)  # Monday
    assert end == datetime(2026, 11, 1, 23, 59, 59, 999999, tzinfo=timezone.utc)  # Sunday


def test_months_ago():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what happened 2 months ago", now)
    assert result is not None
    start, end = result
    # 2 months ago from Nov 2026 is Sep 2026
    assert start == datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_on_weekday():
    # 2026-11-15 is a Sunday. "on Monday" -> most recent past Monday = Nov 9
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do on Monday", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 9, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_last_weekday():
    # 2026-11-15 is a Sunday. "last Monday" -> most recent past Monday = Nov 9
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do last Monday", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 9, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_this_weekday():
    # 2026-11-15 is a Sunday. "this Monday" -> most recent past Monday = Nov 9
    # (since "this" with a weekday in the past still means the most recent)
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do this Monday", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 9, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_in_month():
    # November 2026 -> "in March" -> most recent past March = March 2026
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do in March", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_last_month_name():
    # November 2026 -> "last March" -> March 2026 (already past this year)
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do last March", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_this_month_name():
    # November 2026 -> "this November" -> November 2026 (current month)
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do this November", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 30, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_iso_date():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what happened on 2026-11-02", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 2, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_iso_datetime():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what happened at 2026-11-02T15:30:00", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 2, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_no_time_expression():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("hello there", now)
    assert result is None


def test_empty_string():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("", now)
    assert result is None


def test_weekday_today():
    # Asked on a Monday, "on Monday" means last week's Monday (today is "today")
    # 2026-11-09 is a Monday
    now = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do on Monday", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 2, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_month_arithmetic_on_the_31st():
    # March 31st: no February 31st may be built along the way
    now = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
    feb = (
        datetime(2026, 2, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 28, 23, 59, 59, 999999, tzinfo=timezone.utc),
    )
    assert parse_range("last month", now) == feb
    assert parse_range("1 month ago", now) == feb
    assert parse_range("in February", now) == feb


def test_month_this_year():
    # If the target month is this year but already passed
    # November 2026 -> "in May" -> May 2026
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do in May", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 5, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_month_next_year():
    # If the target month hasn't happened yet this year, use last year
    # March 2026 -> "in November" -> November 2025
    now = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("what did I do in November", now)
    assert result is not None
    start, end = result
    assert start == datetime(2025, 11, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2025, 11, 30, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_case_insensitive():
    now = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    result = parse_range("WHAT DID I DO YESTERDAY", now)
    assert result is not None
    start, end = result
    assert start == datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 14, 23, 59, 59, 999999, tzinfo=timezone.utc)