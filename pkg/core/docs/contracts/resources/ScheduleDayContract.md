# Schedule Day Contract

_Related: [Domain: ScheduleDay](../../domain/ScheduleDay.md) • [Domain: SchedulePlan](../../domain/SchedulePlan.md) • [Domain: PlaylogEvent](../../domain/PlaylogEvent.md) • [SchedulePlanInvariantsContract](SchedulePlanInvariantsContract.md)_

## Purpose

Define the behavioral contract for BroadcastScheduleDay operations in RetroVue. BroadcastScheduleDay represents a finalized instance of a schedule for a specific channel and date, built from a SchedulePlan. Once created, it becomes immutable unless explicitly overridden. This is the execution-time view of "what will air" that feeds the EPG and generates PlaylogEvent entries.

---

## Command Shape

### Generate Schedule Day

```
retrovue schedule-day generate \
  --channel-id <uuid> \
  --date <YYYY-MM-DD> \
  [--force] \
  [--dry-run] \
  [--json] [--test-db]
```

### Override Schedule Day

```
retrovue schedule-day override \
  --channel-id <uuid> \
  --date <YYYY-MM-DD> \
  --plan-id <uuid> \
  [--yes] \
  [--json] [--test-db]
```

### Regenerate Schedule Day

```
retrovue schedule-day regenerate \
  --channel-id <uuid> \
  --date <YYYY-MM-DD> \
  [--force] \
  [--json] [--test-db]
```

### List Schedule Days

```
retrovue schedule-day list \
  [--channel-id <uuid>] \
  [--date <YYYY-MM-DD>] \
  [--date-range <start:end>] \
  [--json] [--test-db]
```

### Show Schedule Day

```
retrovue schedule-day show \
  --channel-id <uuid> \
  --date <YYYY-MM-DD> \
  [--json] [--test-db]
```

### Validate Schedule Day

```
retrovue schedule-day validate \
  --channel-id <uuid> \
  --date <YYYY-MM-DD> \
  [--json] [--test-db]
```

---

## Parameters

### Generate Parameters

- `--channel-id` (required): UUID of the Channel
- `--date` (required): Broadcast date in "YYYY-MM-DD" format
- `--force` (optional): Overwrite existing schedule day without confirmation
- `--dry-run` (optional): Preview schedule generation without persisting
- `--json` (optional): Machine-readable output
- `--test-db` (optional): Use isolated test database session

### Override Parameters

- `--channel-id` (required): UUID of the Channel
- `--date` (required): Broadcast date in "YYYY-MM-DD" format
- `--plan-id` (required): UUID of the SchedulePlan to use for override
- `--yes` (optional): Skip confirmation prompt
- `--json` (optional): Machine-readable output
- `--test-db` (optional): Use isolated test database session

### Regenerate Parameters

- `--channel-id` (required): UUID of the Channel
- `--date` (required): Broadcast date in "YYYY-MM-DD" format
- `--force` (optional): Force regeneration even if schedule day exists
- `--json` (optional): Machine-readable output
- `--test-db` (optional): Use isolated test database session

### List Parameters

- `--channel-id` (optional): Filter by channel UUID
- `--date` (optional): Filter by specific date
- `--date-range` (optional): Filter by date range (format: "YYYY-MM-DD:YYYY-MM-DD")
- `--json` (optional): Machine-readable output
- `--test-db` (optional): Use isolated test database session

### Show Parameters

- `--channel-id` (required): UUID of the Channel
- `--date` (required): Broadcast date in "YYYY-MM-DD" format
- `--json` (optional): Machine-readable output
- `--test-db` (optional): Use isolated test database session

### Validate Parameters

- `--channel-id` (required): UUID of the Channel
- `--date` (required): Broadcast date in "YYYY-MM-DD" format
- `--json` (optional): Machine-readable output
- `--test-db` (optional): Use isolated test database session

---

## Safety Expectations

- **Generate**: Creates a new BroadcastScheduleDay record by resolving the active SchedulePlan for the channel and date. Validates plan is active.
- **Override**: Explicitly replaces an existing schedule day with a new one. Requires confirmation unless `--yes` provided. Sets `is_manual_override=true`.
- **Regenerate**: Recreates schedule day from its plan. Useful after plan updates. Requires `--force` if schedule day already exists.
- **No side effects**: Operations affect only the specified schedule day and downstream PlaylogEvent generation.
- `--test-db` MUST isolate from production data.

