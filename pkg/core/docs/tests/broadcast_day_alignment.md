# Broadcast Day Alignment Testing

_Related: [Domain: MasterClock](../domain/MasterClock.md) • [Runtime: Channel manager](../runtime/ChannelManager.md) • [Contributing: Runtime](../contributing/CONTRIBUTING_RUNTIME.md)_

This document describes the `retrovue test broadcast-day-alignment` command, which validates ScheduleService's broadcast-day logic and rollover handling.

## Overview

The broadcast day alignment test validates that RetroVue correctly handles the broadcast day model (06:00 → 06:00 local channel time) and properly manages programs that span the 06:00 rollover boundary.

## Test Scenario

The test uses an HBO-style scenario where a movie airs from 05:00–07:00 local time:

- **05:00–06:00**: Movie airs on Day A (2025-10-24 broadcast day)
- **06:00–07:00**: Movie continues on Day B (2025-10-25 broadcast day)
- **06:00**: Broadcast day rollover boundary

This scenario tests:

1. Correct broadcast day classification
2. Seamless playback across rollover
3. Proper carryover detection
4. Schedule conflict prevention

## Command Usage

```bash
# Basic test with default settings
retrovue test broadcast-day-alignment

# Test with specific channel and timezone
retrovue test broadcast-day-alignment --channel "hbo_east" --timezone "America/New_York"

# JSON output for programmatic use
retrovue test broadcast-day-alignment --json
```

## Test Parameters

- `--channel, -c`: Test channel ID (default: "test_channel_1")
- `--timezone, -t`: Channel timezone (default: "America/New_York")
- `--json`: Output results in JSON format

## Test Output

### Human-Readable Output

```
Broadcast Day Alignment Test
========================================
Channel: test_channel_1
Timezone: America/New_York

Broadcast Day Labels:
  Day A (05:30 local): 2025-10-24
  Day B (06:30 local): 2025-10-25

Rollover Analysis:
  Rollover start: 2025-10-24T06:00:00
  Rollover end: 2025-10-24T07:00:00
  Carryover exists: Yes

✅ Test PASSED - Broadcast day alignment working correctly

Key Findings:
  • Playback is continuous across 06:00
  • ScheduleService will not double-book 06:00 in the new broadcast day
  • AsRunLogger is expected to split this for reporting
```

### JSON Output

```json
{
  "carryover_exists": true,
  "day_a_label": "2025-10-24",
  "day_b_label": "2025-10-25",
  "rollover_local_start": "2025-10-24T06:00:00",
  "rollover_local_end": "2025-10-24T07:00:00",
  "test_passed": true,
  "errors": [],
  "channel_id": "test_channel_1",
  "channel_timezone": "America/New_York"
}
```

## Test Validation

The test validates the following:

### Broadcast Day Classification

- `broadcast_day_for()` at 05:30 local → returns Day A (2025-10-24)
- `broadcast_day_for()` at 06:30 local → returns Day B (2025-10-25)
- Correct handling of the 06:00 boundary

### Broadcast Day Windows

- `broadcast_day_window()` returns proper 06:00→06:00 windows
- Day A: 2025-10-24 06:00:00 → 2025-10-25 05:59:59.999999
- Day B: 2025-10-25 06:00:00 → 2025-10-26 05:59:59.999999

### Rollover Handling

- `active_segment_spanning_rollover()` detects carryover at 06:00
- Confirms that 06:00–07:00 in Day B is marked as continuation
- Prevents double-scheduling at rollover boundary

## Expected Behavior

### Continuous Playback

The test confirms that:

- Playback is continuous across the 06:00 boundary
- No interruption or restart occurs at rollover
- The same program continues seamlessly

### Schedule Management

The test validates that:

- ScheduleService correctly identifies carryover content
- Day B's schedule accounts for occupied time slots
- No scheduling conflicts occur at rollover

### Reporting Accuracy

The test ensures that:

- AsRunLogger can split continuous assets across broadcast days
- Each broadcast day gets accurate reporting
- No data loss occurs at rollover boundaries

## JSON Output Fields

The test provides structured JSON output with the following key fields:

### Core Fields

