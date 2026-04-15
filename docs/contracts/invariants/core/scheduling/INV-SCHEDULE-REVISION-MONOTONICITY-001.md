# INV-SCHEDULE-REVISION-MONOTONICITY-001

## Behavioral Guarantee

For any channel, once a reader observes revision `R_new` as `active`, the reader MUST NOT subsequently observe a superseded revision `R_old` as `active` for any editorial query at an instant `t ≥ t_obs`, where `t_obs` is the observation time of that active transition. Cache and read paths MUST preserve monotonic visibility of schedule authority relative to revision identity.

## Authority Model

Readers (EPG, playlog materialization, playout plan builders, schedule caches) and the runtime cache invalidation path own this guarantee jointly with the persistence layer that performs atomic supersession.

## Boundary / Constraint

Readers MUST NOT treat cached `revision_id` (or equivalent) as valid without validating it against the current active revision for that channel. Any cache keyed by `(channel_id, absolute_time)` alone MUST NOT be used for editorial answers without a `revision_id` or monotonic `revision_seq` / generation stamp tied to the active head. Runtime MUST invalidate or version all timeline-derived caches on successful schedule publish so no stale future tail from a superseded revision remains visible after `R_new` is observed active.

## Violation

A cache consistency violation: a reader serves future editorial schedule from `R_old` after any path has already observed `R_new` as active for the same channel. Observable as EPG, playlog, or playout disagreeing with persisted `ScheduleItem` rows under `R_new` for pending time, or as `active` revision identity regressing in a single process without a new publish. Remediation MUST force invalidation of affected timeline caches and re-read canonical schedule from `R_active` before serving editorial answers for pending time.

## Derives From

`LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY` (requires at most one active `ScheduleRevision` per channel; see `docs/contracts/scheduling/SCHEDULE-PERSISTENCE-DESIGN-v1.0.md`).

## Required Tests

- `server/tests/contracts/scheduling/test_inv_schedule_revision_monotonicity_001.py`
- `server/tests/contracts/scheduling/test_scheduling_invariants_v1.py` (Group 10 — revision monotonicity)

## Enforcement Evidence

TODO