---

## Output Format

### Human-Readable (Generate)

```
Schedule day generated:
  ID: 550e8400-e29b-41d4-a716-446655440000
  Channel: RetroVue-1
  Date: 2025-01-15
  Plan: WeekdayPlan
  Manual Override: false
  Gaps: 0
  Warnings: 0
  Playlog Events: 48
  Created: 2025-01-01 12:00:00
```

### JSON (Generate)

```json
{
  "status": "ok",
  "schedule_day": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "channel_id": "123e4567-e89b-12d3-a456-426614174000",
    "channel_name": "RetroVue-1",
    "plan_id": "789e0123-e45b-67c8-d901-234567890abc",
    "plan_name": "WeekdayPlan",
    "schedule_date": "2025-01-15",
    "is_manual_override": false,
    "gaps_count": 0,
    "warnings_count": 0,
    "playlog_events_count": 48,
    "created_at": "2025-01-01T12:00:00Z",
    "updated_at": null
  }
}
```

### Human-Readable (Show with Warnings)

```
Schedule Day:
  ID: 550e8400-e29b-41d4-a716-446655440000
  Channel: RetroVue-1
  Date: 2025-01-15
  Plan: WeekdayPlan
  Manual Override: false
  Gaps: 2
    - 02:00-02:30 (no content assigned)
    - 14:15-14:45 (no content assigned)
  Warnings: 1
    - Gap detected in morning block (06:00-09:00)
  Playlog Events: 46
  Created: 2025-01-01 12:00:00
```

---

## Exit Codes

- `0`: Operation completed successfully
- `1`: Validation failed, plan not found, channel not found, or generation failure

---

## Behavior Contract Rules (D-#)

### One ScheduleDay Per (Channel, Date) Tuple

- **D-1:** Exactly one BroadcastScheduleDay MUST exist per (channel_id, schedule_date) tuple
- **D-2:** Unique constraint on (channel_id, schedule_date) MUST be enforced at database level
- **D-3:** Generating a schedule day for an existing (channel_id, schedule_date) tuple MUST overwrite the existing record
- **D-4:** Overwriting an existing schedule day MUST require `--force` flag or explicit confirmation
- **D-5:** Overwriting without `--force` MUST exit 1 with error: "Error: Schedule day already exists for channel and date. Use --force to overwrite."
- **D-6:** Manual override operations MUST explicitly overwrite existing schedule days (different from generate)

### Active Plan Requirement

- **D-7:** Schedule day generation MUST reference an active SchedulePlan at generation time
- **D-8:** Plan resolution MUST identify the active plan for the channel and date based on cron_expression, date ranges, and priority
- **D-9:** If no active plan matches for the channel and date, generation MUST exit 1 with error: "Error: No active plan found for channel and date."
- **D-10:** Plan MUST have `is_active=true` to be eligible for schedule generation
- **D-14:** Plan MUST have at least one SchedulePlanBlockAssignment (enforced by plan validation)

### Gap Detection and Warnings

- **D-15:** Schedule generation SHOULD detect gaps in content coverage
- **D-16:** Gaps are defined as time periods within the broadcast day (00:00-24:00) with no content assigned
- **D-17:** Gaps SHOULD be flagged as warnings, not errors (gaps are allowed but should be noted)
- **D-18:** Gap warnings MUST identify the time period and reason (e.g., "no content assigned", "block assignment missing")
- **D-19:** Gap detection MUST check all time periods within the broadcast day
- **D-20:** Schedule day output SHOULD include gap count and gap details when gaps exist
- **D-21:** Validate command MUST report all gaps and warnings
- **D-22:** Gaps MUST NOT prevent schedule day generation (warnings only, not errors)

### Explicit Overwrites

- **D-23:** Overwriting an existing schedule day MUST be explicit via `--force` flag or override command
- **D-24:** Override command MUST create a new BroadcastScheduleDay record with `is_manual_override=true`
- **D-25:** Override command MUST delete or archive the existing schedule day for the (channel_id, schedule_date) tuple
- **D-26:** Override command MUST require confirmation unless `--yes` flag is provided
- **D-27:** Override confirmation prompt MUST ask: "Are you sure you want to override this schedule day? This will replace the existing schedule. (yes/no): "
- **D-28:** Override operation MUST preserve historical record (soft delete or archive) for audit purposes
- **D-29:** Manual override schedule days MUST set `is_manual_override=true`
- **D-30:** Manual override schedule days MAY reference a different plan than the automatically resolved plan

