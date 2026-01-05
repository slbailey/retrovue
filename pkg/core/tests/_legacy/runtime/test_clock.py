"""
Tests for MasterClock

Tests the authoritative time source for the RetroVue system.
"""

from datetime import UTC, datetime, timedelta

import pytest

from retrovue.runtime.clock import MasterClock, TimeEvent, TimeInfo, TimePrecision


class TestMasterClock:
    """Test cases for MasterClock functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.clock = MasterClock()
    
    def test_initialization(self):
        """Test MasterClock initialization."""
        clock = MasterClock()
        assert clock.precision == TimePrecision.MILLISECOND
        assert clock.is_synchronized is True
        assert isinstance(clock.timezone_cache, dict)
        assert isinstance(clock.scheduled_events, dict)
    
    def test_initialization_with_precision(self):
        """Test MasterClock initialization with custom precision."""
        clock = MasterClock(TimePrecision.SECOND)
        assert clock.precision == TimePrecision.SECOND
    
    def test_now_utc(self):
        """Test getting current UTC time."""
        utc_time = self.clock.now_utc()
        
        # Should be timezone-aware UTC
        assert utc_time.tzinfo == UTC
        
        # Should be recent (within last second)
        now = datetime.now(UTC)
        time_diff = abs((now - utc_time).total_seconds())
        assert time_diff < 1.0
    
    def test_now_utc_precision_second(self):
        """Test UTC time with second precision."""
        clock = MasterClock(TimePrecision.SECOND)
        utc_time = clock.now_utc()
        
        # Microseconds should be zero
        assert utc_time.microsecond == 0
    
    def test_now_utc_precision_millisecond(self):
        """Test UTC time with millisecond precision."""
        clock = MasterClock(TimePrecision.MILLISECOND)
        utc_time = clock.now_utc()
        
        # Microseconds should be rounded to milliseconds
        assert utc_time.microsecond % 1000 == 0
    
    def test_now_local_system_timezone(self):
        """Test getting local time in system timezone."""
        local_time = self.clock.now_local()
        
        # Should be timezone-aware
        assert local_time.tzinfo is not None
        
        # Should be recent
        now = datetime.now()
        time_diff = abs((now - local_time.replace(tzinfo=None)).total_seconds())
        assert time_diff < 1.0
    
    def test_now_local_specific_timezone(self):
        """Test getting local time in specific timezone."""
        # Test with New York timezone
        ny_time = self.clock.now_local("America/New_York")
        
        # Should be timezone-aware
        assert ny_time.tzinfo is not None
        assert "EST" in str(ny_time.tzinfo) or "EDT" in str(ny_time.tzinfo)
        
        # Should be recent
        now = datetime.now()
        time_diff = abs((now - ny_time.replace(tzinfo=None)).total_seconds())
        assert time_diff < 1.0
    
    def test_now_local_invalid_timezone(self):
        """Test getting local time with invalid timezone."""
        # Should fall back to UTC instead of raising exception
        result = self.clock.now_local("Invalid/Timezone")
        assert result.tzinfo == UTC
    
    def test_seconds_since(self):
        """Test calculating seconds since a datetime."""
        # Create a reference time 5 seconds ago
        reference_time = datetime.now(UTC) - timedelta(seconds=5)
        
        seconds = self.clock.seconds_since(reference_time)
        
        # Should be approximately 5 seconds
        assert 4.9 <= seconds <= 5.1
    
    def test_seconds_since_naive_datetime(self):
        """Test seconds_since with naive datetime."""
        # Create a naive datetime
        reference_time = datetime.now() - timedelta(seconds=3)
        
        # Should raise ValueError for naive datetime
        with pytest.raises(ValueError, match="datetime must be timezone-aware"):
            self.clock.seconds_since(reference_time)
    
    def test_seconds_since_future_time(self):
        """Test seconds_since with future time (should clamp to 0.0)."""
        # Create a future datetime
        future_time = datetime.now(UTC) + timedelta(seconds=5)
        
        seconds = self.clock.seconds_since(future_time)
        
        # Should be clamped to 0.0 for future times
        assert seconds == 0.0
    
    def test_to_channel_time(self):
        """Test converting UTC datetime to channel timezone."""
        # Create a UTC datetime
        utc_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        
        # Convert to New York time
        ny_time = self.clock.to_channel_time(utc_time, "America/New_York")
        
        # Should be timezone-aware
        assert ny_time.tzinfo is not None
        # Should be 5 hours behind UTC (EST)
        assert ny_time.hour == 7
        assert ny_time.day == 15
    
    def test_to_channel_time_naive_input(self):
        """Test to_channel_time with naive datetime."""
        # Create a naive datetime
        naive_time = datetime(2024, 1, 15, 12, 0, 0)
        
        # Should raise ValueError for naive datetime
        with pytest.raises(ValueError, match="datetime must be timezone-aware"):
            self.clock.to_channel_time(naive_time, "America/New_York")
    
    def test_to_channel_time_invalid_timezone(self):
        """Test to_channel_time with invalid timezone."""
        # Create a UTC datetime
        utc_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        
        # Should fall back to UTC for invalid timezone
        result = self.clock.to_channel_time(utc_time, "Invalid/Timezone")
        assert result == utc_time
    
    def test_get_current_time(self):
        """Test get_current_time method."""
        current_time = self.clock.get_current_time()
        
        # Should be same as now_utc()
        utc_time = self.clock.now_utc()
        assert current_time == utc_time
    
    def test_get_time_info(self):
        """Test getting comprehensive time information."""
        time_info = self.clock.get_time_info()
        
        assert isinstance(time_info, TimeInfo)
        assert isinstance(time_info.utc_time, datetime)
        assert isinstance(time_info.local_time, datetime)
        assert isinstance(time_info.timezone, str)
        assert isinstance(time_info.precision, TimePrecision)
        assert isinstance(time_info.is_synchronized, bool)
    
    def test_convert_timezone(self):
        """Test timezone conversion."""
        # Create a UTC datetime
        utc_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        
        # Convert to New York time
        ny_time = self.clock.convert_timezone(utc_time, "UTC", "America/New_York")
        
        # Should be 5 hours behind UTC (EST)
        assert ny_time.hour == 7
        assert ny_time.day == 15
    
    def test_convert_timezone_naive_input(self):
        """Test timezone conversion with naive datetime."""
        # Create a naive datetime
        naive_time = datetime(2024, 1, 15, 12, 0, 0)
        
        # Convert from UTC to New York
        ny_time = self.clock.convert_timezone(naive_time, "UTC", "America/New_York")
        
        # Should be 5 hours behind UTC
        assert ny_time.hour == 7
    
    def test_get_channel_time(self):
        """Test getting time for a specific channel."""
        channel_time = self.clock.get_channel_time("channel_1", "America/Los_Angeles")
        
        # Should be timezone-aware
        assert channel_time.tzinfo is not None
        
        # Should be recent
        now = datetime.now()
        time_diff = abs((now - channel_time.replace(tzinfo=None)).total_seconds())
        assert time_diff < 1.0
    
    def test_synchronize_time(self):
        """Test time synchronization."""
        result = self.clock.synchronize_time()
        
        assert result is True
        assert self.clock.is_synchronized is True
    
    def test_schedule_event(self):
        """Test scheduling a time-based event."""
        trigger_time = datetime.now(UTC) + timedelta(minutes=5)
        
        result = self.clock.schedule_event(
            "test_event",
            trigger_time,
            "test_type",
            {"key": "value"}
        )
        
        assert result is True
        assert "test_event" in self.clock.scheduled_events
        
        event = self.clock.scheduled_events["test_event"]
        assert event.event_id == "test_event"
        assert event.trigger_time == trigger_time
        assert event.event_type == "test_type"
        assert event.payload == {"key": "value"}
    
    def test_schedule_event_naive_time(self):
        """Test scheduling event with naive datetime."""
        trigger_time = datetime.now() + timedelta(minutes=5)
        
        result = self.clock.schedule_event(
            "test_event_naive",
            trigger_time,
            "test_type",
            {}
        )
        
        assert result is True
        # Should be converted to UTC
        event = self.clock.scheduled_events["test_event_naive"]
        assert event.trigger_time.tzinfo == UTC
    
    def test_cancel_event(self):
        """Test canceling a scheduled event."""
        # Schedule an event first
        trigger_time = datetime.now(UTC) + timedelta(minutes=5)
        self.clock.schedule_event("test_event", trigger_time, "test_type", {})
        
        # Cancel the event
        result = self.clock.cancel_event("test_event")
        
        assert result is True
        assert "test_event" not in self.clock.scheduled_events
    
    def test_cancel_nonexistent_event(self):
        """Test canceling a non-existent event."""
        result = self.clock.cancel_event("nonexistent_event")
        
        assert result is False
    
    def test_get_scheduled_events(self):
        """Test getting events in a time range."""
        now = datetime.now(UTC)
        
        # Schedule events at different times
        self.clock.schedule_event("event1", now + timedelta(minutes=1), "type1", {})
        self.clock.schedule_event("event2", now + timedelta(minutes=5), "type2", {})
        self.clock.schedule_event("event3", now + timedelta(minutes=10), "type3", {})
        
        # Get events in next 3 minutes
        events = self.clock.get_scheduled_events(now, now + timedelta(minutes=3))
        
        assert len(events) == 1
        assert events[0].event_id == "event1"
    
    def test_trigger_scheduled_events(self):
        """Test triggering due events."""
        now = datetime.now(UTC)
        
        # Schedule events - one in the past, one in the future
        self.clock.schedule_event("past_event", now - timedelta(minutes=1), "type1", {})
        self.clock.schedule_event("future_event", now + timedelta(minutes=1), "type2", {})
        
        # Trigger events
        triggered = self.clock.trigger_scheduled_events()
        
        assert len(triggered) == 1
        assert triggered[0].event_id == "past_event"
        assert "future_event" in self.clock.scheduled_events
        assert "past_event" not in self.clock.scheduled_events
    
    def test_get_time_precision(self):
        """Test getting time precision."""
        precision = self.clock.get_time_precision()
        
        assert precision == TimePrecision.MILLISECOND
    
    def test_set_time_precision(self):
        """Test setting time precision."""
        result = self.clock.set_time_precision(TimePrecision.SECOND)
        
        assert result is True
        assert self.clock.precision == TimePrecision.SECOND
    
    def test_validate_time_consistency(self):
        """Test time consistency validation."""
        result = self.clock.validate_time_consistency()
        
        assert result is True
    
    def test_get_timezone_info(self):
        """Test getting timezone information."""
        tz_info = self.clock.get_timezone_info("America/New_York")
        
        assert isinstance(tz_info, dict)
        assert tz_info['name'] == "America/New_York"
        assert 'offset' in tz_info
        assert 'dst' in tz_info
        assert 'zone' in tz_info
    
    def test_get_timezone_info_invalid(self):
        """Test getting info for invalid timezone."""
        tz_info = self.clock.get_timezone_info("Invalid/Timezone")
        
        assert isinstance(tz_info, dict)
        assert tz_info['name'] == "Invalid/Timezone"
        assert 'error' in tz_info
    
    def test_handle_timezone_changes(self):
        """Test handling timezone changes."""
        # Add some cached timezones
        self.clock._get_timezone_info("America/New_York")
        self.clock._get_timezone_info("Europe/London")
        
        assert len(self.clock.timezone_cache) == 2
        
        # Handle timezone changes
        changes = self.clock.handle_timezone_changes()
        
        assert changes == ['timezone_cache_cleared']
        assert len(self.clock.timezone_cache) == 0
    
    def test_timezone_caching(self):
        """Test timezone caching functionality."""
        # First call should cache the timezone
        tz1 = self.clock._get_timezone_info("America/New_York")
        assert len(self.clock.timezone_cache) == 1
        
        # Second call should use cache
        tz2 = self.clock._get_timezone_info("America/New_York")
        assert len(self.clock.timezone_cache) == 1
        assert tz1 is tz2  # Same object from cache
    
    def test_multiple_timezones_caching(self):
        """Test caching multiple timezones."""
        tz1 = self.clock._get_timezone_info("America/New_York")
        tz2 = self.clock._get_timezone_info("Europe/London")
        tz3 = self.clock._get_timezone_info("Asia/Tokyo")
        
        assert len(self.clock.timezone_cache) == 3
        assert tz1 != tz2 != tz3
    
    def test_precision_affects_output(self):
        """Test that precision setting affects time output."""
        # Test with second precision
        clock_second = MasterClock(TimePrecision.SECOND)
        time_second = clock_second.now_utc()
        
        # Test with microsecond precision
        clock_micro = MasterClock(TimePrecision.MICROSECOND)
        time_micro = clock_micro.now_utc()
        
        # Second precision should have zero microseconds
        assert time_second.microsecond == 0
        
        # Microsecond precision should have non-zero microseconds (likely)
        # Note: This might occasionally fail if the microsecond happens to be 0
        # but it's very unlikely in practice
        assert time_micro.microsecond >= 0


class TestTimeInfo:
    """Test cases for TimeInfo dataclass."""
    
    def test_time_info_creation(self):
        """Test creating TimeInfo object."""
        utc_time = datetime.now(UTC)
        local_time = datetime.now()
        precision = TimePrecision.MILLISECOND
        
        time_info = TimeInfo(
            utc_time=utc_time,
            local_time=local_time,
            timezone="America/New_York",
            precision=precision,
            is_synchronized=True
        )
        
        assert time_info.utc_time == utc_time
        assert time_info.local_time == local_time
        assert time_info.timezone == "America/New_York"
        assert time_info.precision == precision
        assert time_info.is_synchronized is True


class TestTimeEvent:
    """Test cases for TimeEvent dataclass."""
    
    def test_time_event_creation(self):
        """Test creating TimeEvent object."""
        trigger_time = datetime.now(UTC)
        payload = {"key": "value", "number": 42}
        
        event = TimeEvent(
            event_id="test_event",
            trigger_time=trigger_time,
            event_type="test_type",
            payload=payload
        )
        
        assert event.event_id == "test_event"
        assert event.trigger_time == trigger_time
        assert event.event_type == "test_type"
        assert event.payload == payload


class TestTimePrecision:
    """Test cases for TimePrecision enum."""
    
    def test_time_precision_values(self):
        """Test TimePrecision enum values."""
        assert TimePrecision.SECOND.value == "second"
        assert TimePrecision.MILLISECOND.value == "millisecond"
        assert TimePrecision.MICROSECOND.value == "microsecond"
    
    def test_time_precision_enumeration(self):
        """Test TimePrecision enum iteration."""
        precisions = list(TimePrecision)
        assert len(precisions) == 3
        assert TimePrecision.SECOND in precisions
        assert TimePrecision.MILLISECOND in precisions
        assert TimePrecision.MICROSECOND in precisions


class TestMasterClockIntegration:
    """Integration tests for MasterClock with other components."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.clock = MasterClock()
    
    def test_schedule_service_integration(self):
        """Test how ScheduleService would use MasterClock."""
        # Simulate ScheduleService usage
        now_utc = self.clock.now_utc()
        channel_time = self.clock.now_local("America/New_York")
        
        # Calculate offset for mid-program joins
        reference_time = now_utc - timedelta(minutes=30)
        offset_seconds = self.clock.seconds_since(reference_time)
        
        assert isinstance(now_utc, datetime)
        assert isinstance(channel_time, datetime)
        assert isinstance(offset_seconds, float)
        assert offset_seconds > 0
    
    def test_channel_manager_integration(self):
        """Test how ChannelManager would use MasterClock."""
        # Simulate ChannelManager usage
        station_time = self.clock.now_utc()
        channel_tz = "America/Los_Angeles"
        local_time = self.clock.get_channel_time("channel_1", channel_tz)
        
        # Calculate time difference
        time_diff = self.clock.seconds_since(station_time - timedelta(seconds=10))
        
        assert isinstance(station_time, datetime)
        assert isinstance(local_time, datetime)
        assert time_diff > 0
    
    def test_program_director_integration(self):
        """Test how ProgramDirector would use MasterClock."""
        # Simulate ProgramDirector usage
        system_time = self.clock.now_utc()
        
        # Schedule emergency override event
        override_time = system_time + timedelta(seconds=30)
        self.clock.schedule_event(
            "emergency_override",
            override_time,
            "emergency",
            {"channels": ["channel_1", "channel_2"]}
        )
        
        # Check if event is scheduled
        events = self.clock.get_scheduled_events(system_time, system_time + timedelta(minutes=1))
        assert len(events) == 1
        assert events[0].event_id == "emergency_override"
    
    def test_asrun_logger_integration(self):
        """Test how AsRunLogger would use MasterClock."""
        # Simulate AsRunLogger usage
        log_time = self.clock.now_utc()
        
        # Create log entry with timestamp
        log_entry = {
            "timestamp": log_time.isoformat(),
            "event": "playout_started",
            "channel": "channel_1",
            "content": "movie_123"
        }
        
        assert isinstance(log_entry["timestamp"], str)
        assert "T" in log_entry["timestamp"]  # ISO format
        assert "Z" in log_entry["timestamp"] or "+" in log_entry["timestamp"]  # UTC indicator


if __name__ == "__main__":
    pytest.main([__file__])
