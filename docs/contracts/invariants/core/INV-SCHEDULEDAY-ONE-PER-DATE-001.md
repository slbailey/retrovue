# INV-SCHEDULEDAY-ONE-PER-DATE-001 — Exactly one ScheduleDay per channel per broadcast date

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-IMMUTABILITY`

## Purpose

Prevents multiple conflicting authoritative schedules for the same channel-date. Two ScheduleDays for the same `(channel_id, schedule_date)` create an ambiguous derivation root: Playlist and PlaylogEvent cannot determine which is the canonical upstream artifact, violating `LAW-DERIVATION`.

## Guarantee

At any point in time, at most one ScheduleDay record must exist for a given `(channel_id, schedule_date)` pair.

## Preconditions

- None. This invariant holds unconditionally — including during force-regeneration and manual override workflows.

## Observability

Enforced by a unique database constraint on `(channel_id, schedule_date)`. Any insert that would violate the constraint MUST be rejected. Force-regeneration MUST delete or atomically replace the existing record; it MUST NOT insert a second record.

## Deterministic Testability

Materialize a ScheduleDay for (channel=C, date=D). Attempt to insert a second ScheduleDay for the same (C, D). Assert the insert is rejected with a constraint violation. No real-time waits required.

## Failure Semantics

**Planning fault.** The generation service attempted to create a duplicate ScheduleDay without first removing the existing record. This indicates a logic error in the generation or regeneration workflow.

## Required Tests

- `pkg/core/tests/contracts/test_inv_scheduleday_one_per_date.py`

## Enforcement Evidence

TODO
