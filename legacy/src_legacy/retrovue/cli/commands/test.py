"""
Test command group.

Surfaces testing capabilities for runtime components including MasterClock.
Provides test execution, performance testing, and debugging tools.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from ...runtime.clock import MasterClock, TimePrecision
from ...tests.runtime.test_broadcast_day_alignment import (
    test_broadcast_day_alignment,
)
from ...tests.runtime.test_masterclock_validation import (
    test_masterclock_consistency,
    test_masterclock_logging,
    test_masterclock_monotonic,
    test_masterclock_scheduler_alignment,
    test_masterclock_serialization,
    test_masterclock_stability,
    test_masterclock_timezone_resolution,
)

app = typer.Typer(name="test", help="Testing operations for runtime components")


@app.command("masterclock")
def test_masterclock(
    precision: str = typer.Option(
        "millisecond", "--precision", "-p", help="Time precision: second, millisecond, microsecond"
    ),
    test_timezone: str = typer.Option("America/New_York", "--timezone", "-t", help="Test timezone"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test MasterClock functionality with live examples."""

    # Parse precision
    try:
        precision_enum = TimePrecision(precision)
    except ValueError:
        typer.echo(
            f"Invalid precision: {precision}. Must be one of: second, millisecond, microsecond",
            err=True,
        )
        raise typer.Exit(1)

    # Create MasterClock instance
    clock = MasterClock(precision_enum)

    if json_output:
        # JSON output for programmatic use
        result = {
            "precision": precision,
            "test_timezone": test_timezone,
            "utc_time": clock.now_utc().isoformat(),
            "local_time": clock.now_local(test_timezone).isoformat(),
            "timezone_info": clock.get_timezone_info(test_timezone),
            "synchronized": clock.is_synchronized,
            "cached_timezones": list(clock.timezone_cache.keys()),
        }
        typer.echo(json.dumps(result, indent=2))
    else:
        # Human-readable output
        typer.echo("MasterClock Test Results")
        typer.echo("=" * 40)
        typer.echo(f"Precision: {precision}")
        typer.echo(f"Test Timezone: {test_timezone}")
        typer.echo()

        # Basic time operations
        utc_time = clock.now_utc()
        local_time = clock.now_local(test_timezone)

        typer.echo("Time Operations:")
        typer.echo(f"  UTC Time: {utc_time}")
        typer.echo(f"  Local Time ({test_timezone}): {local_time}")
        typer.echo()

        # Timezone information
        tz_info = clock.get_timezone_info(test_timezone)
        typer.echo("Timezone Information:")
        typer.echo(f"  Name: {tz_info['name']}")
        typer.echo(f"  Offset: {tz_info['offset']}")
        typer.echo(f"  DST: {tz_info['dst']}")
        typer.echo()

        # Performance test
        typer.echo("Performance Test:")
        start_time = time.time()
        for _ in range(1000):
            clock.now_utc()
        end_time = time.time()
        duration = end_time - start_time
        typer.echo(
            f"  1000 UTC queries in {duration:.4f} seconds ({1000 / duration:.0f} queries/sec)"
        )

        # Timezone conversion test
        typer.echo()
        typer.echo("Timezone Conversion Test:")
        test_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        converted_time = clock.convert_timezone(test_time, "UTC", test_timezone)
        typer.echo(f"  UTC: {test_time}")
        typer.echo(f"  {test_timezone}: {converted_time}")

        typer.echo()
        typer.echo("MasterClock test completed successfully!")


