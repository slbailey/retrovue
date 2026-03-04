# INV-RESCHEDULE-FUTURE-GUARD-001 — Reschedule operations reject past or currently-airing artifacts

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-RUNTIME-AUTHORITY`

## Purpose

`LAW-IMMUTABILITY` prohibits mutation of published artifacts. `LAW-RUNTIME-AUTHORITY` establishes that currently-airing execution entries are authoritative and MUST NOT be disrupted. Without a temporal guard, an operator reschedule could delete a block that is actively being served to viewers, violating both laws.

## Guarantee

A reschedule operation (deletion-for-regeneration) on a Tier 1 `ProgramLogDay` or Tier 2 `PlaylistEvent` MUST be rejected when the artifact's coverage window has begun or is in the past.

- Tier 1: `ProgramLogDay.range_start` MUST be strictly greater than `now()`.
- Tier 2: `PlaylistEvent.start_utc_ms` MUST be strictly greater than `now_utc_ms`.
- Tier 1 rows with `range_start IS NULL` MUST be rejected (temporal eligibility cannot be determined).

## Preconditions

- Wall clock (`datetime.now(timezone.utc)`) is the authoritative time source for boundary evaluation.
- The artifact exists in the database.

## Observability

Rejected reschedule attempts MUST raise `RescheduleRejectedError` with the invariant ID, the artifact identifier, and the evaluated time boundary.

## Deterministic Testability

Insert a `ProgramLogDay` with `range_start = now - 1h`. Attempt reschedule. Assert rejection. Insert a `ProgramLogDay` with `range_start = now + 1h`. Attempt reschedule. Assert success and row deleted. Repeat for `PlaylistEvent` using `start_utc_ms`. Insert a `ProgramLogDay` with `range_start = None`. Attempt reschedule. Assert rejection.

## Failure Semantics

**Operator fault** if the system permits rescheduling a past or currently-airing artifact — the temporal guard is miscalculated or missing.

## Required Tests

- `pkg/core/tests/contracts/scheduling/test_inv_reschedule_future_guard.py`

## Enforcement Evidence

TODO
