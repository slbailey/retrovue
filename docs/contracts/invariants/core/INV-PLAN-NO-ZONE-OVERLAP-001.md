# INV-PLAN-NO-ZONE-OVERLAP-001 — No two active zones in a plan may overlap

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

Prevents ambiguous editorial authority within a single plan. Overlapping zones with different SchedulableAssets create an unresolvable content conflict at ScheduleDay generation time. Overlap means two zones simultaneously claim authority over the same time window, which contradicts the single-source mandate of `LAW-CONTENT-AUTHORITY`.

## Guarantee

No two active zones within the same SchedulePlan may have overlapping time windows, after normalization to broadcast-day-relative coordinates and considering day-of-week filters.

## Preconditions

- Both zones are enabled (not disabled).
- Both zones belong to the same SchedulePlan.
- Day-of-week filters are applied before checking overlap (e.g., a Mon–Fri zone and a Sat–Sun zone do not overlap).

## Observability

At zone creation or modification, compute pairwise intersection of enabled zone windows per day-of-week combination. Any non-empty intersection is a violation. The overlapping window and zone identifiers MUST be reported.

## Deterministic Testability

Construct a plan with two zones whose windows intersect (e.g., Zone A: 06:00–18:00, Zone B: 16:00–24:00, both active Mon–Sun). Assert that validation raises an overlap fault identifying the intersection. Verify that mutually exclusive day filters (Mon–Fri vs Sat–Sun) do not trigger overlap. No real-time waits required.

## Failure Semantics

**Planning fault.** The operator created or modified zones without ensuring non-overlapping coverage. System MUST reject the conflicting zone configuration.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvPlanNoZoneOverlap001`

## Enforcement Evidence

- `pkg/core/src/retrovue/usecases/zone_coverage_check.py` — `check_overlap()`, `validate_zone_plan_integrity()`
- `pkg/core/src/retrovue/usecases/zone_add.py` — called before `db.commit()`
- `pkg/core/src/retrovue/usecases/zone_update.py` — called before `db.commit()`
- Error tag: `INV-PLAN-NO-ZONE-OVERLAP-001-VIOLATED`