- `test_passed`: Boolean indicating if the test passed
- `carryover_exists`: Whether content spans the rollover boundary
- `day_a_label`: Broadcast day label for Day A (e.g., "2025-10-24")
- `day_b_label`: Broadcast day label for Day B (e.g., "2025-10-25")
- `rollover_local_start`: Local time when rollover begins
- `rollover_local_end`: Local time when rollover ends
- `errors`: Array of error messages if the test failed

### Channel Information

- `channel_id`: Channel being tested
- `channel_timezone`: Timezone of the test channel
- `duration_seconds`: Time taken to run the test
- `timestamp`: When the test was run

### Validation Results

- `broadcast_day_classification_ok`: Whether day labels are correct
- `rollover_detection_ok`: Whether carryover is properly detected
- `schedule_conflict_ok`: Whether no double-scheduling occurs
- `playback_continuity_ok`: Whether playback is seamless

## Example JSON Output

```json
{
  "test_passed": true,
  "carryover_exists": true,
  "day_a_label": "2025-10-24",
  "day_b_label": "2025-10-25",
  "rollover_local_start": "2025-10-24T06:00:00",
  "rollover_local_end": "2025-10-24T07:00:00",
  "channel_id": "test_channel_1",
  "channel_timezone": "America/New_York",
  "duration_seconds": 1.23,
  "timestamp": "2025-10-24T17:30:45.123456+00:00",
  "broadcast_day_classification_ok": true,
  "rollover_detection_ok": true,
  "schedule_conflict_ok": true,
  "playback_continuity_ok": true,
  "errors": []
}
```

## Failure Scenarios

### Common Failures

**Incorrect broadcast day classification:**

```json
{
  "test_passed": false,
  "day_a_label": "2025-10-25",
  "day_b_label": "2025-10-26",
  "errors": ["Day A label incorrect: expected '2025-10-24', got '2025-10-25'"]
}
```

**Rollover detection failure:**

```json
{
  "test_passed": false,
  "carryover_exists": false,
  "errors": ["Carryover detection failed: expected carryover, got None"]
}
```

**Schedule conflict:**

```json
{
  "test_passed": false,
  "schedule_conflict_ok": false,
  "errors": ["Schedule conflict detected at rollover boundary"]
}
```

**Playback discontinuity:**

```json
{
  "test_passed": false,
  "playback_continuity_ok": false,
  "errors": ["Playback interrupted at rollover boundary"]
}
```

## CI Integration

This test is designed for CI integration to guarantee that RetroVue never regresses and starts "cutting" programs at 06:00 or double-scheduling 06:00. The test should be run as part of the continuous integration pipeline to ensure broadcast day logic remains correct.

## Implementation Notes

The test uses stub implementations of ScheduleService methods for validation. In a real implementation, these methods would:

- Use MasterClock for timezone conversion
- Query actual schedule data
- Return real carryover information

The test framework provides a foundation for validating broadcast day logic before full implementation.

## Best Practices

### Regular Testing

```bash
# Daily broadcast day check
retrovue test broadcast-day-alignment

# Weekly comprehensive test
retrovue test broadcast-day-alignment --channel "hbo_east" --timezone "America/New_York"
```

### Performance Monitoring

```bash
# Baseline test
retrovue test broadcast-day-alignment --json > baseline.json

# Compare with current behavior
retrovue test broadcast-day-alignment --json > current.json
```

### Integration Verification

```bash
# Test with different timezones
retrovue test broadcast-day-alignment --timezone "Europe/London"
retrovue test broadcast-day-alignment --timezone "Asia/Tokyo"
```

## See also

- [Domain: MasterClock](../domain/MasterClock.md) - Authoritative time source
- [Runtime: Schedule service](../runtime/schedule_service.md) - Broadcast day logic
- [Runtime: Channel manager](../runtime/ChannelManager.md) - Playback execution
- [Contributing: Runtime](../contributing/CONTRIBUTING_RUNTIME.md) - Runtime development process
- [Domain: MasterClock](../domain/MasterClock.md) - MasterClock specification

_Document version: v0.1 · Last updated: 2025-10-24_
