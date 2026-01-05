"""
Performance tests for MasterClock

Tests the performance characteristics of MasterClock operations,
particularly timezone caching and conversion efficiency.
"""

import time
from datetime import UTC, datetime, timedelta

from retrovue.runtime.clock import MasterClock, TimePrecision


class TestMasterClockPerformance:
    """Performance tests for MasterClock operations."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.clock = MasterClock()
    
    def test_timezone_caching_performance(self):
        """Test that timezone caching improves performance."""
        timezone_name = "America/New_York"
        
        # First call - should populate cache
        start_time = time.time()
        tz1 = self.clock._get_timezone_info(timezone_name)
        first_call_time = time.time() - start_time
        
        # Second call - should use cache
        start_time = time.time()
        tz2 = self.clock._get_timezone_info(timezone_name)
        second_call_time = time.time() - start_time
        
        # Cached call should be faster
        assert second_call_time < first_call_time
        assert tz1 is tz2  # Same object from cache
    
    def test_multiple_timezone_conversion_performance(self):
        """Test performance of multiple timezone conversions."""
        timezones = [
            "America/New_York",
            "Europe/London", 
            "Asia/Tokyo",
            "Australia/Sydney",
            "America/Los_Angeles"
        ]
        
        start_time = time.time()
        
        # Convert current time to all timezones
        for tz in timezones:
            self.clock.now_local(tz)
        
        total_time = time.time() - start_time
        
        # Should complete quickly (less than 1 second for 5 timezones)
        assert total_time < 1.0
    
    def test_bulk_event_scheduling_performance(self):
        """Test performance of scheduling many events."""
        num_events = 1000
        base_time = datetime.now(UTC)
        
        start_time = time.time()
        
        # Schedule many events
        for i in range(num_events):
            trigger_time = base_time + timedelta(seconds=i)
            self.clock.schedule_event(
                f"event_{i}",
                trigger_time,
                "test",
                {"index": i}
            )
        
        scheduling_time = time.time() - start_time
        
        # Should schedule 1000 events quickly
        assert scheduling_time < 1.0
        assert len(self.clock.scheduled_events) == num_events
    
    def test_event_query_performance(self):
        """Test performance of querying scheduled events."""
        # Schedule many events
        base_time = datetime.now(UTC)
        for i in range(100):
            trigger_time = base_time + timedelta(minutes=i)
            self.clock.schedule_event(f"event_{i}", trigger_time, "test", {})
        
        # Query events in a time range
        start_time = time.time()
        events = self.clock.get_scheduled_events(
            base_time + timedelta(minutes=10),
            base_time + timedelta(minutes=20)
        )
        query_time = time.time() - start_time
        
        # Should query quickly
        assert query_time < 0.1
        assert len(events) == 10  # 10 events in the 10-minute range
    
    def test_precision_performance_impact(self):
        """Test that different precision levels have minimal performance impact."""
        operations = 1000
        
        # Test with second precision
        clock_second = MasterClock(TimePrecision.SECOND)
        start_time = time.time()
        for _ in range(operations):
            clock_second.now_utc()
        second_time = time.time() - start_time
        
        # Test with microsecond precision
        clock_micro = MasterClock(TimePrecision.MICROSECOND)
        start_time = time.time()
        for _ in range(operations):
            clock_micro.now_utc()
        micro_time = time.time() - start_time
        
        # Performance difference should be minimal
        time_ratio = micro_time / second_time
        assert time_ratio < 2.0  # Microsecond precision shouldn't be more than 2x slower
    
    def test_timezone_cache_memory_usage(self):
        """Test that timezone cache doesn't grow excessively."""
        # Clear cache
        self.clock.timezone_cache.clear()
        
        # Add many timezones
        timezones = [
            "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
            "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Rome",
            "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Asia/Dubai",
            "Australia/Sydney", "Australia/Melbourne", "Pacific/Auckland"
        ]
        
        for tz in timezones:
            self.clock._get_timezone_info(tz)
        
        # Cache should contain all timezones
        assert len(self.clock.timezone_cache) == len(timezones)
        
        # Adding same timezones again shouldn't increase cache size
        for tz in timezones:
            self.clock._get_timezone_info(tz)
        
        assert len(self.clock.timezone_cache) == len(timezones)
    
    def test_concurrent_timezone_access(self):
        """Test that timezone caching works correctly under concurrent access simulation."""
        timezone_name = "America/New_York"
        
        # Simulate concurrent access by calling the same timezone multiple times
        results = []
        for _ in range(10):
            tz = self.clock._get_timezone_info(timezone_name)
            results.append(tz)
        
        # All results should be the same object (from cache)
        assert all(tz is results[0] for tz in results)
    
    def test_large_event_cleanup_performance(self):
        """Test performance of cleaning up many events."""
        # Schedule many events
        base_time = datetime.now(UTC)
        for i in range(500):
            trigger_time = base_time + timedelta(seconds=i)
            self.clock.schedule_event(f"event_{i}", trigger_time, "test", {})
        
        # Trigger all events (simulate cleanup)
        start_time = time.time()
        triggered = self.clock.trigger_scheduled_events()
        cleanup_time = time.time() - start_time
        
        # Should clean up quickly
        assert cleanup_time < 0.5
        assert len(triggered) == 500
        assert len(self.clock.scheduled_events) == 0


class TestMasterClockScalability:
    """Scalability tests for MasterClock operations."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.clock = MasterClock()
    
    def test_large_timezone_dataset(self):
        """Test performance with a large number of different timezones."""
        # Use a comprehensive list of timezones
        timezones = [
            "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
            "America/Anchorage", "America/Honolulu", "America/Toronto", "America/Vancouver",
            "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Rome", "Europe/Madrid",
            "Europe/Amsterdam", "Europe/Stockholm", "Europe/Moscow", "Europe/Istanbul",
            "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Asia/Dubai", "Asia/Singapore",
            "Asia/Seoul", "Asia/Bangkok", "Asia/Jakarta", "Asia/Manila",
            "Australia/Sydney", "Australia/Melbourne", "Australia/Perth", "Australia/Adelaide",
            "Pacific/Auckland", "Pacific/Fiji", "Pacific/Honolulu"
        ]
        
        start_time = time.time()
        
        # Convert current time to all timezones
        for tz in timezones:
            self.clock.now_local(tz)
        
        total_time = time.time() - start_time
        
        # Should handle 30+ timezones efficiently
        assert total_time < 2.0
        assert len(self.clock.timezone_cache) == len(timezones)
    
    def test_high_frequency_time_queries(self):
        """Test performance under high-frequency time queries."""
        iterations = 10000
        
        start_time = time.time()
        
        for _ in range(iterations):
            self.clock.now_utc()
        
        total_time = time.time() - start_time
        avg_time_per_query = total_time / iterations
        
        # Should be very fast per query
        assert avg_time_per_query < 0.001  # Less than 1ms per query
    
    def test_mixed_operations_performance(self):
        """Test performance of mixed operations (typical usage pattern)."""
        operations = 1000
        
        start_time = time.time()
        
        for i in range(operations):
            # Mix of different operations
            if i % 4 == 0:
                self.clock.now_utc()
            elif i % 4 == 1:
                self.clock.now_local("America/New_York")
            elif i % 4 == 2:
                self.clock.seconds_since(datetime.now(UTC) - timedelta(seconds=1))
            else:
                self.clock.get_time_info()
        
        total_time = time.time() - start_time
        
        # Should handle mixed operations efficiently
        assert total_time < 1.0
