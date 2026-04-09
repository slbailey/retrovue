# ADR-016: Zone Concepts Preserved for Future DSL Promotion

**Status:** Accepted
**Date:** 2026-04-09
**Context:** RETA-88 Option B — SchedulePlan/Zone/Program CRUD island retirement

## Decision

The Zone entity and its CRUD surface are retired. The following Zone-level concepts are valuable scheduling primitives that should be promoted as DSL-native features when operator demand justifies them.

## Preserved Concepts

### DST Policy

Zone supported three policies for handling Daylight Saving Time transitions within a scheduling region:

| Policy | Behavior |
|--------|----------|
| `reject` | Refuse to schedule blocks that span a DST boundary |
| `shrink_one_block` | Shorten one block to absorb the lost hour (spring forward) |
| `expand_one_block` | Extend one block to fill the gained hour (fall back) |

**DSL promotion path:** Add a `dst_policy` directive at the DSL schedule or block level. The DslScheduleService compiler would apply the policy during ScheduleRevision generation.

### Day Filters

Zone supported restricting scheduling to specific days of week (e.g., weekday-only, weekend-only, or arbitrary day combinations).

**DSL promotion path:** Add `days:` filter syntax to DSL block definitions. Example: `days: [mon, tue, wed, thu, fri]` to restrict a block to weekdays only.

### Effective Date Ranges

Zone supported seasonal scheduling via effective date ranges — a zone could be active only during specific calendar periods (e.g., summer schedule, holiday schedule).

**DSL promotion path:** Add `effective:` date range syntax to DSL schedule definitions. Example: `effective: 2026-06-01..2026-08-31` for a summer-only schedule variant.

### Coverage Validation

Zone enforced two invariants that ensured complete, non-overlapping time coverage across the broadcast day:

- **INV-PLAN-FULL-COVERAGE-001** — zones must collectively cover the full broadcast day (00:00–24:00)
- **INV-PLAN-NO-ZONE-OVERLAP-001** — no two active zones may overlap

**DSL promotion path:** These validation rules should be reimplemented as compile-time checks in DslScheduleService when the DSL supports multiple scheduling regions within a single day. Currently, the DSL compiles a single contiguous schedule per channel-day (enforced by INV-COMPILED-BLOCK-CONTIGUITY-001 and INV-COMPILED-GRID-ALIGNMENT-001).

## Non-Goals

- This ADR does not schedule implementation of any of these features.
- This ADR does not preserve the Zone CRUD surface or SchedulePlan entity.
- These concepts are documentation only until a concrete DSL feature request arrives.

## Consequences

- Zone concepts are documented and discoverable for future DSL design.
- No CRUD code needs to be maintained for these features.
- When any concept is promoted, it follows the standard contracts-first workflow: invariant → test → DSL syntax → compiler implementation.
