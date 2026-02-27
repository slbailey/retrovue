# INV-PLAN-FULL-COVERAGE-001 — Plan zones must cover the full broadcast day

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

Prevents channels from having periods with no editorial authority. A gap in zone coverage means ScheduleDay generation has no SchedulePlan mandate for those windows. Content introduced to fill such a gap would be constitutionally unanchored, violating `LAW-CONTENT-AUTHORITY`.

## Guarantee

An active SchedulePlan's zones must collectively cover the full broadcast day (00:00–24:00, relative to `programming_day_start`) with no temporal gaps.

## Preconditions

- Plan `is_active = true`.
- Zone coverage is evaluated at plan save, plan activation, and ScheduleDay generation time.

## Observability

Coverage is computed as the union of all zone time windows. Any uncovered interval within [00:00, 24:00] is a violation. The gap interval (start, end) MUST be reported.

## Deterministic Testability

Construct a plan with zones that leave a known gap (e.g., zones covering [00:00, 18:00] and [20:00, 24:00]). Assert that validation raises a coverage fault identifying [18:00, 20:00] as uncovered. No real-time waits required.

## Failure Semantics

**Planning fault.** The operator created or modified a plan without ensuring full broadcast day coverage. System must reject activation of the plan until coverage is complete.

## Required Tests

- `pkg/core/tests/contracts/test_inv_plan_full_coverage.py`

## Enforcement Evidence

TODO
