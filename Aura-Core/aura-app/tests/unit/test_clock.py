"""Tests for the clock provider."""

import pytest
from datetime import datetime, timezone, timedelta

from aura.clock import Clock, FakeClock, get_clock, set_clock


class TestClock:
    """Tests for the real Clock class."""
    
    def test_now_returns_timezone_aware_utc(self):
        """get_clock().now() returns a timezone-aware UTC datetime."""
        clock = Clock()
        now = clock.now()
        
        assert isinstance(now, datetime)
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc


class TestFakeClock:
    """Tests for the FakeClock class."""
    
    def test_fake_clock_initial_time(self):
        """FakeClock starts at the given time or current time."""
        fixed_time = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        clock = FakeClock(fixed_time)
        
        assert clock.now() == fixed_time
    
    def test_fake_clock_set(self):
        """set() changes the clock's time."""
        clock = FakeClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
        new_time = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        
        clock.set(new_time)
        assert clock.now() == new_time
    
    def test_fake_clock_advance(self):
        """advance() moves the clock forward by seconds."""
        clock = FakeClock(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
        
        clock.advance(3600)  # 1 hour
        expected = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        assert clock.now() == expected
        
        clock.advance(60)  # 1 minute
        expected = datetime(2024, 1, 1, 13, 1, 0, tzinfo=timezone.utc)
        assert clock.now() == expected
    
    def test_fake_clock_advance_fractional(self):
        """advance() works with fractional seconds."""
        clock = FakeClock(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
        
        clock.advance(0.5)
        expected = datetime(2024, 1, 1, 12, 0, 0, 500000, tzinfo=timezone.utc)
        assert clock.now() == expected
    
    def test_fake_clock_naive_datetime_converted_to_utc(self):
        """Naive datetimes passed to set() are treated as UTC."""
        clock = FakeClock()
        naive = datetime(2024, 6, 15, 10, 30)  # no timezone
        
        clock.set(naive)
        assert clock.now().tzinfo == timezone.utc
        assert clock.now() == datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc)
    
    def test_fake_clock_initial_naive_converted_to_utc(self):
        """Naive datetime in constructor is treated as UTC."""
        naive = datetime(2024, 6, 15, 10, 30)
        clock = FakeClock(naive)
        
        assert clock.now().tzinfo == timezone.utc
        assert clock.now() == datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc)


class TestClockGlobal:
    """Tests for the global clock functions."""
    
    def test_get_clock_returns_instance(self):
        """get_clock() returns a Clock instance."""
        clock = get_clock()
        assert isinstance(clock, Clock)
    
    def test_set_clock_replaces_global(self):
        """set_clock() replaces the global clock."""
        original = get_clock()
        fake = FakeClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
        
        set_clock(fake)
        assert get_clock() is fake
        
        # Restore
        set_clock(original)
        assert get_clock() is original
    
    def test_fake_clock_used_via_get_clock(self):
        """FakeClock works through get_clock()."""
        fake = FakeClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
        set_clock(fake)
        
        assert get_clock().now() == datetime(2024, 1, 1, tzinfo=timezone.utc)
        
        fake.advance(100)
        assert get_clock().now() == datetime(2024, 1, 1, 0, 1, 40, tzinfo=timezone.utc)
        
        # Restore real clock
        set_clock(Clock())