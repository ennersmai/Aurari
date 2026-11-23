"""Time expression parsing for the Recall Engine temporal channel (W4-02).

Parses English time expressions into a (start, end) datetime range.
The `now` parameter is supplied by the caller via `get_clock().now()`.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


# ISO date pattern: 2026-11-02 or 2026-11-02T15:30:00
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}:\d{2}))?\b")

# Relative expressions
_RELATIVE_RE = re.compile(
    r"\b(?:"
    r"today|"
    r"yesterday|"
    r"last\s+week|"
    r"this\s+week|"
    r"last\s+month|"
    r"this\s+month|"
    r"(\d+)\s+days?\s+ago|"
    r"(\d+)\s+weeks?\s+ago|"
    r"(\d+)\s+months?\s+ago"
    r")\b",
    re.IGNORECASE,
)

# Weekday names: "on Monday", "last Monday", "this Monday"
_WEEKDAY_RE = re.compile(
    r"\b(?:on|last|this)\s+"
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)

# Month names: "in March", "last March", "this March"
_MONTH_RE = re.compile(
    r"\b(?:in|last|this)\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)

_WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _start_of_day(dt: datetime) -> datetime:
    """Return midnight UTC of the given datetime."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt: datetime) -> datetime:
    """Return 23:59:59.999999 UTC of the given datetime."""
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def _start_of_week(dt: datetime) -> datetime:
    """Return Monday 00:00 UTC of the week containing dt."""
    start = _start_of_day(dt)
    # weekday() returns 0=Monday, 6=Sunday
    return start - timedelta(days=start.weekday())


def _end_of_week(dt: datetime) -> datetime:
    """Return Sunday 23:59:59 UTC of the week containing dt."""
    start = _start_of_week(dt)
    return _end_of_day(start + timedelta(days=6))


def _start_of_month(dt: datetime) -> datetime:
    """Return 1st day 00:00 UTC of the month containing dt."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _end_of_month(dt: datetime) -> datetime:
    """Return last day 23:59:59 UTC of the month containing dt."""
    if dt.month == 12:
        next_month = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        next_month = dt.replace(month=dt.month + 1, day=1)
    return _end_of_day(next_month - timedelta(days=1))


def _most_recent_weekday(now: datetime, target_weekday: int) -> datetime:
    """Return the most recent past occurrence of target_weekday (0=Mon)."""
    # On the named weekday itself, "on Monday" means last week's Monday.
    days_back = (now.weekday() - target_weekday) % 7 or 7
    return _start_of_day(now - timedelta(days=days_back))


def _most_recent_month(now: datetime, target_month: int) -> datetime:
    """Return the first day of the most recent past target_month."""
    if now.month == target_month:
        # This month is the target - use this month
        return _start_of_month(now)
    elif now.month > target_month:
        # Target month already passed this year
        return _start_of_month(now.replace(month=target_month, day=1))
    else:
        # Target month is next year - use last year
        return _start_of_month(now.replace(year=now.year - 1, month=target_month, day=1))


def parse_range(text: str, now: datetime) -> Optional[Tuple[datetime, datetime]]:
    """Parse a time expression from English text into a (start, end) datetime range.

    Supported expressions (all relative to `now`):
    - "today" → today 00:00 to 23:59
    - "yesterday" → yesterday 00:00 to 23:59
    - "last week" → previous week (Mon-Sun)
    - "this week" → current week (Mon-Sun)
    - "last month" → previous calendar month
    - "this month" → current calendar month
    - "N days/weeks/months ago" → a day/week/month window around that point
    - "on Monday", "last Monday", "this Monday" → most recent past Monday
    - "in March", "last March", "this March" → most recent past March
    - ISO dates: "2026-11-02" or "2026-11-02T15:30:00"

    Returns None if no time expression is found.
    """
    if not text or not text.strip():
        return None

    text_lower = text.lower()

    # 1. ISO date
    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        date_str = iso_match.group(1)
        time_str = iso_match.group(2)
        try:
            if time_str:
                dt = datetime.fromisoformat(f"{date_str}T{time_str}")
            else:
                dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return (_start_of_day(dt), _end_of_day(dt))
        except ValueError:
            pass

    # 2. Relative expressions
    rel_match = _RELATIVE_RE.search(text_lower)
    if rel_match:
        # Check which group matched
        if "today" in rel_match.group(0):
            return (_start_of_day(now), _end_of_day(now))
        elif "yesterday" in rel_match.group(0):
            yday = now - timedelta(days=1)
            return (_start_of_day(yday), _end_of_day(yday))
        elif "last week" in rel_match.group(0):
            # Previous week (Mon-Sun)
            this_week_start = _start_of_week(now)
            last_week_start = this_week_start - timedelta(days=7)
            return (last_week_start, _end_of_day(last_week_start + timedelta(days=6)))
        elif "this week" in rel_match.group(0):
            return (_start_of_week(now), _end_of_week(now))
        elif "last month" in rel_match.group(0):
            last_month = _start_of_month(now) - timedelta(days=1)
            return (_start_of_month(last_month), _end_of_month(last_month))
        elif "this month" in rel_match.group(0):
            return (_start_of_month(now), _end_of_month(now))
        elif rel_match.group(1):  # N days ago
            n = int(rel_match.group(1))
            target = now - timedelta(days=n)
            return (_start_of_day(target), _end_of_day(target))
        elif rel_match.group(2):  # N weeks ago
            n = int(rel_match.group(2))
            target = now - timedelta(weeks=n)
            return (_start_of_week(target), _end_of_week(target))
        elif rel_match.group(3):  # N months ago
            n = int(rel_match.group(3))
            # Approximate: subtract n months
            year = now.year
            month = now.month - n
            while month <= 0:
                month += 12
                year -= 1
            target = now.replace(year=year, month=month, day=1)
            return (_start_of_month(target), _end_of_month(target))

    # 3. Weekday names: "on Monday", "last Monday", "this Monday"
    wd_match = _WEEKDAY_RE.search(text_lower)
    if wd_match:
        weekday_name = wd_match.group(1)
        target_weekday = _WEEKDAY_MAP[weekday_name]
        target = _most_recent_weekday(now, target_weekday)
        return (_start_of_day(target), _end_of_day(target))

    # 4. Month names: "in March", "last March", "this March"
    mon_match = _MONTH_RE.search(text_lower)
    if mon_match:
        month_name = mon_match.group(1)
        target_month = _MONTH_MAP[month_name]
        target = _most_recent_month(now, target_month)
        return (_start_of_month(target), _end_of_month(target))

    return None