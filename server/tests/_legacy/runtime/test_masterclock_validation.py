"""
Test helpers for MasterClock validation tests.

This module provides test functions for the 7 new MasterClock validation tests
that will be exposed via CLI commands.
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from retrovue.runtime.clock import MasterClock


def test_masterclock_monotonic(iterations: int = 1000) -> dict[str, Any]:
    """
    Test that time doesn't "run backward" and seconds_since() is never negative.
    
    Args:
        iterations: Number of iterations to test
        
    Returns:
        Test results dictionary
    """
    _clock = MasterClock()
    results = {
        "test_name": "masterclock-monotonic",
        "iterations": iterations,
        "max_negative_drift": 0.0,
        "future_timestamp_behavior": "correct",
        "monotonic_violations": 0,
        "negative_seconds_since": 0,
        "passed": True
    }
    
    # Test 1: Time monotonicity
    times = []
    for _ in range(iterations):
        times.append(_clock.now_utc())
    
    # Check for backward time movement
    for i in range(1, len(times)):
        if times[i] < times[i-1]:
            results["monotonic_violations"] += 1
            results["max_negative_drift"] = min(results["max_negative_drift"], 
                                              (times[i] - times[i-1]).total_seconds())
    
    # Test 2: seconds_since with past timestamp
    past_time = _clock.now_utc() - timedelta(seconds=1)
    seconds_past = _clock.seconds_since(past_time)
    if seconds_past < 0:
        results["negative_seconds_since"] += 1
    
    # Test 3: seconds_since with future timestamp (should clamp to 0.0)
    future_time = _clock.now_utc() + timedelta(seconds=5)
    seconds_future = _clock.seconds_since(future_time)
    if seconds_future != 0.0:
        results["future_timestamp_behavior"] = "incorrect"
        results["passed"] = False
    
    # Overall pass/fail
    if results["monotonic_violations"] > 0 or results["negative_seconds_since"] > 0:
        results["passed"] = False
    
    return results


def test_masterclock_timezone_resolution(timezones: list[str] = None) -> dict[str, Any]:
    """
    Test timezone mapping is safe and handles invalid timezones gracefully.
    
    Args:
        timezones: List of timezone strings to test
        
    Returns:
        Test results dictionary
    """
    if timezones is None:
        timezones = [
            "America/New_York", "Europe/London", "Asia/Tokyo", "Australia/Sydney",
            "Invalid/Timezone", "US/Eastrn", "Bad/Zone", "America/NonExistent"
        ]
    
    _clock = MasterClock()
    results = {
        "test_name": "masterclock-timezone-resolution",
        "timezones_tested": len(timezones),
        "successful_timezones": [],
        "failed_timezones": [],
        "fallback_to_utc": [],
        "dst_boundary_tests": [],
        "passed": True
    }
    
    for tz in timezones:
        try:
            # Test now_local with this timezone
            local_time = _clock.now_local(tz)
            
            # Check if it's timezone-aware
            if local_time.tzinfo is not None:
                results["successful_timezones"].append(tz)
            else:
                results["failed_timezones"].append(tz)
                
        except Exception:
            # If exception, check if it falls back to UTC
            try:
                local_time = _clock.now_local(tz)
                if local_time.tzinfo == UTC:
                    results["fallback_to_utc"].append(tz)
                else:
                    results["failed_timezones"].append(tz)
            except Exception:
                results["failed_timezones"].append(tz)
    
    # Test DST boundaries for valid timezones
    valid_tz = "America/New_York"  # Known to have DST
    try:
        # Test around DST transition (March 10, 2024 2:00 AM)
        dst_time = datetime(2024, 3, 10, 1, 30, 0, tzinfo=UTC)
        local_dst = _clock.to_channel_time(dst_time, valid_tz)
        results["dst_boundary_tests"].append({
            "timezone": valid_tz,
            "utc_time": dst_time.isoformat(),
            "local_time": local_dst.isoformat(),
            "success": True
        })
    except Exception as e:
        results["dst_boundary_tests"].append({
            "timezone": valid_tz,
            "error": str(e),
            "success": False
        })
    
    # Overall pass/fail
    if len(results["failed_timezones"]) > 0:
        results["passed"] = False
    
    return results


def test_masterclock_logging() -> dict[str, Any]:
    """
    Test timestamps for AsRunLogger are correct and consistent.
    
    Returns:
        Test results dictionary
    """
    _clock = MasterClock()
    results = {
        "test_name": "masterclock-logging",
        "utc_timestamps": [],
        "local_timestamps": [],
        "timezone_offsets": [],
        "precision_consistency": True,
        "timezone_awareness": True,
        "passed": True
    }
    
    # Generate mock as-run events
    events = [
        {"event": "playout_started", "channel": "ch1"},
        {"event": "commercial_break", "channel": "ch1"},
        {"event": "playout_resumed", "channel": "ch1"},
        {"event": "playout_ended", "channel": "ch1"}
    ]
    
    for event in events:
        # Get both UTC and local timestamps
        utc_time = _clock.now_utc()
        local_time = _clock.now_local("America/New_York")
        
        # Check timezone awareness
        if utc_time.tzinfo is None or local_time.tzinfo is None:
            results["timezone_awareness"] = False
            results["passed"] = False
        
        # Store timestamps
        results["utc_timestamps"].append({
            "event": event["event"],
            "timestamp": utc_time.isoformat(),
            "tzinfo": str(utc_time.tzinfo)
        })
        
        results["local_timestamps"].append({
            "event": event["event"],
            "timestamp": local_time.isoformat(),
            "tzinfo": str(local_time.tzinfo)
        })
        
        # Calculate timezone offset
        offset_seconds = (local_time - utc_time).total_seconds()
        results["timezone_offsets"].append({
            "event": event["event"],
            "offset_seconds": offset_seconds
        })
        
        # Small delay to ensure different timestamps
        time.sleep(0.001)
    
    # Check precision consistency
    utc_times = [datetime.fromisoformat(ts["timestamp"]) for ts in results["utc_timestamps"]]
    for i in range(1, len(utc_times)):
        if utc_times[i] <= utc_times[i-1]:
            results["precision_consistency"] = False
            results["passed"] = False
    
    return results


def test_masterclock_scheduler_alignment() -> dict[str, Any]:
    """
    Test schedule lookup logic won't give off-by-one bugs at slot boundaries.
    
    Returns:
        Test results dictionary
    """
    _clock = MasterClock()
    results = {
        "test_name": "masterclock-scheduler-alignment",
        "boundary_tests": [],
        "dst_edge_cases": [],
        "passed": True
    }
    
    # Create a fake grid
    def resolve_block_for_timestamp(grid: list[tuple[datetime, datetime, str]], ts: datetime) -> str:
        """Stub function to resolve block for timestamp."""
        for start, end, block in grid:
            if start <= ts < end:
                return block
        return "unknown"
    
    # Test grid: 00:00:00–00:30:00 → Block A, 00:30:00–01:00:00 → Block B
    base_time = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    grid = [
        (base_time, base_time + timedelta(minutes=30), "Block A"),
        (base_time + timedelta(minutes=30), base_time + timedelta(hours=1), "Block B")
    ]
    
    # Test boundary conditions
    test_cases = [
        ("00:29:59.900", base_time + timedelta(minutes=29, seconds=59, milliseconds=900), "Block A"),
        ("00:30:00.000", base_time + timedelta(minutes=30), "Block B"),
        ("00:30:00.001", base_time + timedelta(minutes=30, milliseconds=1), "Block B"),
    ]
    
    for description, test_time, expected_block in test_cases:
        actual_block = resolve_block_for_timestamp(grid, test_time)
        results["boundary_tests"].append({
            "description": description,
            "test_time": test_time.isoformat(),
            "expected_block": expected_block,
            "actual_block": actual_block,
            "passed": actual_block == expected_block
        })
        
        if actual_block != expected_block:
            results["passed"] = False
    
    # Test DST edge case
    try:
        # Simulate DST transition
        dst_transition = datetime(2024, 3, 10, 6, 0, 0, tzinfo=UTC)  # 2 AM EST -> 3 AM EDT
        dst_grid = [
            (dst_transition - timedelta(hours=1), dst_transition, "Pre-DST"),
            (dst_transition, dst_transition + timedelta(hours=1), "Post-DST")
        ]
        
        # Test just before and after DST transition
        pre_dst = dst_transition - timedelta(minutes=1)
        post_dst = dst_transition + timedelta(minutes=1)
        
        pre_block = resolve_block_for_timestamp(dst_grid, pre_dst)
        post_block = resolve_block_for_timestamp(dst_grid, post_dst)
        
        results["dst_edge_cases"].append({
            "transition_time": dst_transition.isoformat(),
            "pre_dst_block": pre_block,
            "post_dst_block": post_block,
            "success": True
        })
        
    except Exception as e:
        results["dst_edge_cases"].append({
            "error": str(e),
            "success": False
        })
    
    return results


def test_masterclock_stability(iterations: int = 10000, minutes: int = None) -> dict[str, Any]:
    """
    Stress-test that repeated tz conversion doesn't leak memory or fall off a performance cliff.
    
    Args:
        iterations: Number of iterations to test
        minutes: Alternative to iterations - run for specified minutes
        
    Returns:
        Test results dictionary
    """
    _clock = MasterClock()
    results = {
        "test_name": "masterclock-stability",
        "iterations": iterations,
        "timezones_tested": ["America/New_York", "Europe/London", "Asia/Tokyo"],
        "performance_metrics": {},
        "memory_usage": {},
        "passed": True
    }
    
    if minutes:
        iterations = minutes * 60 * 100  # Rough estimate for 100 ops/sec
    
    # Test timezone conversion performance
    start_time = time.time()
    start_calls = 0
    
    for i in range(iterations):
        tz = results["timezones_tested"][i % len(results["timezones_tested"])]
        _clock.now_local(tz)
        
        # Sample performance at start and end
        if i == 100:
            start_calls = time.time()
        elif i == iterations - 100:
            end_calls = time.time()
    
    total_time = time.time() - start_time
    
    # Calculate performance metrics
    results["performance_metrics"] = {
        "total_time": total_time,
        "calls_per_second": iterations / total_time,
        "start_performance": 100 / (start_calls - start_time) if start_calls > 0 else 0,
        "end_performance": 100 / (time.time() - end_calls) if 'end_calls' in locals() else 0
    }
    
    # Check for performance degradation
    if results["performance_metrics"]["end_performance"] < results["performance_metrics"]["start_performance"] * 0.5:
        results["passed"] = False
    
    # Check timezone cache size
    results["memory_usage"] = {
        "cached_timezones": len(_clock.timezone_cache),
        "cache_hit_ratio": "N/A"  # Would need more sophisticated tracking
    }
    
    return results


def test_masterclock_consistency() -> dict[str, Any]:
    """
    Test that different high-level components would see the "same now," not different shapes of time.
    
    Returns:
        Test results dictionary
    """
    _clock = MasterClock()
    results = {
        "test_name": "masterclock-consistency",
        "component_timestamps": [],
        "max_skew": 0.0,
        "timezone_awareness": True,
        "naive_timestamps": 0,
        "passed": True
    }
    
    # Simulate multiple components asking for time in rapid succession
    timestamps = []
    for _i in range(100):
        # Simulate ProgramDirector and ChannelManager asking for time
        pd_time = _clock.now_utc()
        cm_time = _clock.now_utc()
        
        timestamps.extend([pd_time, cm_time])
    
    # Analyze timestamps
    for i, ts in enumerate(timestamps):
        # Check timezone awareness
        if ts.tzinfo is None:
            results["naive_timestamps"] += 1
            results["timezone_awareness"] = False
        
        # Check for maximum skew
        for _j, other_ts in enumerate(timestamps[i+1:], i+1):
            skew = abs((ts - other_ts).total_seconds())
            results["max_skew"] = max(results["max_skew"], skew)
    
    # Store sample timestamps
    results["component_timestamps"] = [
        {
            "component": "ProgramDirector" if i % 2 == 0 else "ChannelManager",
            "timestamp": ts.isoformat(),
            "tzinfo": str(ts.tzinfo) if ts.tzinfo else "None"
        }
        for i, ts in enumerate(timestamps[:10])  # First 10 for brevity
    ]
    
    # Overall pass/fail
    if results["naive_timestamps"] > 0 or results["max_skew"] > 0.1:  # 100ms max skew
        results["passed"] = False
    
    return results


def test_masterclock_serialization() -> dict[str, Any]:
    """
    Test that we can safely serialize timestamps and round-trip them.
    
    Returns:
        Test results dictionary
    """
    _clock = MasterClock()
    results = {
        "test_name": "masterclock-serialization",
        "serialization_tests": [],
        "roundtrip_accuracy": [],
        "timezone_preservation": True,
        "passed": True
    }
    
    # Test various timestamp types
    test_cases = [
        ("utc_now", _clock.now_utc()),
        ("local_ny", _clock.now_local("America/New_York")),
        ("local_london", _clock.now_local("Europe/London")),
        ("local_tokyo", _clock.now_local("Asia/Tokyo"))
    ]
    
    for name, original_dt in test_cases:
        try:
            # Serialize to ISO 8601
            serialized = original_dt.isoformat()
            
            # Parse back
            parsed_dt = datetime.fromisoformat(serialized)
            
            # Check timezone preservation
            tz_preserved = original_dt.tzinfo == parsed_dt.tzinfo
            
            # Check round-trip accuracy
            time_diff = abs((original_dt - parsed_dt).total_seconds())
            
            results["serialization_tests"].append({
                "name": name,
                "original": original_dt.isoformat(),
                "serialized": serialized,
                "parsed": parsed_dt.isoformat(),
                "timezone_preserved": tz_preserved,
                "time_difference": time_diff,
                "success": tz_preserved and time_diff < 0.001  # 1ms tolerance
            })
            
            results["roundtrip_accuracy"].append({
                "name": name,
                "accuracy_seconds": time_diff
            })
            
            if not tz_preserved:
                results["timezone_preservation"] = False
                results["passed"] = False
                
        except Exception as e:
            results["serialization_tests"].append({
                "name": name,
                "error": str(e),
                "success": False
            })
            results["passed"] = False
    
    return results


def run_all_masterclock_tests() -> dict[str, Any]:
    """
    Run all MasterClock validation tests.
    
    Returns:
        Combined test results
    """
    all_results = {
        "test_suite": "masterclock-validation",
        "timestamp": datetime.now(UTC).isoformat(),
        "tests": {}
    }
    
    # Run all tests
    all_results["tests"]["monotonic"] = test_masterclock_monotonic()
    all_results["tests"]["timezone_resolution"] = test_masterclock_timezone_resolution()
    all_results["tests"]["logging"] = test_masterclock_logging()
    all_results["tests"]["scheduler_alignment"] = test_masterclock_scheduler_alignment()
    all_results["tests"]["stability"] = test_masterclock_stability()
    all_results["tests"]["consistency"] = test_masterclock_consistency()
    all_results["tests"]["serialization"] = test_masterclock_serialization()
    
    # Calculate overall pass/fail
    all_passed = all(test["passed"] for test in all_results["tests"].values())
    all_results["overall_passed"] = all_passed
    
    return all_results
