# INV-PLAN-NO-ZONE-OVERLAP-001 — No two active zones in a plan may overlap

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

Prevents ambiguous editorial authority within a single plan. Overlapping zones with different SchedulableAssets create an unresolvable content conflict at ScheduleDay generation time. Overlap means two zones simultaneously claim authority over the same time window, which contradicts the single-source mandate of `LAW-CONTENT-AUTHORITY`.

## Guarantee

No two active zones within the same SchedulePlan may have overlapping time windows, after grid normalization and considering day-of-week filters.

## Preconditions

- Both zones are active (not archived or disabled).
- Both zones belong to the same SchedulePlan.
- Day-of-week filters are applied before checking overlap (e.g., a Mon–Fri zone and a Sat–Sun zone do not overlap).

## Observability

At plan save or zone modification, compute pairwise intersection of active zone windows per day-of-week combination. Any non-empty intersection is a violation. The overlapping window and zone identifiers MUST be reported.

## Deterministic Testability

Construct a plan with two zones whose windows intersect (e.g., Zone A: 18:00–22:00, Zone B: 20:00–24:00, both active Mon–Sun). Assert that validation raises an overlap fault identifying the [20:00, 22:00] intersection. No real-time waits required.

## Failure Semantics

**Planning fault.** The operator created or modified zones without ensuring non-overlapping coverage. System must reject the conflicting zone configuration.

## Required Tests

- `pkg/core/tests/contracts/test_inv_plan_no_zone_overlap.py`

## Enforcement Evidence

TODO
