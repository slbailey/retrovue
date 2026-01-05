# SchedulePlan Update Contract

_Related: [Domain: SchedulePlan](../../domain/SchedulePlan.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> <plan> update` command, which updates an existing SchedulePlan.

## Command Syntax

```bash
retrovue channel plan <channel> <plan> update \
  [--name <string>] \
  [--description <string>] \
  [--cron <cron-expression>] \
  [--start-date <YYYY-MM-DD>] \
  [--end-date <YYYY-MM-DD>] \
  [--priority <integer>] \
  [--active | --inactive] \
  [--json] [--test-db]
```

## Required Arguments

- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - SchedulePlan identifier (UUID or name)

## Optional Options

- `--name <string>` - Update plan name (must be unique within channel)
- `--description <string>` - Update description
- `--cron <cron-expression>` - Update cron expression. Hour/minute ignored; matching uses MasterClock.
- `--start-date <YYYY-MM-DD>` - Update start date
- `--end-date <YYYY-MM-DD>` - Update end date
- `--priority <integer>` - Update priority
- `--active` / `--inactive` - Update active status
- `--json` - Output in JSON format
- `--test-db` - Use test database context

## Behavior Contract Rules (B-#)

### B-1: Channel and Plan Resolution

**Rule:** The command MUST resolve both channel and plan by their identifiers before updating.

**Behavior:**

- If channel is not found → exit 1, error message: "Error: Channel '<identifier>' not found"
- If plan is not found → exit 1, error message: "Error: Plan '<identifier>' not found"
- If plan does not belong to channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"

### B-2: Partial Updates

**Rule:** Only provided fields MUST be updated; others remain unchanged.

**Behavior:**

- Unspecified fields retain their current values
- At least one field must be provided for update

### B-3: Name Uniqueness

**Rule:** If `--name` is provided, the new name MUST be unique within the channel. Uniqueness is evaluated using the same normalization as lookups (case-insensitive, trimmed).

**Behavior:**

- If name conflicts with existing plan in same channel (excluding current plan) → exit 1, error message: "Error: Plan name '<name>' already exists in channel '<channel>'"
- Name comparison is case-insensitive and trimmed (leading/trailing whitespace removed)

### B-4: Date Range Validation

**Rule:** If both `--start-date` and `--end-date` are provided, start_date MUST be <= end_date.

**Behavior:**

- If start_date > end_date → exit 1, error message: "Error: start_date must be <= end_date"
- Date format validation: must be YYYY-MM-DD

### B-5: Cron Expression Validation

**Rule:** If `--cron` is provided, it MUST be valid cron syntax. Hour and minute fields are parsed but ignored.

**Behavior:**

- Invalid cron syntax → exit 1, error message: "Error: Invalid cron expression: <expression>"
- Cron is used only for date/day-of-week matching; time-of-day is defined by Zones
- Hour and minute fields in cron expressions are parsed but ignored

### B-6: Priority Validation

**Rule:** If `--priority` is provided, it MUST be a non-negative integer.

**Behavior:**

- If priority < 0 → exit 1, error message: "Error: Priority must be non-negative"

### B-7: Output Format

**Rule:** The command MUST support both human-readable and JSON output formats.

**Behavior:**

- Without `--json`: Human-readable output with updated plan details
- With `--json`: Valid JSON with `status` and `plan` object

### B-8: JSON Error Shape

**Rule:** With `--json` on failure, return `{ "status":"error", "code":"<ERR_CODE>", "message":"..." }`.

**Behavior:**

- Error codes:
  - `CHANNEL_NOT_FOUND` - Channel identifier not found
  - `PLAN_NOT_FOUND` - Plan identifier not found
  - `PLAN_WRONG_CHANNEL` - Plan exists but belongs to different channel
  - `PLAN_NAME_DUPLICATE` - Plan name already exists in channel
  - `INVALID_DATE_FORMAT` - Date format validation failed
  - `INVALID_DATE_RANGE` - Start date after end date
  - `INVALID_CRON` - Invalid cron expression syntax
  - `INVALID_PRIORITY` - Priority is negative
  - `NO_FIELDS_PROVIDED` - No update fields specified
- Error message provides human-readable description
- Status is always `"error"` for failures, `"ok"` for success

### B-9: Identifier Resolution Order

**Rule:** If `<plan>` looks like a UUID, resolve by id; otherwise resolve by name within the given channel.

**Behavior:**

- UUID format: 8-4-4-4-12 hex digits with hyphens → resolve by `id` field
- Non-UUID format → resolve by `name` field within the channel
- If UUID exists but belongs to a different channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"
- Name resolution is scoped to the specified channel

### B-10: Name Normalization

**Rule:** Name lookups are case-insensitive and trimmed (same normalization used for uniqueness).

**Behavior:**

- Case-insensitive matching: "WeekdayPlan" matches "weekdayplan", "WEEKDAYPLAN", etc.
- Leading/trailing whitespace is trimmed before matching
- If multiple normalized matches exist (shouldn't happen due to constraint) → exit 1 with clear diagnostic: "Error: Multiple plans match normalized name '<name>' in channel '<channel>'"
- Normalization matches the same rules used for uniqueness validation

### B-11: Clock Source & Cron Semantics

**Rule:** All date parsing and cron evaluation use MasterClock (system local time). Hour/minute ignored; matching uses MasterClock.

**Behavior:**

- No timezone flags or per-channel timezone settings
- Date range evaluation uses MasterClock for boundary checks
- Cron matching uses MasterClock for day-of-week/month evaluation
- Cron hour/minute fields are parsed but ignored (only date/day-of-week fields are used)
- Tests must inject fixed MasterClock for deterministic behavior

### B-12: Coverage Invariant Validation (INV_PLAN_MUST_HAVE_FULL_COVERAGE)

**Rule:** On save/update, the plan MUST satisfy INV_PLAN_MUST_HAVE_FULL_COVERAGE. Plans must contain one or more Zones whose combined coverage spans 00:00–24:00 with no gaps.

**Behavior:**

- Validation checks that the plan's zones provide full 24-hour coverage (00:00–24:00) with no gaps
- If validation fails → exit 1, error message: "Error: Plan must have full 24-hour coverage (00:00–24:00) with no gaps. See INV_PLAN_MUST_HAVE_FULL_COVERAGE."
- **Example error output:** `Error Code E-INV-14: Coverage Invariant Violation — Plan no longer covers 00:00–24:00. Suggested Fix: Add a zone covering the missing range or enable default test pattern seeding.`
- Removal of all zones or breaking coverage is prohibited unless in developer debug mode
- In developer debug mode, the invariant check may be bypassed (implementation-specific)
- This validation ensures plans remain usable for runtime schedule generation

## Data Contract Rules (D-#)

### D-1: Partial Field Updates

**Rule:** Only modified fields change; others remain intact.

**Behavior:**

- Unspecified fields retain their database values
- `updated_at` is automatically updated to current timestamp

### D-2: Timestamps

**Rule:** `updated_at` MUST be updated to current timestamp on successful update.

**Behavior:**

- `created_at` remains unchanged
- `updated_at` reflects update time in UTC

### D-3: Unique Constraint

**Rule:** If name is updated, the new name MUST be unique within the channel.

**Behavior:**

- Database constraint prevents duplicate names within same channel
- Application layer validates before attempting update

### D-4: Transaction Boundaries

**Rule:** Plan update MUST be atomic within a single transaction.

**Behavior:**

- All database operations succeed or fail together
- No partial state persists on failure

### D-5: Test Database Isolation

**Rule:** `--test-db` MUST use an isolated test database session.

**Behavior:**

- Test database must not read/write production tables
- Test data should not persist between test sessions

## Output Format

### Human-Readable

```
Plan updated:
  ID: 550e8400-e29b-41d4-a716-446655440000
  Channel: RetroToons (660e8400-e29b-41d4-a716-446655440001)
  Name: WeekdayPlan
  Description: Updated weekday programming plan
  Cron: * * * * MON-FRI (hour/min ignored)
  Start Date: 2025-01-01
  End Date: 2025-12-31
  Priority: 15
  Active: true
  Created: 2025-01-01T12:00:00Z
  Updated: 2025-01-02T10:00:00Z
```

### JSON

```json
{
  "status": "ok",
  "plan": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "channel_id": "660e8400-e29b-41d4-a716-446655440001",
    "name": "WeekdayPlan",
    "description": "Updated weekday programming plan",
    "cron_expression": "* * * * MON-FRI",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "priority": 15,
    "is_active": true,
    "created_at": "2025-01-01T12:00:00Z",
    "updated_at": "2025-01-02T10:00:00Z"
  }
}
```

## Exit Codes

- `0`: Plan updated successfully
- `1`: Validation failed (channel/plan not found, name not unique, invalid dates/cron/priority, etc.)
- `2`: CLI usage error (no fields provided for update)

## Error Conditions

- Channel not found: exit 1, "Error: Channel '<identifier>' not found"
- Plan not found: exit 1, "Error: Plan '<identifier>' not found"
- Plan doesn't belong to channel: exit 1, "Error: Plan '<plan>' does not belong to channel '<channel>'"
- Duplicate name: exit 1, "Error: Plan name '<name>' already exists in channel '<channel>'"
- Invalid date format: exit 1, "Error: Invalid date format. Use YYYY-MM-DD: <error>"
- Start date after end date: exit 1, "Error: start_date must be <= end_date"
- Invalid cron: exit 1, "Error: Invalid cron expression: <expression>"
- Negative priority: exit 1, "Error: Priority must be non-negative"
- No fields provided: exit 2, "Error: At least one field must be provided for update"

## JSON Error Format

When `--json` is used and an error occurs:

```json
{
  "status": "error",
  "code": "PLAN_NOT_FOUND",
  "message": "Error: Plan 'InvalidPlan' not found"
}
```

## Tests

Planned tests:

- `tests/contracts/test_plan_update_contract.py::test_plan_update_help_flag_exits_zero`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_channel_not_found_exits_one`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_plan_not_found_exits_one`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_success_human`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_success_json`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_partial_update`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_duplicate_name_exits_one`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_invalid_dates_exits_one`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_json_error_channel_not_found`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_json_error_plan_not_found`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_json_error_plan_wrong_channel`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_json_error_duplicate_name`
- `tests/contracts/test_plan_update_contract.py::test_plan_update_json_error_invalid_date_range`
- `tests/contracts/test_plan_update_data_contract.py::test_plan_update_partial_fields`
- `tests/contracts/test_plan_update_data_contract.py::test_plan_update_updates_timestamp`

## See Also

- [Domain: SchedulePlan](../../domain/SchedulePlan.md) - SchedulePlan domain documentation
- [SchedulePlan Add](SchedulePlanAddContract.md)
