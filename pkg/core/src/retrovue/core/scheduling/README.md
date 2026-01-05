# Scheduling Domain Contracts

This module provides validation contracts for the scheduling domain, enforcing structural integrity, policy compliance, and playout safety.

## Overview

The scheduling contracts validate:
- **SchedulePlanInvariantsContract**: Ensures SchedulePlan is logically consistent
- **ProgramContract**: Validates programs are coherent and policy-compliant
- **ScheduleDayContract**: Ensures generated schedule days match intended plans
- **PlaylogEventContract**: Guarantees playout events are valid and correctly timed

## Usage

### Validating a SchedulePlan

```python
from retrovue.core.scheduling import validate_schedule_plan, SchedulePlanValidationError

try:
    validate_schedule_plan(plan)
    # Plan is valid, proceed with save/compilation
except SchedulePlanValidationError as e:
    # Handle validation errors
    print(f"Plan validation failed: {e}")
    for violation in e.violations:
        print(f"  - {violation}")
```

### Validating a Block Assignment

```python
from retrovue.core.scheduling import validate_block_assignment, BlockAssignmentValidationError

try:
    validate_block_assignment(assignment, plan=plan, channel=channel)
    # Assignment is valid
except BlockAssignmentValidationError as e:
    # Handle validation errors
    print(f"Assignment validation failed: {e}")
```

**Note:** The `channel` parameter is optional. If provided, the validation will enforce grid boundary alignment:
- Duration must be a multiple of the channel's `grid_block_minutes`
- Start time must align with the channel's grid boundaries (based on `block_start_offsets_minutes`)

**Automatic Channel Detection:** Since SchedulePlans are required to be tied to a channel, if a `plan` is provided with a loaded `channel` relationship, the validation will automatically use that channel for grid boundary validation. You don't need to pass the channel separately in this case.

### Validating a Schedule Day

```python
from retrovue.core.scheduling import validate_schedule_day, ScheduleDayValidationError

try:
    validate_schedule_day(schedule_day, channel=channel)
    # Schedule day is valid
except ScheduleDayValidationError as e:
    # Handle validation errors
    print(f"Schedule day validation failed: {e}")
```

### Validating a Playlog Event

```python
from retrovue.core.scheduling import validate_playlog_event, PlaylogEventValidationError

try:
    validate_playlog_event(event, channel=channel)
    # Event is valid
except PlaylogEventValidationError as e:
    # Handle validation errors
    print(f"Playlog event validation failed: {e}")
```

## Integration with ScheduleService

When implementing or updating `ScheduleService`, integrate validation as follows:

```python
from retrovue.core.scheduling import (
    validate_schedule_plan,
    validate_block_assignment,
    validate_schedule_day,
    validate_playlog_event,
)

class ScheduleService:
    def create_or_update_plan(self, plan_data):
        """Create or update a schedule plan with validation."""
        # ... create/load plan ...
        
        # Validate before saving
        validate_schedule_plan(plan)
        
        # Validate all block assignments
        # If plan has a channel relationship loaded, grid validation happens automatically
        for assignment in plan.programs:
            validate_block_assignment(assignment, plan=plan, channel=channel)
        
        # ... save plan ...
    
    def generate_schedule_day(self, channel_id, date):
        """Generate a schedule day with validation."""
        # ... generate schedule day from plan ...
        
        # Validate schedule day
        validate_schedule_day(schedule_day, channel=channel)
        
        # Validate all playlog events
        for event in schedule_day.playlog_events:
            validate_playlog_event(event, channel=channel)
        
        # ... save schedule day ...
```

## Validation Rules

### SchedulePlanInvariantsContract

- Plan start_offset must equal 0 (plans begin at 00:00)
- All block assignments must have non-overlapping time windows
- The union of all block durations must not exceed 24 hours
- Blocks must be ordered by ascending start_time
- Labels (if present) must exist in SchedulePlanLabel for that plan
- ContentPolicyRule validation (when implemented)

### ProgramContract

- `start_time` and `duration` are required and positive
- **Grid boundary alignment** (if channel provided):
  - Duration must be a multiple of channel's `grid_block_minutes`
  - Start time must align with channel's grid boundaries (based on `block_start_offsets_minutes`)
- If `content_ref` points to a VirtualAsset, ensure it exists and can expand
- If `content_ref` points to a Series or Playlist, ensure it contains playable items
- Validate ContentPolicyRule compatibility

### ScheduleDayContract

- No duplicate or overlapping PlaylogEvents
- Each PlaylogEvent should trace back to a Program
- All timestamps must align to channel's `broadcast_day_start` logic
- If VirtualAsset expands into multiple events, verify total runtime matches

### PlaylogEventContract

- `start_utc` < `end_utc`
- `duration` = `end_utc - start_utc`
- `asset_uuid` must resolve to a valid media file or URL
- No overlapping events within a single channel's day log (unless `allow_overlap=True`)
- `broadcast_day` must be in YYYY-MM-DD format

## Exceptions

All validation functions raise typed exceptions:

- `ScheduleValidationError`: Base exception for all scheduling validation errors
- `SchedulePlanValidationError`: Raised when SchedulePlan validation fails
- `BlockAssignmentValidationError`: Raised when block assignment validation fails
- `ScheduleDayValidationError`: Raised when schedule day validation fails
- `PlaylogEventValidationError`: Raised when playlog event validation fails

All exceptions include:
- A human-readable error message
- A list of specific violations
- Context information (IDs, names, etc.)

## Testing

Comprehensive unit tests are available in `tests/core/scheduling/test_schedule_contracts.py`.

Run tests with:
```bash
pytest tests/core/scheduling/test_schedule_contracts.py -v
```

## Future Enhancements

- ContentPolicyRule validation (when implemented)
- VirtualAsset expansion validation
- Series/Playlist content validation
- More sophisticated overlap detection with `allow_overlap` flag

