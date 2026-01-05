# SchedulePlan Show Contract

_Related: [Domain: SchedulePlan](../../domain/SchedulePlan.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> <plan> show` command, which displays a single SchedulePlan record.

**Context:** This command is part of the Plan Mode workflow, allowing operators to inspect SchedulePlan details before entering plan mode for interactive editing.

**Coverage Guarantee:** Every displayed plan is guaranteed to have a coverage baseline satisfying INV_PLAN_MUST_HAVE_FULL_COVERAGE. Plans must contain one or more Zones whose combined coverage spans 00:00–24:00 with no gaps. When no scheduled content exists, the test filler zone (SyntheticAsset) appears in the zones list (00:00–24:00).

**Broadcast-Day Display:** Human-readable times in plan show must reflect channel broadcast-day start (e.g., 06:00 → 05:59 next day). JSON outputs can keep canonical times, but include `broadcast_day_start` so UIs can offset. Human output hides implementation details (asset_type, producer_type); JSON output may include technical fields.

## Command Syntax

```bash
retrovue channel plan <channel> <plan> show \
  [--json] \
  [--with-contents] \
  [--computed] \
  [--no-color] \
  [--quiet] \
  [--test-db]
```

## Required Arguments

- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - SchedulePlan identifier (UUID or name)

## Optional Options

- `--json` - Output in JSON format
- `--with-contents` - Include lightweight summaries of Zones and their SchedulableAssets
- `--computed` - Include computed fields (effective_today, next_applicable_date)
- `--no-color` - Disable colored output (if CLI supports it)
- `--quiet` - Suppress extraneous output lines
- `--test-db` - Use test database context

## Behavior Contract Rules (B-#)

### B-1: Channel and Plan Resolution

**Rule:** The command MUST resolve both channel and plan by their identifiers before displaying.

**Behavior:**

- If channel is not found → exit 1, error message: "Error: Channel '<identifier>' not found"
- If plan is not found → exit 1, error message: "Error: Plan '<identifier>' not found"
- If plan does not belong to channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"

### B-2: Output Format

**Rule:** The command MUST support both human-readable and JSON output formats.

**Behavior:**

- Without `--json`: Human-readable output with plan details
- With `--json`: Valid JSON with `status` and `plan` object
- JSON output MUST include all plan fields

### B-3: Read-Only Operation

**Rule:** Show operation MUST be read-only with no mutations.

**Behavior:**

- No database modifications
- No side effects
- Idempotent operation

### B-4: Identifier Resolution Order

**Rule:** If `<plan>` looks like a UUID, resolve by id; otherwise resolve by name within the given channel.

**Behavior:**

- UUID format: 8-4-4-4-12 hex digits with hyphens → resolve by `id` field
- Non-UUID format → resolve by `name` field within the channel
- If UUID exists but belongs to a different channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"
- Name resolution is scoped to the specified channel

### B-5: Name Normalization

**Rule:** Name lookups are case-insensitive and trimmed (same normalization used for uniqueness).

**Behavior:**

- Case-insensitive matching: "WeekdayPlan" matches "weekdayplan", "WEEKDAYPLAN", etc.
- Leading/trailing whitespace is trimmed before matching
- If multiple normalized matches exist (shouldn't happen due to constraint) → exit 1 with clear diagnostic: "Error: Multiple plans match normalized name '<name>' in channel '<channel>'"
- Normalization matches the same rules used for uniqueness validation

### B-6: Expandable Relations (Opt-In)

**Rule:** Support `--with-contents` to include lightweight summaries of Zones and SchedulableAssets.

**Behavior (Human-Readable):**

- Display broadcast-day aligned grid/table view:
  - **Zones (count: N)** with rows: `Ord | Start | End | Zone Name | Title`
  - Times reflect broadcast-day start (e.g., 06:00 → 05:59 next day)
  - Human view shows only title (e.g., "Test Filler"), not asset_type or producer_type
- Zone rows show: order, start time (broadcast-day offset), end time (broadcast-day offset), zone name, title
- Every plan is guaranteed to have at least one zone covering 00:00–24:00 (see INV_PLAN_MUST_HAVE_FULL_COVERAGE)
- If no explicit zones exist, the default test filler zone (SyntheticAsset, 00:00–24:00) will appear
- **UI Note:** UI renderers can safely assume at least one zone exists for empty coverage fallback visualization

**Behavior (JSON):**

- Add `"broadcast_day_start": "HH:MM"` field for UI offset calculation
- Add `"zones": [...]` array with objects containing:
  - `order`, `start` (canonical time 00:00–24:00), `end` (canonical time 00:00–24:00)
  - `zone_name`, `title`
  - `asset_type`, `producer_type` (technical fields, included in JSON)
- Arrays are empty if `--with-contents` is not provided

### B-7: Deterministic Formatting

**Rule:** Dates printed as YYYY-MM-DD; timestamps printed ISO-8601 UTC with Z.

**Behavior:**

- Date fields (`start_date`, `end_date`): Always formatted as `YYYY-MM-DD`
- Timestamp fields (`created_at`, `updated_at`): Always formatted as ISO-8601 UTC with `Z` suffix (e.g., `2025-01-01T12:00:00Z`)
- Null dates shown as `null` in JSON, `-` or omitted in human-readable
- Formatting is deterministic and consistent across all output modes

### B-8: JSON Error Shape

**Rule:** With `--json` on failure, return `{ "status":"error", "code":"<ERR_CODE>", "message":"..." }`.

**Behavior:**

- Error codes:
  - `CHANNEL_NOT_FOUND` - Channel identifier not found
  - `PLAN_NOT_FOUND` - Plan identifier not found
  - `PLAN_WRONG_CHANNEL` - Plan exists but belongs to different channel
- Error message provides human-readable description
- Status is always `"error"` for failures, `"ok"` for success

### B-9: Readability Flags

**Rule:** Honor global `--no-color` / `--quiet` if CLI supports them; show must not emit extra lines in `--quiet`.

**Behavior:**

- `--no-color`: Disable ANSI color codes in output (if CLI supports colored output)
- `--quiet`: Suppress extraneous output lines (headers, separators, etc.)
- In `--quiet` mode, output only essential plan data
- Flags are optional; CLI may not support all flags

## Data Contract Rules (D-#)

### D-1: Reflects Persisted State

**Rule:** Output MUST reflect the persisted SchedulePlan row exactly.

**Behavior:**

- All fields match database state
- Timestamps reported in UTC
- Null fields shown as `null` in JSON, `-` or omitted in human-readable

### D-2: Test Database Isolation

**Rule:** `--test-db` MUST use an isolated test database session.

**Behavior:**

- Test database must not read/write production tables
- Test data should not persist between test sessions

## Output Format

### Human-Readable

```
Plan:
  ID: 550e8400-e29b-41d4-a716-446655440000
  Channel: RetroToons (660e8400-e29b-41d4-a716-446655440001)
  Name: WeekdayPlan
  Description: Weekday programming plan
  Cron: * * * * MON-FRI (hour/min ignored)
  Start Date: 2025-01-01
  End Date: 2025-12-31
  Priority: 10
  Active: true
  Created: 2025-01-01T12:00:00Z
  Updated: 2025-01-01T12:00:00Z
```

### Human-Readable (with --with-contents)

```
Plan:
  ID: 550e8400-e29b-41d4-a716-446655440000
  Channel: RetroToons (660e8400-e29b-41d4-a716-446655440001)
  Name: WeekdayPlan
  Description: Weekday programming plan
  Cron: * * * * MON-FRI (hour/min ignored)
  Start Date: 2025-01-01
  End Date: 2025-12-31
  Priority: 10
  Active: true
  Created: 2025-01-01T12:00:00Z
  Updated: 2025-01-01T12:00:00Z

Zones (count: 2):
  Base | 00:00–24:00 | All days
  Prime Time | 19:00–22:00 | All days

SchedulableAssets in Zones:
  Base | Cheers, The Big Bang Theory, ...
  Prime Time | Drama Series, Movie Block
```

### Human-Readable (with --computed)

```
Plan:
  ID: 550e8400-e29b-41d4-a716-446655440000
  Channel: RetroToons (660e8400-e29b-41d4-a716-446655440001)
  Name: WeekdayPlan
  Description: Weekday programming plan
  Cron: * * * * MON-FRI (hour/min ignored)
  Start Date: 2025-01-01
  End Date: 2025-12-31
  Priority: 10
  Active: true
  Created: 2025-01-01T12:00:00Z
  Updated: 2025-01-01T12:00:00Z

Computed:
  Effective Today: true
  Next Applicable Date: 2025-01-06
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

### JSON (with --with-contents)

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
  },
  "zones": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440002",
      "name": "Base",
      "start_time": "00:00:00",
      "end_time": "24:00:00",
      "day_filters": null
    },
    {
      "id": "880e8400-e29b-41d4-a716-446655440003",
      "name": "Prime Time",
      "start_time": "19:00:00",
      "end_time": "22:00:00",
      "day_filters": null
    }
  ],
  "schedulable_assets_by_zone": [
    {
      "zone_name": "Base",
      "schedulable_asset_count": 2
    },
    {
      "zone_name": "Prime Time",
      "schedulable_asset_count": 2
    }
  ]
}
```

### JSON (with --computed)

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
    "updated_at": "2025-01-01T12:00:00Z",
    "effective_today": true,
    "next_applicable_date": "2025-01-06"
  }
}
```