### Immutability

- **D-31:** Once generated, BroadcastScheduleDay is immutable unless explicitly overridden
- **D-32:** Schedule day records MUST NOT be modified after creation (no update operations)
- **D-33:** To change a schedule day, operators MUST regenerate or override it
- **D-34:** Regenerate command MUST delete and recreate the schedule day from its plan
- **D-35:** Immutability ensures EPG and playout systems have a stable view of "what will air"

### PlaylogEvent Generation

- **D-36:** Schedule day generation MUST trigger generation of BroadcastPlaylogEvent entries
- **D-37:** PlaylogEvent generation MUST occur as part of schedule day creation (same transaction or immediately after)
- **D-38:** PlaylogEvent entries MUST be generated for all content assignments in the schedule day
- **D-39:** Each content assignment in the schedule day MUST result in at least one PlaylogEvent entry
- **D-40:** PlaylogEvent entries MUST reference the schedule day's channel_id and schedule_date
- **D-41:** PlaylogEvent generation MUST use the resolved content from SchedulePlanBlockAssignment records
- **D-42:** PlaylogEvent generation MUST validate content eligibility
- **D-43:** If PlaylogEvent generation fails, schedule day creation MUST fail (rollback transaction)
- **D-44:** Schedule day output SHOULD include count of generated PlaylogEvent entries

### Date Format Validation

- **D-45:** `schedule_date` MUST be in "YYYY-MM-DD" format
- **D-46:** Invalid date format MUST exit 1 with error: "Error: Invalid date format. Expected YYYY-MM-DD."
- **D-47:** Invalid date values (e.g., 2025-13-45) MUST exit 1 with error: "Error: Invalid date value."
- **D-48:** Date validation MUST occur before any database operations

### Referential Integrity

- **D-49:** `channel_id` MUST reference an existing Channel
- **D-50:** Creating schedule day with non-existent channel MUST exit 1 with error: "Error: Channel not found."
- **D-51:** `plan_id` MUST reference an existing SchedulePlan (if provided)
- **D-52:** Override with non-existent plan MUST exit 1 with error: "Error: Plan not found."

### Dry Run Support

- **D-55:** `--dry-run` flag MUST preview schedule generation without persisting
- **D-56:** Dry run MUST show what schedule day would be created (plan, gaps, warnings)
- **D-57:** Dry run MUST NOT create any database records
- **D-58:** Dry run MUST validate all constraints (plan existence, etc.)
- **D-59:** Dry run output SHOULD match generate output format (without database IDs)

### Output Format

- **D-60:** `--json` flag MUST return valid JSON with the operation result
- **D-61:** Human-readable output MUST include all schedule day fields (id, channel, date, plan, gaps, warnings, playlog count)
- **D-62:** Show command MUST display schedule day details including gaps and warnings
- **D-63:** List command MUST show all schedule days matching filters

### Test Database

- **D-64:** `--test-db` flag MUST behave identically in output shape and exit codes
- **D-65:** `--test-db` MUST NOT read/write production tables

---

## Data Contract Rules (D-#)

### Persistence

- **D-1:** Schedule day records MUST be persisted in `broadcast_schedule_days` table
- **D-2:** Timestamps MUST be stored in UTC with timezone information
- **D-3:** `channel_id` MUST be stored as UUID foreign key reference
- **D-4:** `plan_id` MUST be stored as UUID foreign key reference (nullable)
- **D-6:** `schedule_date` MUST be stored as TEXT in "YYYY-MM-DD" format
- **D-7:** `is_manual_override` MUST be stored as BOOLEAN (NOT NULL, default false)
- **D-8:** Database constraint MUST enforce unique (channel_id, schedule_date) tuple

### Referential Integrity

- **D-9:** Foreign key constraints MUST ensure channel_id references valid Channel
- **D-10:** Foreign key constraints MUST ensure plan_id references valid SchedulePlan (if not null)
- **D-12:** Deleting a channel SHOULD handle dependent schedule days (CASCADE or RESTRICT based on schema)
- **D-13:** Deleting a plan SHOULD preserve schedule days (set plan_id to null or prevent deletion if schedule days exist)

### Transaction Boundaries

- **D-14:** Schedule day generation MUST occur within a single database transaction
- **D-15:** PlaylogEvent generation MUST occur in the same transaction as schedule day creation
- **D-16:** Transaction MUST rollback on any validation failure or PlaylogEvent generation failure
- **D-17:** Test database operations MUST use isolated transactions

