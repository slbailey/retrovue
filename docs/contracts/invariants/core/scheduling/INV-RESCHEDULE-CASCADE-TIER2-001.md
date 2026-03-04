# INV-RESCHEDULE-CASCADE-TIER2-001 — Tier 1 reschedule cascade-deletes future derived Tier 2 rows

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-IMMUTABILITY`

## Purpose

`LAW-DERIVATION` requires that every artifact traces to its source. Tier 2 `PlaylistEvent` rows are derived from Tier 1 `ProgramLogDay`. If a Tier 1 row is deleted for regeneration but its derived Tier 2 rows survive, the derivation chain is broken — Tier 2 rows reference a source that no longer exists. Serving orphaned Tier 2 data violates `LAW-DERIVATION`. Deleting past Tier 2 rows (historical record) violates `LAW-IMMUTABILITY`.

## Guarantee

When a Tier 1 `ProgramLogDay` row is deleted via reschedule, all Tier 2 `PlaylistEvent` rows matching `(channel_slug = ProgramLogDay.channel_id, broadcast_day = ProgramLogDay.broadcast_day)` with `start_utc_ms > now_utc_ms` MUST be deleted atomically in the same database transaction.

Tier 2 rows whose `start_utc_ms <= now_utc_ms` (past or currently airing) MUST NOT be deleted.

## Preconditions

- The Tier 1 row passes the future guard (`INV-RESCHEDULE-FUTURE-GUARD-001`).
- The database session supports transactional atomicity.

## Observability

The cascade deletion count MUST be reported to the operator. A Tier 1 reschedule that completes without cascade-deleting reachable future Tier 2 rows is a derivation fault.

## Deterministic Testability

Insert a `ProgramLogDay` with `range_start = now + 1h`. Insert 5 `PlaylistEvent` rows for the same `(channel_slug, broadcast_day)`: 2 with `start_utc_ms <= now_utc_ms`, 3 with `start_utc_ms > now_utc_ms`. Reschedule the `ProgramLogDay`. Assert: `ProgramLogDay` deleted, 3 future `PlaylistEvent` rows deleted, 2 past `PlaylistEvent` rows preserved.

## Failure Semantics

**Planning fault** if future Tier 2 rows survive the Tier 1 deletion (orphaned derivation chain). **Operator fault** if past Tier 2 rows are cascade-deleted (historical record destruction).

## Required Tests

- `pkg/core/tests/contracts/scheduling/test_inv_reschedule_cascade_tier2.py`

## Enforcement Evidence

TODO
