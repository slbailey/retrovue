# INV-SCHEDULEDAY-NO-GAPS-001 — ScheduleDay must have no temporal gaps in the broadcast day

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-LIVENESS`

## Purpose

Ensures continuous editorial coverage across the full broadcast day. A gap in ScheduleDay means Playlist has no content authority for that window. A gap in Playlist propagates into a PlaylogEvent gap — leaving a live channel with no constitutionally-authorized content to play, threatening `LAW-LIVENESS` at the playout layer.

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

- `pkg/core/tests/contracts/test_inv_scheduleday_no_gaps.py`

## Enforcement Evidence

TODO
