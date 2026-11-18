"""Clock provider for time-dependent operations.

All code that needs the current time should use get_clock().now() instead of
datetime.now() or datetime.utcnow(). This allows tests to control time via
FakeClock.
"""

from datetime import datetime, timezone
from typing import Optional


class Clock:
    """Base clock returning real UTC time."""
    
    def now(self) -> datetime:
        """Return current timezone-aware UTC datetime."""
        return datetime.now(timezone.utc)


class FakeClock(Clock):
    """Controllable clock for testing."""
    
    def __init__(self, initial: Optional[datetime] = None):
        self._now = initial or datetime.now(timezone.utc)
        if self._now.tzinfo is None:
            self._now = self._now.replace(tzinfo=timezone.utc)
    
    def now(self) -> datetime:
        return self._now
    
    def set(self, dt: datetime) -> None:
        """Set the clock to a specific datetime."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt
    
    def advance(self, seconds: float) -> None:
        """Advance the clock by the given number of seconds."""
        from datetime import timedelta
        self._now = self._now + timedelta(seconds=seconds)


# Process-wide clock instance
_clock: Clock = Clock()


def get_clock() -> Clock:
    """Return the process-wide clock instance."""
    return _clock


def set_clock(clock: Clock) -> None:
    """Replace the process-wide clock (for testing)."""
    global _clock
    _clock = clock