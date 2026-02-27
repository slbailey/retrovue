# INV-SCHEDULEDAY-NO-GAPS-001 — ScheduleDay must have no temporal gaps in the broadcast day

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-LIVENESS`

## Purpose

Ensures continuous editorial coverage across the full broadcast day. A gap in ResolvedScheduleDay means TransmissionLog has no content authority for that window. A gap in TransmissionLog propagates into an ExecutionEntry gap — leaving a live channel with no constitutionally-authorized content to play, threatening `LAW-LIVENESS` at the playout layer.

## Guarantee

A materialized ScheduleDay must provide continuous, gap-free SchedulableAsset coverage across the full broadcast day, from `programming_day_start` to `programming_day_start + 24h`.

## Preconditions

- ScheduleDay has been materialized (generation is complete).
- "Gap" means an interval within the broadcast day for which no zone assignment exists.

## Observability

After ScheduleDay generation, coverage is computed as the union of all zone slot intervals. Any uncovered sub-interval within the broadcast day is a violation. The gap interval (start, end) MUST be logged. Generation MUST either fill the gap with declared filler or halt with an explicit gap fault — it MUST NOT silently emit a ScheduleDay with a gap.

## Deterministic Testability

Generate a ScheduleDay from a plan that has a known gap (upstream `INV-PLAN-FULL-COVERAGE-001` was bypassed or the plan used an `empty=True` override). Assert that coverage validation raises a gap fault before the ScheduleDay is committed. No real-time waits required.

## Failure Semantics

**Planning fault** (upstream plan had coverage gaps that should have been caught by `INV-PLAN-FULL-COVERAGE-001`). If that invariant was enforced, a gap here indicates a generation logic fault — **Runtime fault**.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvScheduledayNoGaps001`

## Enforcement Evidence

- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `validate_scheduleday_contiguity()` computes absolute slot intervals, sorts by start, checks first slot starts at broadcast_day_start, adjacent pairs have no gap/overlap, last slot ends at broadcast_day_end
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.store()` calls `validate_scheduleday_contiguity()` before commit when `programming_day_start_hour` is configured
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.force_replace()` calls `validate_scheduleday_contiguity()` before commit when `programming_day_start_hour` is configured
- Error tag: `INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED`
