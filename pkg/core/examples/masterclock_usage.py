#!/usr/bin/env python3
"""
MasterClock Usage Example

This example demonstrates how to use MasterClock in a RetroVue application.
It shows typical usage patterns for different components.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from retrovue.runtime.clock import MasterClock, TimePrecision


def demonstrate_basic_usage():
    """Demonstrate basic MasterClock usage."""
    print("=== Basic MasterClock Usage ===")
    
    # Create a MasterClock instance
    clock = MasterClock()
    
    # Get current UTC time
    utc_time = clock.now_utc()
    print(f"Current UTC time: {utc_time}")
    
    # Get local time in different timezones
    ny_time = clock.now_local("America/New_York")
    london_time = clock.now_local("Europe/London")
    tokyo_time = clock.now_local("Asia/Tokyo")
    
    print(f"New York time: {ny_time}")
    print(f"London time: {london_time}")
    print(f"Tokyo time: {tokyo_time}")
    
    # Calculate time differences
    reference_time = utc_time - timedelta(minutes=30)
    seconds_elapsed = clock.seconds_since(reference_time)
    print(f"Seconds since 30 minutes ago: {seconds_elapsed:.2f}")


def demonstrate_schedule_service_usage():
    """Demonstrate how ScheduleService would use MasterClock."""
    print("\n=== ScheduleService Usage ===")
    
    clock = MasterClock()
    
    # Simulate ScheduleService getting current time for schedule queries
    station_time = clock.now_utc()
    print(f"Station time for schedule query: {station_time}")
    
    # Get channel-specific time
    channel_time = clock.now_local("America/Los_Angeles")
    print(f"Channel time (LA): {channel_time}")
    
    # Calculate offset for mid-program joins
    program_start = station_time - timedelta(minutes=15)
    offset_seconds = clock.seconds_since(program_start)
    print(f"Program started {offset_seconds:.2f} seconds ago")
    
    # Convert between timezones for multi-channel operations
    utc_program_time = datetime(2024, 1, 15, 20, 0, 0, tzinfo=UTC)
    ny_program_time = clock.convert_timezone(utc_program_time, "UTC", "America/New_York")
    print(f"Program at 8 PM UTC is {ny_program_time.strftime('%I:%M %p %Z')} in New York")


def demonstrate_channel_manager_usage():
    """Demonstrate how ChannelManager would use MasterClock."""
    print("\n=== ChannelManager Usage ===")
    
    clock = MasterClock()
    
    # Simulate viewer joining mid-program
    program_start_time = clock.now_utc() - timedelta(minutes=20)
    viewer_join_time = clock.now_utc()
    
    # Calculate playback offset
    playback_offset = clock.seconds_since(program_start_time)
    print(f"Viewer joined {playback_offset:.2f} seconds into the program")
    
    # Get channel-specific time for logging
    channel_time = clock.get_channel_time("channel_1", "America/Chicago")
    print(f"Channel time (Chicago): {channel_time}")
    
    # Simulate health check timing
    health_check_time = clock.now_utc()
    print(f"Health check performed at: {health_check_time}")


def demonstrate_program_director_usage():
    """Demonstrate how ProgramDirector would use MasterClock."""
    print("\n=== ProgramDirector Usage ===")
    
    clock = MasterClock()
    
    # Schedule emergency override
    override_time = clock.now_utc() + timedelta(seconds=30)
    clock.schedule_event(
        "emergency_override",
        override_time,
        "emergency",
        {"channels": ["channel_1", "channel_2"], "reason": "breaking_news"}
    )
    print(f"Emergency override scheduled for: {override_time}")
    
    # Check scheduled events
    now = clock.now_utc()
    future_events = clock.get_scheduled_events(now, now + timedelta(minutes=1))
    print(f"Events in next minute: {len(future_events)}")
    
    # Simulate time passing and trigger events
    print("Simulating time passage...")
    # In real usage, time would naturally pass
    # For demo, we'll manually trigger if any events are due
    triggered = clock.trigger_scheduled_events()
    if triggered:
        for event in triggered:
            print(f"Triggered event: {event.event_id} - {event.event_type}")


def demonstrate_asrun_logger_usage():
    """Demonstrate how AsRunLogger would use MasterClock."""
    print("\n=== AsRunLogger Usage ===")
    
    clock = MasterClock()
    
    # Log playout events with timestamps
    events = [
        {"event": "playout_started", "content": "movie_123", "channel": "channel_1"},
        {"event": "commercial_break", "duration": 120, "channel": "channel_1"},
        {"event": "playout_resumed", "content": "movie_123", "channel": "channel_1"},
    ]
    
    for event_data in events:
        timestamp = clock.now_utc()
        log_entry = {
            "timestamp": timestamp.isoformat(),
            **event_data
        }
        print(f"Logged: {log_entry}")


def demonstrate_precision_levels():
    """Demonstrate different precision levels."""
    print("\n=== Precision Levels ===")
    
    # Test different precision levels
    for precision in TimePrecision:
        clock = MasterClock(precision)
        time_now = clock.now_utc()
        print(f"{precision.value} precision: {time_now} (microseconds: {time_now.microsecond})")


def demonstrate_timezone_handling():
    """Demonstrate timezone handling capabilities."""
    print("\n=== Timezone Handling ===")
    
    clock = MasterClock()
    
    # Test DST transition handling
    # Create a time during DST transition (second Sunday in March)
    dst_transition = datetime(2024, 3, 10, 6, 0, 0, tzinfo=UTC)
    
    # Convert to New York time (should handle DST)
    ny_time = clock.convert_timezone(dst_transition, "UTC", "America/New_York")
    print(f"DST transition time in NY: {ny_time}")
    
    # Test timezone info
    tz_info = clock.get_timezone_info("America/New_York")
    print(f"NY timezone info: {tz_info}")


def main():
    """Run all demonstrations."""
    print("MasterClock Usage Examples")
    print("=" * 50)
    
    try:
        demonstrate_basic_usage()
        demonstrate_schedule_service_usage()
        demonstrate_channel_manager_usage()
        demonstrate_program_director_usage()
        demonstrate_asrun_logger_usage()
        demonstrate_precision_levels()
        demonstrate_timezone_handling()
        
        print("\n" + "=" * 50)
        print("✅ All examples completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