@app.command("masterclock-events")
def test_masterclock_events(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test MasterClock event scheduling functionality."""

    clock = MasterClock()

    # Schedule some test events
    now = clock.now_utc()
    events = [
        ("immediate", now + timedelta(seconds=1), "test", {"type": "immediate"}),
        ("short", now + timedelta(seconds=5), "test", {"type": "short"}),
        ("medium", now + timedelta(minutes=1), "test", {"type": "medium"}),
    ]

    for event_id, trigger_time, event_type, payload in events:
        clock.schedule_event(event_id, trigger_time, event_type, payload)

    if json_output:
        result = {
            "scheduled_events": len(clock.scheduled_events),
            "events": [
                {
                    "id": event.event_id,
                    "trigger_time": event.trigger_time.isoformat(),
                    "type": event.event_type,
                    "payload": event.payload,
                }
                for event in clock.scheduled_events.values()
            ],
        }
        typer.echo(json.dumps(result, indent=2))
    else:
        typer.echo("MasterClock Event Scheduling Test")
        typer.echo("=" * 40)
        typer.echo(f"Scheduled Events: {len(clock.scheduled_events)}")
        typer.echo()

        for event in clock.scheduled_events.values():
            typer.echo(f"  Event: {event.event_id}")
            typer.echo(f"     Trigger: {event.trigger_time}")
            typer.echo(f"     Type: {event.event_type}")
            typer.echo(f"     Payload: {event.payload}")
            typer.echo()

        # Test event querying
        future_events = clock.get_scheduled_events(now, now + timedelta(minutes=2))
        typer.echo(f"Events in next 2 minutes: {len(future_events)}")

        typer.echo()
        typer.echo("Event scheduling test completed!")


@app.command("masterclock-performance")
def test_masterclock_performance(
    iterations: int = typer.Option(
        10000, "--iterations", "-i", help="Number of iterations for performance test"
    ),
    timezones: int = typer.Option(
        10, "--timezones", "-t", help="Number of different timezones to test"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test MasterClock performance characteristics."""

    clock = MasterClock()

    # Test timezones
    test_timezones = [
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "Europe/London",
        "Europe/Paris",
        "Europe/Berlin",
        "Asia/Tokyo",
        "Asia/Shanghai",
        "Australia/Sydney",
    ][:timezones]

    if json_output:
        # JSON output for programmatic use
        results = {}

        # UTC query performance
        start_time = time.time()
        for _ in range(iterations):
            clock.now_utc()
        utc_duration = time.time() - start_time

        # Timezone conversion performance
        start_time = time.time()
        for tz in test_timezones:
            for _ in range(iterations // len(test_timezones)):
                clock.now_local(tz)
        tz_duration = time.time() - start_time

        # Event scheduling performance
        start_time = time.time()
        for i in range(min(iterations, 1000)):  # Limit events for memory
            trigger_time = clock.now_utc() + timedelta(seconds=i)
            clock.schedule_event(f"perf_event_{i}", trigger_time, "performance", {"iteration": i})
        event_duration = time.time() - start_time

        results = {
            "iterations": iterations,
            "timezones_tested": len(test_timezones),
            "utc_queries": {
                "duration": utc_duration,
                "queries_per_second": iterations / utc_duration,
            },
            "timezone_conversions": {
                "duration": tz_duration,
                "conversions_per_second": iterations / tz_duration,
            },
            "event_scheduling": {
                "duration": event_duration,
                "events_scheduled": min(iterations, 1000),
                "events_per_second": min(iterations, 1000) / event_duration,
            },
            "cached_timezones": len(clock.timezone_cache),
        }

        typer.echo(json.dumps(results, indent=2))
    else:
        # Human-readable output
        typer.echo("MasterClock Performance Test")
        typer.echo("=" * 40)
        typer.echo(f"Iterations: {iterations:,}")
        typer.echo(f"Timezones: {len(test_timezones)}")
        typer.echo()

        # UTC query performance
        typer.echo("UTC Query Performance:")
        start_time = time.time()
        for _ in range(iterations):
            clock.now_utc()
        utc_duration = time.time() - start_time
        typer.echo(f"  Duration: {utc_duration:.4f} seconds")
        typer.echo(f"  Queries/sec: {iterations / utc_duration:,.0f}")
        typer.echo()

        # Timezone conversion performance
        typer.echo("Timezone Conversion Performance:")
        start_time = time.time()
        for tz in test_timezones:
            for _ in range(iterations // len(test_timezones)):
                clock.now_local(tz)
        tz_duration = time.time() - start_time
        typer.echo(f"  Duration: {tz_duration:.4f} seconds")
        typer.echo(f"  Conversions/sec: {iterations / tz_duration:,.0f}")
        typer.echo()

        # Event scheduling performance
        typer.echo("Event Scheduling Performance:")
        event_count = min(iterations, 1000)  # Limit for memory
        start_time = time.time()
        for i in range(event_count):
            trigger_time = clock.now_utc() + timedelta(seconds=i)
            clock.schedule_event(f"perf_event_{i}", trigger_time, "performance", {"iteration": i})
        event_duration = time.time() - start_time
        typer.echo(f"  Events scheduled: {event_count:,}")
        typer.echo(f"  Duration: {event_duration:.4f} seconds")
        typer.echo(f"  Events/sec: {event_count / event_duration:,.0f}")
        typer.echo()

        # Cache information
        typer.echo("Cache Information:")
        typer.echo(f"  Cached timezones: {len(clock.timezone_cache)}")
        typer.echo(f"  Scheduled events: {len(clock.scheduled_events)}")

        typer.echo()
        typer.echo("Performance test completed!")


@app.command("masterclock-integration")
def test_masterclock_integration(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test MasterClock integration patterns with other components."""

    clock = MasterClock()

    # Simulate ScheduleService usage
    station_time = clock.now_utc()
    channel_time = clock.now_local("America/New_York")
    program_start = station_time - timedelta(minutes=30)
    offset_seconds = clock.seconds_since(program_start)

    # Simulate ChannelManager usage
    viewer_join_time = clock.now_utc()
    playback_offset = clock.seconds_since(program_start)

    # Simulate ProgramDirector usage
    emergency_time = clock.now_utc() + timedelta(seconds=30)
    clock.schedule_event(
        "emergency_override", emergency_time, "emergency", {"channels": ["ch1", "ch2"]}
    )

    # Simulate AsRunLogger usage
    log_entries = [
        {"event": "playout_started", "timestamp": clock.now_utc().isoformat()},
        {"event": "commercial_break", "timestamp": clock.now_utc().isoformat()},
        {"event": "playout_resumed", "timestamp": clock.now_utc().isoformat()},
    ]

    if json_output:
        result = {
            "schedule_service": {
                "station_time": station_time.isoformat(),
                "channel_time": channel_time.isoformat(),
                "program_offset_seconds": offset_seconds,
            },
            "channel_manager": {
                "viewer_join_time": viewer_join_time.isoformat(),
                "playback_offset_seconds": playback_offset,
            },
            "program_director": {
                "emergency_scheduled": True,
                "emergency_time": emergency_time.isoformat(),
                "scheduled_events": len(clock.scheduled_events),
            },
            "asrun_logger": {"log_entries": log_entries},
        }
        typer.echo(json.dumps(result, indent=2))
    else:
        typer.echo("MasterClock Integration Test")
        typer.echo("=" * 40)

        typer.echo("ScheduleService Integration:")
        typer.echo(f"  Station time: {station_time}")
        typer.echo(f"  Channel time (NY): {channel_time}")
        typer.echo(f"  Program offset: {offset_seconds:.2f} seconds")
        typer.echo()

        typer.echo("ChannelManager Integration:")
        typer.echo(f"  Viewer join time: {viewer_join_time}")
        typer.echo(f"  Playback offset: {playback_offset:.2f} seconds")
        typer.echo()

        typer.echo("ProgramDirector Integration:")
        typer.echo(f"  Emergency scheduled: {emergency_time}")
        typer.echo(f"  Scheduled events: {len(clock.scheduled_events)}")
        typer.echo()

        typer.echo("AsRunLogger Integration:")
        for entry in log_entries:
            typer.echo(f"  {entry['event']}: {entry['timestamp']}")

        typer.echo()
        typer.echo("Integration test completed!")


@app.command("masterclock-monotonic")
def test_masterclock_monotonic_cmd(
    iterations: int = typer.Option(1000, "--iterations", "-i", help="Number of iterations to test"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test that time doesn't 'run backward' and seconds_since() is never negative."""

    results = test_masterclock_monotonic(iterations)

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        typer.echo("MasterClock Monotonic Test")
        typer.echo("=" * 40)
        typer.echo(f"Iterations: {results['iterations']:,}")
        typer.echo(f"Monotonic violations: {results['monotonic_violations']}")
        typer.echo(f"Max negative drift: {results['max_negative_drift']:.6f} seconds")
        typer.echo(f"Future timestamp behavior: {results['future_timestamp_behavior']}")
        typer.echo(f"Negative seconds_since calls: {results['negative_seconds_since']}")
        typer.echo()
        if results["passed"]:
            typer.echo(
                "[PASS] Test PASSED - Time is monotonic and seconds_since() behaves correctly"
            )
        else:
            typer.echo("[FAIL] Test FAILED - Time monotonicity issues detected")
            raise typer.Exit(1)


@app.command("masterclock-timezone-resolution")
def test_masterclock_timezone_resolution_cmd(
    timezones: str = typer.Option(
        "", "--timezones", "-t", help="Comma-separated list of timezones to test"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test timezone mapping is safe and handles invalid timezones gracefully."""

    timezone_list = timezones.split(",") if timezones else None
    results = test_masterclock_timezone_resolution(timezone_list)

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        typer.echo("MasterClock Timezone Resolution Test")
        typer.echo("=" * 40)
        typer.echo(f"Timezones tested: {results['timezones_tested']}")
        typer.echo(f"Successful: {len(results['successful_timezones'])}")
        typer.echo(f"Failed: {len(results['failed_timezones'])}")
        typer.echo(f"Fallback to UTC: {len(results['fallback_to_utc'])}")
        typer.echo()

        if results["successful_timezones"]:
            typer.echo("Successful timezones:")
            for tz in results["successful_timezones"]:
                typer.echo(f"  [OK] {tz}")

        if results["fallback_to_utc"]:
            typer.echo("Fallback to UTC:")
            for tz in results["fallback_to_utc"]:
                typer.echo(f"  [WARN] {tz}")

        if results["failed_timezones"]:
            typer.echo("Failed timezones:")
            for tz in results["failed_timezones"]:
                typer.echo(f"  [FAIL] {tz}")

        typer.echo()
        if results["passed"]:
            typer.echo("[PASS] Test PASSED - Timezone resolution working correctly")
        else:
            typer.echo("[FAIL] Test FAILED - Timezone resolution issues detected")
            raise typer.Exit(1)


@app.command("masterclock-logging")
def test_masterclock_logging_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test timestamps for AsRunLogger are correct and consistent."""

    results = test_masterclock_logging()

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        typer.echo("MasterClock Logging Test")
        typer.echo("=" * 40)
        typer.echo(f"Timezone awareness: {'[OK]' if results['timezone_awareness'] else '[FAIL]'}")
        typer.echo(
            f"Precision consistency: {'[OK]' if results['precision_consistency'] else '[FAIL]'}"
        )
        typer.echo()

        typer.echo("Sample timestamps:")
        for i, (utc, local) in enumerate(
            zip(results["utc_timestamps"][:3], results["local_timestamps"][:3])
        ):
            typer.echo(f"  Event {i + 1}:")
            typer.echo(f"    UTC: {utc['timestamp']}")
            typer.echo(f"    Local: {local['timestamp']}")
            typer.echo(
                f"    Offset: {results['timezone_offsets'][i]['offset_seconds']:.1f} seconds"
            )

        typer.echo()
        if results["passed"]:
            typer.echo("[PASS] Test PASSED - Logging timestamps are consistent and timezone-aware")
        else:
            typer.echo("[FAIL] Test FAILED - Logging timestamp issues detected")
            raise typer.Exit(1)


@app.command("masterclock-scheduler-alignment")
def test_masterclock_scheduler_alignment_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test schedule lookup logic won't give off-by-one bugs at slot boundaries."""

    results = test_masterclock_scheduler_alignment()

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        typer.echo("MasterClock Scheduler Alignment Test")
        typer.echo("=" * 40)
        typer.echo("Boundary tests:")
        for test in results["boundary_tests"]:
            status = "[OK]" if test["passed"] else "[FAIL]"
            typer.echo(
                f"  {status} {test['description']}: {test['expected_block']} -> {test['actual_block']}"
            )

        typer.echo()
        typer.echo("DST edge cases:")
        for case in results["dst_edge_cases"]:
            if case.get("success"):
                typer.echo("  [OK] DST transition handled correctly")
            else:
                typer.echo(f"  [FAIL] DST transition error: {case.get('error', 'Unknown')}")

        typer.echo()
        typer.echo("MasterClock Usage Validation:")
        typer.echo(
            f"  Uses MasterClock only: {'[OK]' if results['uses_masterclock_only'] else '[FAIL]'}"
        )
        typer.echo(
            f"  Naive timestamps rejected: {'[OK]' if results['naive_timestamp_rejected'] else '[FAIL]'}"
        )

        if "error" in results:
            typer.echo(f"  Error: {results['error']}")

        typer.echo()
        if results["passed"]:
            typer.echo("[PASS] Test PASSED - Scheduler alignment working correctly")
        else:
            typer.echo("[FAIL] Test FAILED - Scheduler alignment issues detected")
            raise typer.Exit(1)


@app.command("masterclock-stability")
def test_masterclock_stability_cmd(
    iterations: int = typer.Option(
        10000, "--iterations", "-i", help="Number of iterations to test"
    ),
    minutes: int = typer.Option(
        None, "--minutes", "-m", help="Run for specified minutes instead of iterations"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Stress-test that repeated tz conversion doesn't leak memory or fall off a performance cliff."""

    results = test_masterclock_stability(iterations, minutes)

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        typer.echo("MasterClock Stability Test")
        typer.echo("=" * 40)
        typer.echo(f"Iterations: {results['iterations']:,}")
        typer.echo(f"Timezones tested: {', '.join(results['timezones_tested'])}")
        typer.echo()

        perf = results["performance_metrics"]
        typer.echo("Performance metrics:")
        typer.echo(f"  Total iterations: {perf['total_iterations']:,}")
        typer.echo(f"  Test duration: {perf['test_duration_seconds']:.3f} seconds")
        typer.echo(f"  Peak calls/sec: {perf['peak_calls_per_second']:,.0f}")
        typer.echo(f"  Min calls/sec: {perf['min_calls_per_second']:,.0f}")
        typer.echo(f"  Final calls/sec: {perf['final_calls_per_second']:,.0f}")
        typer.echo(f"  Average calls/sec: {perf['average_calls_per_second']:,.0f}")

        memory = results["memory_usage"]
        typer.echo()
        typer.echo("Memory usage:")
        typer.echo(f"  Cached timezones: {memory['cached_timezones']}")

        typer.echo()
        if results["passed"]:
            typer.echo("[PASS] Test PASSED - MasterClock performance is stable")
        else:
            typer.echo("[FAIL] Test FAILED - Performance degradation detected")
            raise typer.Exit(1)


@app.command("masterclock-consistency")
def test_masterclock_consistency_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test that different high-level components would see the 'same now,' not different shapes of time."""

    results = test_masterclock_consistency()

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        typer.echo("MasterClock Consistency Test")
        typer.echo("=" * 40)
        typer.echo(f"Timezone awareness: {'[OK]' if results['timezone_awareness'] else '[FAIL]'}")
        typer.echo(f"Max skew: {results['max_skew_seconds']:.6f} seconds")
        typer.echo(f"Naive timestamps: {results['naive_timestamps']}")
        typer.echo()

        typer.echo("Serialization validation:")
        typer.echo(f"  TZ info preserved: {'[OK]' if results['tzinfo_ok'] else '[FAIL]'}")
        typer.echo(f"  Round-trip accuracy: {'[OK]' if results['roundtrip_ok'] else '[FAIL]'}")

        if "serialization_error" in results:
            typer.echo(f"  Serialization error: {results['serialization_error']}")

        typer.echo()
        typer.echo("Sample component timestamps:")
        for ts in results["component_timestamps"][:5]:
            typer.echo(f"  {ts['component']}: {ts['timestamp']} ({ts['tzinfo']})")

        typer.echo()
        if results["passed"]:
            typer.echo("[PASS] Test PASSED - Components see consistent time")
        else:
            typer.echo("[FAIL] Test FAILED - Time consistency issues detected")
            raise typer.Exit(1)


@app.command("masterclock-serialization")
def test_masterclock_serialization_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test that we can safely serialize timestamps and round-trip them."""

    results = test_masterclock_serialization()

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        typer.echo("MasterClock Serialization Test")
        typer.echo("=" * 40)
        typer.echo(
            f"Timezone preservation: {'[OK]' if results['timezone_preservation'] else '[FAIL]'}"
        )
        typer.echo()

        typer.echo("Serialization tests:")
        for test in results["serialization_tests"]:
            status = "[OK]" if test["success"] else "[FAIL]"
            typer.echo(f"  {status} {test['name']}: {test['time_difference']:.6f}s difference")
            if not test["success"] and "error" in test:
                typer.echo(f"    Error: {test['error']}")

        typer.echo()
        typer.echo("Round-trip accuracy:")
        for acc in results["roundtrip_accuracy"]:
            typer.echo(f"  {acc['name']}: {acc['accuracy_seconds']:.6f} seconds")

        typer.echo()
        if results["passed"]:
            typer.echo("[PASS] Test PASSED - Serialization working correctly")
        else:
            typer.echo("[FAIL] Test FAILED - Serialization issues detected")
            raise typer.Exit(1)


@app.command("run-tests")
def run_tests(
    test_type: str = typer.Option(
        "all", "--type", "-t", help="Test type: all, unit, performance, integration"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Run MasterClock test suite using pytest."""

    # Get project root
    project_root = Path(__file__).parent.parent.parent.parent.parent
    test_dir = project_root / "tests" / "runtime"

    if not test_dir.exists():
        typer.echo(f"Test directory not found: {test_dir}", err=True)
        raise typer.Exit(1)

    # Build pytest command
    cmd = [sys.executable, "-m", "pytest"]

    if test_type == "unit":
        cmd.append("test_clock.py")
    elif test_type == "performance":
        cmd.append("test_clock_performance.py")
    elif test_type == "integration":
        cmd.extend(["test_clock.py", "-k", "integration"])
    else:  # all
        cmd.extend(["test_clock.py", "test_clock_performance.py"])

    if verbose:
        cmd.append("-v")

    if json_output:
        cmd.extend(["--json-report", "--json-report-file=test_results.json"])

    try:
        typer.echo(f"Running tests: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=test_dir, capture_output=True, text=True)

        if json_output:
            typer.echo(result.stdout)
        else:
            typer.echo("Test Results:")
            typer.echo("=" * 40)
            typer.echo(result.stdout)
            if result.stderr:
                typer.echo("Errors:")
                typer.echo(result.stderr)

        if result.returncode == 0:
            typer.echo("All tests passed!")
        else:
            typer.echo("Some tests failed!")
            raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"Error running tests: {e}", err=True)
        raise typer.Exit(1)


@app.command("broadcast-day-alignment")
def test_broadcast_day_alignment_cmd(
    channel_id: str = typer.Option("test_channel_1", "--channel", "-c", help="Test channel ID"),
    channel_timezone: str = typer.Option(
        "America/New_York", "--timezone", "-t", help="Channel timezone"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Test broadcast day alignment for HBO-style 05:00–07:00 scenario."""

    # Run the broadcast day alignment test
    result = test_broadcast_day_alignment(channel_id, channel_timezone)

    if json_output:
        # JSON output for programmatic use
        output = {
            "carryover_exists": result.carryover_exists,
            "day_a_label": result.day_a_label,
            "day_b_label": result.day_b_label,
            "rollover_local_start": result.rollover_local_start,
            "rollover_local_end": result.rollover_local_end,
            "test_passed": result.test_passed,
            "errors": result.errors,
            "channel_id": channel_id,
            "channel_timezone": channel_timezone,
        }
        typer.echo(json.dumps(output, indent=2))
    else:
        # Human-readable output
        typer.echo("Broadcast Day Alignment Test")
        typer.echo("=" * 40)
        typer.echo(f"Channel: {channel_id}")
        typer.echo(f"Timezone: {channel_timezone}")
        typer.echo()

        typer.echo("Broadcast Day Labels:")
        typer.echo(f"  Day A (05:30 local): {result.day_a_label}")
        typer.echo(f"  Day B (06:30 local): {result.day_b_label}")
        typer.echo()

        typer.echo("Rollover Analysis:")
        typer.echo(f"  Rollover start: {result.rollover_local_start}")
        typer.echo(f"  Rollover end: {result.rollover_local_end}")
        typer.echo(f"  Carryover exists: {'Yes' if result.carryover_exists else 'No'}")
        typer.echo()

        if result.errors:
            typer.echo("Errors:")
            for error in result.errors:
                typer.echo(f"  [ERROR] {error}")
            typer.echo()

        if result.test_passed:
            typer.echo("[PASS] Test PASSED - Broadcast day alignment working correctly")
            typer.echo()
            typer.echo("Key Findings:")
            typer.echo("  • Playback is continuous across 06:00")
            typer.echo("  • ScheduleService will not double-book 06:00 in the new broadcast day")
            typer.echo("  • AsRunLogger is expected to split this for reporting")
        else:
            typer.echo("[FAIL] Test FAILED - Broadcast day alignment issues detected")
            raise typer.Exit(1)
