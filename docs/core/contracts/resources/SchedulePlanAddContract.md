# SchedulePlan Add Contract

_Related: [Domain: SchedulePlan](../../domain/SchedulePlan.md) • [Domain: Channel](../../domain/Channel.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> add` command, which creates a new SchedulePlan for a channel. SchedulePlans are the top-level unit of channel programming, defining Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets). On creation, a newly created plan auto-creates a single 24:00 test filler zone (SyntheticAsset) to ensure the plan is valid. The web UI will call the same underlying Plan Add function used by the CLI; the interactive plan build command exists only for developer and QA workflows, not production usage.

## Command Syntax

```bash
retrovue channel plan <channel> add \
  --name <string> \
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

## Required Options

- `--name <string>` - Plan name (must be unique within the channel)

## Optional Options

- `--description <string>` - Human-readable description of the plan's programming intent
- `--cron <cron-expression>` - Cron-style expression for recurring patterns. **Note:** Only date/day-of-week fields are used (e.g., `* * * * MON-FRI`). Hour and minute fields are parsed but ignored. Cron matching is evaluated against MasterClock (system local time). See [SchedulePlan Update Contract](SchedulePlanUpdateContract.md) for cron update behavior.
- `--start-date <YYYY-MM-DD>` - Start date for plan validity (inclusive, can be year-agnostic)
- `--end-date <YYYY-MM-DD>` - End date for plan validity (inclusive, can be year-agnostic)
- `--priority <integer>` - Priority for layering (default: 0). Higher numbers = higher priority.
- `--active` / `--inactive` - Plan operational status (default: `--active`)
- `--empty` - Create plan without default test filler zone (developer override; plan will not satisfy INV_PLAN_MUST_HAVE_FULL_COVERAGE)
- `--allow-empty` - Create an invalid plan (no zones) for debugging or schema testing only. This flag disables automatic test filler zone seeding and should only be available in dev mode.
- `--json` - Output in JSON format
- `--test-db` - Use test database context

## Behavior Contract Rules (B-#)

### B-1: Channel Resolution

**Rule:** The command MUST resolve the channel by its identifier before creating the plan.

**Behavior:**

- If channel is not found → exit 1, error message: "Error: Channel '<identifier>' not found"
- Channel must exist and be valid

### B-2: Name Uniqueness

**Rule:** Plan name MUST be unique within the channel. Uniqueness is evaluated using the same normalization as lookups (case-insensitive, trimmed).

**Behavior:**

- If name conflicts with existing plan in same channel → exit 1, error message: "Error: Plan name '<name>' already exists in channel '<channel>'"
- Plans in different channels can have the same name
- Name validation occurs at creation time
- Name comparison is case-insensitive and trimmed (leading/trailing whitespace removed)

### B-3: Date Range Validation

**Rule:** If both `--start-date` and `--end-date` are provided, start_date MUST be <= end_date.

**Behavior:**

- If start_date > end_date → exit 1, error message: "Error: start_date must be <= end_date"
- Date format validation: must be YYYY-MM-DD → exit 1, error message: "Error: Invalid date format. Use YYYY-MM-DD: <error>"

### B-4: Cron Expression Validation

**Rule:** If `--cron` is provided, it MUST be valid cron syntax. Hour and minute fields are parsed but ignored.

**Behavior:**

- Invalid cron syntax → exit 1, error message: "Error: Invalid cron expression: <expression>"
- Cron is used only for date/day-of-week matching; time-of-day is defined by Zones
- Cron matching is evaluated against MasterClock (system local time)

### B-5: Priority Validation

**Rule:** Priority MUST be a non-negative integer.

**Behavior:**

- If priority < 0 → exit 1, error message: "Error: Priority must be non-negative"
- Default priority is 0 if not specified

### B-6: Output Format

**Rule:** The command MUST support both human-readable and JSON output formats.

**Behavior:**

- Without `--json`: Human-readable output with plan details
- With `--json`: Valid JSON with `status` and `plan` fields
- JSON output MUST include: `id`, `channel_id`, `name`, `description`, `cron_expression`, `start_date`, `end_date`, `priority`, `is_active`, `created_at`, `updated_at`

### B-7: Active Status

**Rule:** Plan MUST be created with `is_active=true` unless `--inactive` is specified.

**Behavior:**

- Default: `is_active=true`
- With `--inactive`: `is_active=false`
- Active plans are eligible for schedule generation

### B-8: Clock Source

**Rule:** All date parsing and cron evaluation use MasterClock (system local time).

**Behavior:**

- No timezone flags or per-channel timezone settings
- Date range evaluation uses MasterClock for boundary checks
- Cron matching uses MasterClock for day-of-week/month evaluation
- Cron hour/minute fields are parsed but ignored (only date/day-of-week fields are used)
- Tests must inject fixed MasterClock for deterministic behavior

### B-9: Initialization Rules (Default Test Filler Zone)

**Rule:** When no zones are supplied, the system MUST auto-seed a full 24-hour test filler zone (00:00–24:00) to satisfy INV_PLAN_MUST_HAVE_FULL_COVERAGE.

**Behavior:**

- By default, a new plan is created with a default test filler zone covering 00:00–24:00
- This ensures the plan immediately satisfies the full coverage invariant (plans must contain one or more Zones whose combined coverage spans 00:00–24:00 with no gaps)
- The default zone can be replaced or modified after plan creation
- With `--empty` flag: Skip auto-seeding (plan will not satisfy coverage invariant; developer override only)
- The `--empty` flag is intended for development/testing scenarios where incomplete plans are temporarily needed
- With `--allow-empty` flag: Disables automatic test filler zone seeding and creates an invalid plan with no zones. This flag should only be available in dev mode and is intended for debugging or schema testing only. The resulting plan will violate INV_PLAN_MUST_HAVE_FULL_COVERAGE.

### B-10: JSON Error Shape

**Rule:** With `--json` on failure, return machine-usable error shape.

**Behavior:**

- Error responses MUST use: `{"status":"error","code":"<ERR_CODE>","message":"..."}`
- Error codes MUST include:
  - `CHANNEL_NOT_FOUND` - Channel identifier not found
  - `PLAN_NAME_DUPLICATE` - Plan name already exists in channel
  - `INVALID_DATE_FORMAT` - Date format is not YYYY-MM-DD
  - `INVALID_DATE_RANGE` - start_date > end_date
  - `INVALID_CRON` - Cron expression syntax is invalid
  - `INVALID_PRIORITY` - Priority is negative
- Error messages MUST be human-readable and actionable

## Data Contract Rules (D-#)

### D-1: Record Persistence

**Rule:** A new SchedulePlan record MUST be persisted in `schedule_plans` table with all provided fields.

**Fields:**

- `id` (UUID, primary key, auto-generated)
- `channel_id` (UUID, FK to channels.id, required)
- `name` (Text, required, max length: 255 characters)
- `description` (Text, optional, nullable)
- `cron_expression` (Text, optional, nullable)
- `start_date` (Date, optional, nullable)
- `end_date` (Date, optional, nullable)
- `priority` (Integer, required, default: 0)
- `is_active` (Boolean, required, default: true)
- `created_at` (DateTime(timezone=True), auto-generated)
- `updated_at` (DateTime(timezone=True), auto-generated)

### D-2: Unique Constraint

**Rule:** The combination of `channel_id` + `name` MUST be unique (enforced at database level).

**Behavior:**

- Database constraint prevents duplicate names within same channel
- Application layer validates before attempting insert

### D-3: Foreign Key Constraint

**Rule:** `channel_id` MUST reference a valid Channel record.

**Behavior:**

- Foreign key constraint enforced at database level
- Cascade delete: if channel is deleted, plans are deleted (CASCADE)

### D-4: Timestamps

**Rule:** `created_at` and `updated_at` MUST be stored in UTC with timezone information.

**Behavior:**

- Timestamps are auto-generated by database
- `updated_at` is set to `created_at` on initial creation

### D-5: Transaction Boundaries

**Rule:** Plan creation MUST be atomic within a single transaction.

**Behavior:**

- All database operations succeed or fail together
- No partial state persists on failure

### D-6: Test Database Isolation

**Rule:** `--test-db` MUST use an isolated test database session.

**Behavior:**

- Test database must not read/write production tables
- Test data should not persist between test sessions

## Output Format

### Human-Readable

```
Plan created:
  ID: 550e8400-e29b-41d4-a716-446655440000
  Channel: RetroToons (660e8400-e29b-41d4-a716-446655440001)
  Name: WeekdayPlan
  Description: Weekday programming plan
  Cron: * * * * MON-FRI
  Start Date: 2025-01-01
  End Date: 2025-12-31
  Priority: 10
  Active: true
  Created: 2025-01-01T12:00:00Z
```

### JSON

```json
{
  "status": "ok",
  "plan": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "channel_id": "660e8400-e29b-41d4-a716-446655440001",
    "name": "WeekdayPlan",
    "description": "Weekday programming plan",
    "cron_expression": "* * * * MON-FRI",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "priority": 10,
    "is_active": true,
    "created_at": "2025-01-01T12:00:00Z",
    "updated_at": "2025-01-01T12:00:00Z"
  }
}
```

## Exit Codes

- `0`: Plan created successfully
- `1`: Validation failed (channel not found, name not unique, invalid dates/cron, etc.)
- `2`: CLI usage error (missing required arguments)

## Error Conditions

- Channel not found: exit 1, "Error: Channel '<identifier>' not found"
- Duplicate name: exit 1, "Error: Plan name '<name>' already exists in channel '<channel>'"
- Invalid date format: exit 1, "Error: Invalid date format. Use YYYY-MM-DD: <error>"
- Start date after end date: exit 1, "Error: start_date must be <= end_date"
- Invalid cron: exit 1, "Error: Invalid cron expression: <expression>"
- Negative priority: exit 1, "Error: Priority must be non-negative"

## JSON Error Format

When `--json` is used and an error occurs, the output MUST follow this structure:

```json
{
  "status": "error",
  "code": "CHANNEL_NOT_FOUND",
  "message": "Channel 'invalid-id' not found"
}
```

Example error codes:

- `CHANNEL_NOT_FOUND` - Channel identifier not found
- `PLAN_NAME_DUPLICATE` - Plan name already exists in channel
- `INVALID_DATE_FORMAT` - Date format is not YYYY-MM-DD
- `INVALID_DATE_RANGE` - start_date > end_date
- `INVALID_CRON` - Cron expression syntax is invalid
- `INVALID_PRIORITY` - Priority is negative

## Tests

Planned tests:

- `tests/contracts/test_plan_add_contract.py::test_plan_add_help_flag_exits_zero`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_missing_name_exits_one`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_channel_not_found_exits_one`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_duplicate_name_exits_one`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_success_human`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_success_json`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_invalid_date_format_exits_one`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_start_after_end_exits_one`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_invalid_cron_exits_one`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_negative_priority_exits_one`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_uses_master_clock_for_cron_matching`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_ignores_cron_hours_and_minutes`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_date_range_parsing_with_master_clock`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_json_error_channel_not_found`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_json_error_plan_name_duplicate`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_json_error_invalid_date_format`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_json_error_invalid_date_range`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_json_error_invalid_cron`
- `tests/contracts/test_plan_add_contract.py::test_plan_add_json_error_invalid_priority`
- `tests/contracts/test_plan_add_data_contract.py::test_plan_add_persists_record`
- `tests/contracts/test_plan_add_data_contract.py::test_plan_add_enforces_unique_constraint`
- `tests/contracts/test_plan_add_data_contract.py::test_plan_add_enforces_foreign_key`
- `tests/contracts/test_plan_add_data_contract.py::test_plan_add_sets_defaults`

## See Also

- [Domain: SchedulePlan](../../domain/SchedulePlan.md) - SchedulePlan domain documentation
- [Channel Contract](ChannelContract.md)
