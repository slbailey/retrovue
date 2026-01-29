# SchedulePlan Delete Contract

_Related: [Domain: SchedulePlan](../../domain/SchedulePlan.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> <plan> delete` command, which deletes an existing SchedulePlan.

**Context:** This command is part of the Plan Mode workflow, allowing operators to remove obsolete or test SchedulePlans from a channel once all dependent components (Zones, Patterns, ScheduleDays) are cleared.

**Coverage Implications:** Deletion of the last valid plan (or all plans) for a channel may leave the schedule without coverage, violating INV_PLAN_MUST_HAVE_FULL_COVERAGE for that channel. Operators should ensure at least one active plan with full 24-hour coverage remains after deletion. Deleting all plans for a channel triggers a scheduler warning about uncovered channels.

## Command Syntax

```bash
retrovue channel plan <channel> <plan> delete [--yes] [--test-db]
```

## Required Arguments

- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - SchedulePlan identifier (UUID or name)

## Optional Options

- `--yes` - Non-interactive confirmation for destructive action
- `--test-db` - Use test database context

## Operational Safety Expectations

- Destructive operation confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md)
- MUST refuse deletion if dependencies exist (Zones, Patterns, ScheduleDays) with actionable error
- `--test-db` MUST isolate from production

## Behavior Contract Rules (B-#)

### B-1: Channel and Plan Resolution

**Rule:** The command MUST resolve both channel and plan by their identifiers before deleting.

**Behavior:**

- If channel is not found → exit 1, error message: "Error: Channel '<identifier>' not found"
- If plan is not found → exit 1, error message: "Error: Plan '<identifier>' not found"
- If plan does not belong to channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"

### B-2: Dependency Check

**Rule:** If dependencies exist (Zones, Patterns, ScheduleDays), deletion MUST be refused.

**Behavior:**

- If Zones exist → exit 1, error message: "Error: Cannot delete plan '<plan>': plan has <N> zone(s). Delete zones first or archive the plan with --inactive."
- If Patterns exist → exit 1, error message: "Error: Cannot delete plan '<plan>': plan has <N> pattern(s). Delete patterns first or archive the plan with --inactive."
- If ScheduleDays exist → exit 1, error message: "Error: Cannot delete plan '<plan>': plan has <N> schedule day(s). Archive the plan with --inactive instead."
- Error message MUST suggest archiving with `--inactive` as an alternative
- **Note:** Archiving behavior is defined in [SchedulePlan Update Contract](SchedulePlanUpdateContract.md) under rule B-3 (--inactive toggle)

### B-3: Confirmation

**Rule:** Without `--yes`, the command MUST prompt for confirmation.

**Behavior:**

- Interactive prompt: "Are you sure you want to delete plan '<plan>'? [y/N]: "
- With `--yes`: Skip confirmation and proceed
- Tests run non-interactively MUST pass `--yes`

### B-4: Output Format

**Rule:** The command MUST support both human-readable and JSON output formats.

**Behavior:**

- Human-readable: "Plan deleted: <plan-name>"
- JSON: `{"status": "ok", "deleted": 1, "id": "<uuid>"}`

### B-5: Plan Mode Awareness

**Rule:** If the user is currently "in plan mode" for the plan being deleted, the system MUST exit plan mode and notify the user.

**Behavior:**

- If plan mode is active for the deleted plan → exit plan mode automatically
- Message: "Exited plan mode for deleted plan '<plan>'"
- Prevents dangling session context
- Applies to interactive plan mode sessions only

### B-6: Identifier Resolution Order

**Rule:** If `<plan>` looks like a UUID, resolve by id; otherwise resolve by name within the given channel.

**Behavior:**

- UUID format: 8-4-4-4-12 hex digits with hyphens → resolve by `id` field
- Non-UUID format → resolve by `name` field within the channel
- If UUID exists but belongs to a different channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"
- Name resolution is scoped to the specified channel

### B-7: Name Normalization

**Rule:** Name lookups are case-insensitive and trimmed (same normalization used for uniqueness).

**Behavior:**

- Case-insensitive matching: "WeekdayPlan" matches "weekdayplan", "WEEKDAYPLAN", etc.
- Leading/trailing whitespace is trimmed before matching
- If multiple normalized matches exist (shouldn't happen due to constraint) → exit 1 with clear diagnostic: "Error: Multiple plans match normalized name '<name>' in channel '<channel>'"
- Normalization matches the same rules used for uniqueness validation

## Data Contract Rules (D-#)

### D-1: Record Deletion

**Rule:** One SchedulePlan row MUST be removed from `schedule_plans` table when successful.

**Behavior:**

- Plan record is deleted
- Foreign key constraints may cascade delete related Zones/Patterns (if configured)
- ScheduleDays are NOT automatically deleted (they reference plan_id but may be nullable)

### D-2: No Orphaned References

**Rule:** No orphaned references should remain after deletion.

**Behavior:**

- ScheduleDays may retain `plan_id` reference (nullable) for historical purposes
- Zones and Patterns are deleted via cascade if foreign key is configured

### D-3: Transaction Boundaries

**Rule:** Plan deletion MUST be atomic within a single transaction.

**Behavior:**

- All database operations succeed or fail together
- No partial state persists on failure

### D-4: Test Database Isolation

**Rule:** `--test-db` MUST use an isolated test database session.

**Behavior:**

- Test database must not read/write production tables
- Test data should not persist between test sessions

### D-5: JSON Key Consistency

**Rule:** All structured outputs MUST follow snake_case and include "status" and "id" keys for success/failure consistency with create/update/delete contracts.

**Behavior:**

- Success JSON: `{"status": "ok", "deleted": 1, "id": "<uuid>"}`
- Error JSON: `{"status": "error", "code": "<ERR_CODE>", "message": "..."}`
- Keys use snake_case convention
- "status" key is always present ("ok" or "error")
- "id" key present in success responses
- Consistency ensures predictable parsing in CI/tooling integrations

## Output Format

### Human-Readable

```
Plan deleted: WeekdayPlan
```

### JSON

```json
{
  "status": "ok",
  "deleted": 1,
  "id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### JSON Error Format

```json
{
  "status": "error",
  "code": "PLAN_HAS_DEPENDENCIES",
  "message": "Error: Cannot delete plan 'WeekdayPlan': plan has 2 zone(s). Delete zones first or archive the plan with --inactive."
}
```

## Exit Codes

- `0`: Plan deleted successfully
- `1`: Channel not found, plan not found, plan doesn't belong to channel, dependencies prevent deletion, confirmation refused, DB failure, or `--test-db` session unavailable

## Error Conditions

- Channel not found: exit 1, "Error: Channel '<identifier>' not found"
- Plan not found: exit 1, "Error: Plan '<identifier>' not found"
- Plan doesn't belong to channel: exit 1, "Error: Plan '<plan>' does not belong to channel '<channel>'"
- Dependencies exist: exit 1, "Error: Cannot delete plan '<plan>': plan has <N> <dependency>(s). <suggestion>"
- Confirmation refused: exit 1 (when running interactively without `--yes`)

## Tests

Planned tests:

- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_help_flag_exits_zero`
- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_channel_not_found_exits_one`
- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_plan_not_found_exits_one`
- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_requires_yes`
- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_success`
- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_blocked_by_zones`
- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_blocked_by_patterns`
- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_blocked_by_schedule_days`
- `tests/contracts/test_plan_delete_contract.py::test_plan_delete_exits_plan_mode_if_active`
- `tests/contracts/test_plan_delete_data_contract.py::test_plan_delete_removes_record`
- `tests/contracts/test_plan_delete_data_contract.py::test_plan_delete_cascades_to_zones_patterns`

## See Also

- [Domain: SchedulePlan](../../domain/SchedulePlan.md) - SchedulePlan domain documentation
- [SchedulePlan Update](SchedulePlanUpdateContract.md)
- [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md)
