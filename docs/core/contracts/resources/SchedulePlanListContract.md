# SchedulePlan List Contract

_Related: [Domain: SchedulePlan](../../domain/SchedulePlan.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> list` command, which lists all SchedulePlan records for a given channel.

**Coverage Guarantee:** Plans returned by list APIs are guaranteed valid (coverage invariant enforced). All plans satisfy INV_PLAN_MUST_HAVE_FULL_COVERAGE, ensuring full 24-hour coverage (00:00–24:00) with no gaps. Plans must contain one or more Zones whose combined coverage spans 00:00–24:00 with no gaps.

## Command Syntax

```bash
retrovue channel plan <channel> list \
  [--json] \
  [--active-only] \
  [--inactive-only] \
  [--limit <integer>] \
  [--offset <integer>] \
  [--test-db]
```

**Note:** `--active-only`, `--inactive-only`, `--limit`, and `--offset` are reserved for future implementation. In the baseline contract, these flags are ignored with a warning (exit 0).

## Required Arguments

- `<channel>` - Channel identifier (UUID or slug)

## Optional Options

- `--json` - Output in JSON format
- `--active-only` - Filter to active plans only (future: reserved, currently ignored with warning)
- `--inactive-only` - Filter to inactive plans only (future: reserved, currently ignored with warning)
- `--limit <integer>` - Limit number of results (future: reserved, currently ignored with warning)
- `--offset <integer>` - Offset for pagination (future: reserved, currently ignored with warning)
- `--test-db` - Use test database context

## Clock & Calendar

All date values reflect system local time via MasterClock. There is no per-channel timezone.

## Behavior Contract Rules (B-#)

### B-1: Channel Resolution

**Rule:** The command MUST resolve the channel by its identifier before listing plans.

**Behavior:**

- If channel is not found → exit 1, error message: "Error: Channel '<identifier>' not found"
- Channel must exist and be valid

### B-2: Output Format

**Rule:** The command MUST support both human-readable and JSON output formats.

**Behavior:**

- Without `--json`: Human-readable output with plan details
- With `--json`: Valid JSON with `status`, `total`, and `plans` array
- JSON output MUST include all plan fields for each plan

### B-3: Deterministic Sorting

**Rule:** Plans MUST be sorted deterministically. Table shows plans for the channel (omit channel column).

**Behavior:**

- Sorted by priority (descending), then name (case-insensitive ascending), then id (ascending)
- When priority and name are identical, sort by id ascending
- Output is deterministic and repeatable
- Keeps list stable across re-inserts
- Human-readable table omits channel column (plans are already scoped to a specific channel)

### B-4: Read-Only Operation

**Rule:** List operation MUST be read-only with no mutations.

**Behavior:**

- No database modifications
- No side effects
- Idempotent operation

### B-5: Optional Filtering and Pagination (Future-Safe)

**Rule:** The command MAY accept `--active-only`, `--inactive-only`, `--limit`, and `--offset` in future versions, but in baseline contract these are ignored with a warning.

**Behavior:**

- Unknown/future flags → warning message (exit 0, operation continues)
- When implemented, pagination must be deterministic and stable under concurrent inserts
- Filtering flags are reserved for future use

### B-6: JSON Error Shape

**Rule:** With `--json` on failure, return machine-usable shape: `{ "status": "error", "code": "CHANNEL_NOT_FOUND", "message": "Channel '<id>' not found" }`.

**Behavior:**

- Error codes:
  - `CHANNEL_NOT_FOUND` - Channel identifier not found
- Error message provides human-readable description
- Status is always `"error"` for failures, `"ok"` for success

### B-7: Zero-Result Behavior

**Rule:** If channel has no plans, exit 0 and display an explicit empty state.

**Behavior:**

- Human-readable: "No plans found for channel '<channel>'"
- JSON: `"total": 0, "plans": []`
- Exit code is 0 (success, just no results)

### B-8: Consistent Column Order (Human Output)

**Rule:** Field order and labeling must match show output exactly to ensure predictable diffs.

**Behavior:**

- Field order: ID, Name, Description, Cron, Start Date, End Date, Priority, Active, Created
- Labeling matches show command output format
- Ensures predictable diffs when comparing list vs show

### B-9: Deterministic Sorting Tie-Breaker

**Rule:** When priority and name are identical, sort by created_at ascending before id.

**Behavior:**

- Reason: Keeps list stable across re-inserts
- Final sort order: priority (desc) → name (case-insensitive asc) → created_at (asc) → id (asc)

## Data Contract Rules (D-#)

### D-1: Reflects Current State

**Rule:** Output MUST reflect all SchedulePlan rows for the channel at query time.

**Behavior:**

- Includes all plans regardless of `is_active` status
- Includes all plans regardless of date range validity
- No filtering applied unless explicitly specified

### D-2: Complete Field Set

**Rule:** Each plan in output MUST include all defined fields.

**Fields:**

- `id`, `channel_id`, `name`, `description`, `cron_expression`, `start_date`, `end_date`, `priority`, `is_active`, `created_at`, `updated_at`

### D-3: Test Database Isolation

**Rule:** `--test-db` MUST use an isolated test database session.

**Behavior:**

- Test database must not read/write production tables
- Test data should not persist between test sessions

### D-4: View Isolation

**Rule:** Under `--test-db`, list reads from isolated test schema; cross-pollination is forbidden.

**Behavior:**

- Test database schema is completely isolated
- No reads from production tables
- No writes to production tables
- Cross-pollination between test and production is forbidden

### D-5: Field Canonicalization

**Rule:** All date fields serialized as YYYY-MM-DD; all timestamps as full ISO-8601 UTC with Z.

**Behavior:**

- Date fields (`start_date`, `end_date`): Always formatted as `YYYY-MM-DD`
- Timestamp fields (`created_at`, `updated_at`): Always formatted as ISO-8601 UTC with `Z` suffix (e.g., `2025-01-01T12:00:00Z`)
- Nulls → `null` in JSON; `-` or omitted in human output
- Formatting is deterministic and consistent

## Output Format

### Human-Readable

```
Plans for channel RetroToons:
  ID: 550e8400-e29b-41d4-a716-446655440000
  Name: WeekdayPlan
  Description: Weekday programming plan
  Cron: * * * * MON-FRI (hour/min ignored)
  Start Date: 2025-01-01
  End Date: 2025-12-31
  Priority: 10
  Active: true
  Created: 2025-01-01T12:00:00Z

  ID: 660e8400-e29b-41d4-a716-446655440001
  Name: HolidayPlan
  Description: Holiday programming plan
  Cron: null
  Start Date: 2025-12-24
  End Date: 2025-12-31
  Priority: 30
  Active: true
  Created: 2025-01-02T10:00:00Z

Total: 2 plans
```

### Human-Readable (Empty Channel)

```
No plans found for channel RetroToons
```

### JSON

```json
{
  "status": "ok",
  "total": 2,
  "plans": [
    {
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
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "channel_id": "660e8400-e29b-41d4-a716-446655440001",
      "name": "HolidayPlan",
      "description": "Holiday programming plan",
      "cron_expression": null,
      "start_date": "2025-12-24",
      "end_date": "2025-12-31",
      "priority": 30,
      "is_active": true,
      "created_at": "2025-01-02T10:00:00Z",
      "updated_at": "2025-01-02T10:00:00Z"
    }
  ]
}
```

### JSON (Empty Channel)

```json
{
  "status": "ok",
  "total": 0,
  "plans": []
}
```

### JSON Error Format

```json
{
  "status": "error",
  "code": "CHANNEL_NOT_FOUND",
  "message": "Error: Channel 'invalid-channel' not found"
}
```

## Exit Codes

- `0`: Command succeeded (including zero results)
- `1`: Channel not found, DB failure, or `--test-db` session unavailable

## Error Conditions

- Channel not found: exit 1, "Error: Channel '<identifier>' not found"

## Tests

Planned tests:

- `tests/contracts/test_plan_list_contract.py::test_plan_list_help_flag_exits_zero`
- `tests/contracts/test_plan_list_contract.py::test_plan_list_channel_not_found_exits_one`
- `tests/contracts/test_plan_list_contract.py::test_plan_list_success_human`
- `tests/contracts/test_plan_list_contract.py::test_plan_list_success_json`
- `tests/contracts/test_plan_list_contract.py::test_plan_list_deterministic_sort`
- `tests/contracts/test_plan_list_contract.py::test_plan_list_sort_tiebreaker_created_at`
- `tests/contracts/test_plan_list_contract.py::test_plan_list_empty_channel_outputs_clear_message`
- `tests/contracts/test_plan_list_contract.py::test_plan_list_human_field_order_consistency`
- `tests/contracts/test_plan_list_contract.py::test_plan_list_json_error_shape`
- `tests/contracts/test_plan_list_data_contract.py::test_plan_list_reflects_current_state`
- `tests/contracts/test_plan_list_data_contract.py::test_plan_list_testdb_isolation`

## See Also

- [Domain: SchedulePlan](../../domain/SchedulePlan.md) - SchedulePlan domain documentation
- [SchedulePlan Show](SchedulePlanShowContract.md)
