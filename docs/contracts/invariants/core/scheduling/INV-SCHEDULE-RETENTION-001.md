# INV-SCHEDULE-RETENTION-001: Schedule Data Lifecycle and Retention

## Status: ACTIVE

## Summary

Schedule cache tables hold only forward-looking data within their defined
horizons. Expired rows are purged automatically on each horizon evaluation
tick. Historical record lives only in as-run logs.

## Motivation

ProgramLogDay (program schedule cache) and PlaylistEvent (playlog plan) are *caches* of
forward-looking schedule data. Without retention enforcement:

1. Old broadcast days accumulate indefinitely in both tables.
2. Pre-`segmented_blocks` program schedule rows can never be updated because
   `_save_compiled_schedule` used `db.merge()` with a fresh UUID, which
   silently failed on the `(channel_id, broadcast_day)` unique constraint
   in the `program_log_days` table.
3. Every startup re-expands stale days from scratch (the slow path).

## Invariant

### Program schedule — ProgramLogDay

- **Retention window**: rows where `broadcast_day >= today - 1 day`.
  This covers the current broadcast day and HORIZON_DAYS (3) forward days.
- **Purge**: rows with `broadcast_day < today - 1` are deleted.
- **Trigger**: `_purge_expired_program_schedule()` called from `_maybe_extend_horizon()`.
- **Throttle**: at most once per hour (`_last_program_schedule_purge_utc_ms`).

### Playlog Plan — PlaylistEvent

- **Retention window**: rows where `end_utc_ms > now_ms - 4 hours`.
  This covers the current playback window plus a safety margin.
- **Purge**: rows with `end_utc_ms <= now_ms - 4 hours` are deleted.
- **Trigger**: `_purge_expired_playlog_plan()` called from `evaluate_once()`.
- **Throttle**: at most once per hour (`_last_playlog_plan_purge_utc_ms`).

### Upsert Correctness

`_save_compiled_schedule` MUST correctly update existing rows on the
`(channel_id, broadcast_day)` unique constraint. A query-then-update-or-insert
pattern replaces the broken `db.merge()` with fresh UUID approach.

## Boundaries

- Purge is delete-only. No schedule data is recreated on purge.
- Rebuild requires explicit `retrovue programming rebuild`.
- As-run logs are the permanent historical record — not schedule caches.
- Purge does not affect in-memory block lists (those have their own
  `_prune_old_blocks` logic).

## Verification

- Contract test: `pkg/core/tests/contracts/scheduling/test_inv_schedule_retention_001.py`
- Program schedule purge: deletes rows with `broadcast_day < cutoff`, keeps current/future.
- Playlog Plan purge: deletes rows with `end_utc_ms <= cutoff`, keeps recent.
- Upsert: updates existing row on conflict, does not silently fail.
