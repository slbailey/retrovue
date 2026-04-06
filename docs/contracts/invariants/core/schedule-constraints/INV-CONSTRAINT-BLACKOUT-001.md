# INV-CONSTRAINT-BLACKOUT-001 — Blackout exclusion windows

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`

## Purpose

Prevents scheduling content during operator-declared exclusion windows. Blackout constraints protect against editorial errors where date-sensitive content (seasonal specials, rights-expiring material) appears outside its permitted broadcast window. Violation risks `LAW-CONTENT-AUTHORITY` by allowing content the operator has explicitly excluded.

## Guarantee

Content subject to an active blackout constraint MUST NOT appear in the schedule during the blackout window. A blackout window is defined by date range, daily time range, and optional day-of-week filters.

## Preconditions

- At least one blackout constraint is defined for the channel or plan.
- The constraint's date range overlaps the broadcast day being validated.
- The constraint's day-of-week filter (if any) includes the day being validated.

## Observability

At plan-edit or compilation time, each scheduled asset is checked against all active blackout constraints. Any asset appearing within a matching blackout window produces a structured violation identifying the asset, the blackout window, and the constraint reason.

## Deterministic Testability

Construct a plan with one zone containing Asset A. Define a blackout constraint excluding Asset A on the target broadcast day and time window. Assert that validation raises a blackout violation. Verify that assets outside the blackout or on non-matching days pass. No real-time waits required.

## Failure Semantics

**Planning fault.** The operator scheduled content during a blackout window. System MUST reject the conflicting schedule configuration.

## Required Tests

- `pkg/core/tests/contracts/scheduling/test_schedule_constraints.py::TestInvConstraintBlackout001`

## Enforcement Evidence

- `pkg/core/src/retrovue/scheduling/schedule_constraints.py` — `check_blackout_constraints()`
- `pkg/core/src/retrovue/usecases/zone_coverage_check.py` — integrated into `validate_zone_plan_integrity()` after eligibility checks
- Error tag: `INV-CONSTRAINT-BLACKOUT-001-VIOLATED`