### Immutability Enforcement

- **D-18:** Database schema SHOULD prevent direct updates to schedule day records (read-only after creation)
- **D-19:** If updates are allowed at database level, application layer MUST enforce immutability (no update operations exposed)
- **D-20:** Override operations MUST create new records rather than modifying existing ones

---

## Tests

Planned tests:

- `tests/contracts/test_schedule_day_generate_contract.py::test_schedule_day_generate__success`
- `tests/contracts/test_schedule_day_generate_contract.py::test_schedule_day_generate__duplicate_without_force_fails`
- `tests/contracts/test_schedule_day_generate_contract.py::test_schedule_day_generate__no_active_plan_fails`
- `tests/contracts/test_schedule_day_generate_contract.py::test_schedule_day_generate__inactive_plan_fails`
- `tests/contracts/test_schedule_day_generate_contract.py::test_schedule_day_generate__with_gaps_warns`
- `tests/contracts/test_schedule_day_generate_contract.py::test_schedule_day_generate__generates_playlog_events`
- `tests/contracts/test_schedule_day_generate_contract.py::test_schedule_day_generate__dry_run`
- `tests/contracts/test_schedule_day_override_contract.py::test_schedule_day_override__success_with_confirmation`
- `tests/contracts/test_schedule_day_override_contract.py::test_schedule_day_override__with_yes_flag`
- `tests/contracts/test_schedule_day_override_contract.py::test_schedule_day_override__sets_manual_override_flag`
- `tests/contracts/test_schedule_day_regenerate_contract.py::test_schedule_day_regenerate__success`
- `tests/contracts/test_schedule_day_regenerate_contract.py::test_schedule_day_regenerate__force_flag`
- `tests/contracts/test_schedule_day_validate_contract.py::test_schedule_day_validate__reports_gaps`
- `tests/contracts/test_schedule_day_validate_contract.py::test_schedule_day_validate__reports_warnings`

---

## Error Conditions

### Validation Errors

- Duplicate without force: exit 1, "Error: Schedule day already exists for channel and date. Use --force to overwrite."
- No active plan: exit 1, "Error: No active plan found for channel and date."
- Inactive plan: exit 1, "Error: Plan is not active."
- Channel not found: exit 1, "Error: Channel not found."
- Plan not found: exit 1, "Error: Plan not found."
- Invalid date format: exit 1, "Error: Invalid date format. Expected YYYY-MM-DD."
- Invalid date value: exit 1, "Error: Invalid date value."

---

## Gap Detection Example

### Schedule Day with Gaps

```
Schedule Day:
  Channel: RetroVue-1
  Date: 2025-01-15
  Gaps: 2
    - 02:00-02:30: No content assigned in "Overnight Block"
    - 14:15-14:45: Missing assignment in "Afternoon Block"
  Warnings: 2
    - Gap detected: 02:00-02:30 (30 minutes)
    - Gap detected: 14:15-14:45 (30 minutes)
  Status: Generated with warnings
```

**Result:** Schedule day is created successfully, but warnings are reported for operator review.

---

## PlaylogEvent Generation Flow

1. **Schedule Day Created**: BroadcastScheduleDay record persisted
2. **Plan Resolved**: SchedulePlan and SchedulePlanBlockAssignment records retrieved
3. **Content Resolved**: Actual content selections extracted from plan assignments
4. **PlaylogEvent Generation**: For each content assignment:
   - Calculate precise start_utc and end_utc timestamps
   - Create BroadcastPlaylogEvent record
   - Link to schedule day's channel_id and schedule_date
5. **Transaction Commit**: All records committed atomically

**Critical Rule:** If PlaylogEvent generation fails at any step, the entire transaction (including schedule day) MUST rollback.

---

## See also

- [Domain: ScheduleDay](../../domain/ScheduleDay.md) - Complete domain documentation
- [Domain: SchedulePlan](../../domain/SchedulePlan.md) - Plan entity that generates schedule days
- [Domain: PlaylogEvent](../../domain/PlaylogEvent.md) - Generated playout events
- [SchedulePlanInvariantsContract](SchedulePlanInvariantsContract.md) - Cross-entity invariants
- [CLI Data Guarantees](cross-domain/CLI_Data_Guarantees.md) - General CLI guarantees