### JSON Error Format

```json
{
  "status": "error",
  "code": "PLAN_NOT_FOUND",
  "message": "Error: Plan 'InvalidPlan' not found"
}
```

## Exit Codes

- `0`: Plan found and displayed
- `1`: Channel not found, plan not found, plan doesn't belong to channel, DB failure, or `--test-db` session unavailable

## Error Conditions

- Channel not found: exit 1, "Error: Channel '<identifier>' not found"
- Plan not found: exit 1, "Error: Plan '<identifier>' not found"
- Plan doesn't belong to channel: exit 1, "Error: Plan '<plan>' does not belong to channel '<channel>'"

## Tests

Planned tests:

- `tests/contracts/test_plan_show_contract.py::test_plan_show_help_flag_exits_zero`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_channel_not_found_exits_one`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_plan_not_found_exits_one`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_plan_wrong_channel_exits_one`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_uuid_wrong_channel_exits_one`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_name_lookup_is_case_insensitive_and_trimmed`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_success_human`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_success_json`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_with_contents_human`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_with_contents_json`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_with_computed`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_formats_dates_and_timestamps`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_json_error_channel_not_found`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_json_error_plan_not_found`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_json_error_plan_wrong_channel`
- `tests/contracts/test_plan_show_contract.py::test_plan_show_quiet_has_no_extraneous_output`
- `tests/contracts/test_plan_show_data_contract.py::test_plan_show_reflects_persisted_state`

## See Also

- [Domain: SchedulePlan](../../domain/SchedulePlan.md) - SchedulePlan domain documentation
- [SchedulePlan List](SchedulePlanListContract.md)
