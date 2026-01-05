# Program Contract

_Related: [Domain: Program](../../domain/Program.md) • [Domain: SchedulePlan](../../domain/SchedulePlan.md) • [SchedulePlanInvariantsContract](SchedulePlanInvariantsContract.md)_

## Purpose

This contract defines the critical rules and constraints that must be enforced for Programs within SchedulePlans. Programs are the building blocks of schedule plans, defining what content should air when.

## Scope

This contract applies to:

- **Program** - Scheduled pieces of content in plans that define what content runs when using `start_time` and `duration`
- **SchedulePlan** - Top-level operator-created plans that contain programs
- **Content references** - Series, Movies, VirtualAssets, or rule-based selectors referenced by programs

## Contract Rules

### P-1: Programs belong to a single SchedulePlan

**Rule:** Each Program MUST belong to exactly one SchedulePlan via the `plan_id` foreign key.

**Rationale:** Programs are the building blocks of plans. Each program must be associated with a specific plan to enable plan-based scheduling and layering.

**Enforcement:**
- Database constraint MUST enforce `plan_id` foreign key relationship
- `plan_id` MUST be required (NOT NULL)
- Programs MUST NOT be orphaned (must reference a valid SchedulePlan)
- When a SchedulePlan is deleted, associated programs MUST be handled according to cascade rules

**Test Coverage:** Tests must verify that:
- Programs cannot be created without a valid `plan_id`
- Programs cannot reference non-existent plans
- Plan deletion properly handles associated programs (cascade or prevent)

### P-2: Start times are relative to broadcast day (not wall clock)

**Rule:** Program `start_time` MUST be expressed in schedule-time (00:00 to 24:00 relative to the channel's broadcast day start), not wall-clock time.

**Rationale:** Schedule-time allows plans to be reused across different calendar dates while maintaining consistent programming structure. The channel's `programming_day_start` (broadcast day start) anchors schedule-time to wall-clock time during resolution.

**Enforcement:**
- `start_time` MUST be in "HH:MM" format
- `start_time` MUST represent an offset from 00:00 (programming day start)
- `start_time` MUST be in the range 00:00 to 24:00
- Time resolution MUST combine `start_time` with channel's `programming_day_start` to produce wall-clock times
- Validation MUST reject invalid time formats or out-of-range values

**Test Coverage:** Tests must verify that:
- Valid "HH:MM" format times are accepted
- Invalid formats are rejected
- Times outside 00:00-24:00 range are rejected
- Time resolution correctly combines schedule-time with broadcast day start

### P-3: Duration is required

**Rule:** Program `duration` MUST be provided and MUST be a positive integer representing minutes.

**Rationale:** Duration is essential for determining when a program ends and whether programs overlap. Without duration, the system cannot calculate program boundaries.

**Enforcement:**
- `duration` MUST be required (NOT NULL)
- `duration` MUST be a positive integer (greater than 0)
- `duration` MUST be expressed in minutes
- `duration` SHOULD align with channel's `grid_block_minutes` (validation warning if not aligned)
- Validation MUST reject zero, negative, or non-integer duration values

**Test Coverage:** Tests must verify that:
- Programs cannot be created without a duration
- Zero or negative durations are rejected
- Non-integer durations are rejected
- Duration alignment with grid is validated (when channel is available)

### P-4: Content reference can point to a Series, Movie, VirtualAsset, or rule-based selector

**Rule:** Program `content_ref` MUST reference valid content based on the `content_type`:
- `content_type: "series"` → Series identifier or UUID
- `content_type: "asset"` → Asset UUID (Movie or single asset)
- `content_type: "virtual_package"` → VirtualAsset UUID
- `content_type: "rule"` → Rule JSON for filtered selection
- `content_type: "random"` → Random selection rule JSON

**Rationale:** Programs support multiple content selection strategies. The content reference must match the declared content type and reference valid entities.

**Enforcement:**
- `content_type` MUST be one of: "series", "asset", "rule", "random", "virtual_package"
- `content_ref` MUST be provided (NOT NULL)
- `content_ref` MUST be valid for the specified `content_type`:
  - For "asset": MUST reference a valid Asset UUID with `state='ready'` and `approved_for_broadcast=true`
  - For "series": MUST reference a valid Series identifier
  - For "virtual_package": MUST reference a valid VirtualAsset UUID
  - For "rule" or "random": MUST be valid JSON
- Validation MUST reject invalid content types or references

**Test Coverage:** Tests must verify that:
- Valid content types are accepted
- Invalid content types are rejected
- Content references are validated against content type
- Asset references are validated for eligibility (ready + approved)
- VirtualAsset references are validated for existence
- Rule/random JSON is validated for structure

### P-5: Programs must not overlap within the same SchedulePlan unless explicitly allowed

**Rule:** Programs within the same SchedulePlan MUST NOT overlap in time, unless the plan explicitly allows overlaps (future feature).

**Rationale:** Each time slice within a plan must have exactly one content assignment. Overlapping programs would create ambiguity about what content should play.

**Enforcement:**
- Overlap detection MUST check: `(start_time < other.end_time) AND (end_time > other.start_time)` where `end_time = start_time + duration`
- Programs that touch at boundaries (e.g., one ends where another starts) are allowed
- Overlap validation MUST be performed within the same `plan_id` only
- Programs in different plans can overlap (they're independent)
- If overlap is explicitly allowed (future feature), validation MUST be skipped
- Validation MUST reject overlapping programs within the same plan

**Test Coverage:** Tests must verify that:
- Overlapping programs within the same plan are rejected
- Programs in different plans can overlap
- Boundary cases (touching programs) are handled correctly
- Time calculations correctly handle schedule-time offsets
- Overlap detection correctly calculates end_time from start_time + duration

## Validation Workflows

### Program Creation

When creating a program, the system MUST:
1. Validate P-1: Ensure `plan_id` references a valid SchedulePlan
2. Validate P-2: Ensure `start_time` is valid schedule-time format
3. Validate P-3: Ensure `duration` is positive integer
4. Validate P-4: Ensure `content_ref` matches `content_type` and references valid content
5. Validate P-5: Ensure no overlap with existing programs in the same plan

### Program Update

When updating a program, the system MUST:
1. Re-validate all rules (P-1 through P-5)
2. Check for overlap with other programs (excluding the program being updated)
3. Ensure content reference remains valid after update

### Plan Validation

When validating a SchedulePlan, the system MUST:
1. Validate all programs in the plan against P-1 through P-5
2. Check for overlaps across all programs in the plan
3. Verify content references are valid and eligible

## Error Handling

When a program violates contract rules, the system MUST:
- Provide clear, actionable error messages
- Identify the specific rule violated (P-1 through P-5)
- Identify the specific program that violates the rule
- Suggest corrective actions when possible

## Out of Scope

The following are NOT part of this contract:
- Content selection algorithms (how content is chosen from rules)
- VirtualAsset expansion logic
- ScheduleDay generation from programs
- Plan layering and priority resolution (covered in SchedulePlanInvariantsContract)
- Grid alignment validation (covered in SchedulePlanInvariantsContract)

## Related Contracts

- [SchedulePlanInvariantsContract](SchedulePlanInvariantsContract.md) - Plan-level invariants including program overlap rules
- [ScheduleDayContract](ScheduleDayContract.md) - Resolved schedule day validation
- [PlaylogEventContract](PlaylogEventContract.md) - Playout event validation

## See Also

- [Domain: Program](../../domain/Program.md) - Complete domain documentation
- [Domain: SchedulePlan](../../domain/SchedulePlan.md) - Plan structure and relationships

