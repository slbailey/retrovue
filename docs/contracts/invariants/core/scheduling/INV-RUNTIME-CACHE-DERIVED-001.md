# INV-RUNTIME-CACHE-DERIVED-001 — Runtime cache is derived

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring the in-memory `_blocks` cache is a derived artifact, not an authoritative data source. After a restart, `_blocks` MUST be reconstructable from persisted ScheduleRevision data. Treating a runtime cache as authoritative creates a single point of failure where data loss (process crash) silently corrupts the schedule.

## Guarantee

`_blocks` is a derived in-memory cache. It MUST NOT be treated as authoritative after restart without persisted schedule backing. It MUST be reconstructable from ScheduleRevision data.

## Observability

After a restart, the reconstructed `_blocks` cache MUST produce identical timeline answers to the pre-restart cache for any queried time T within the compiled horizon.

## Deterministic Testability

Build a timeline from ScheduleRevision data. Cache it in `_blocks`. Discard the cache. Rebuild from the same ScheduleRevision data. Every block, boundary, and timing answer MUST be identical between the two caches.

## Failure Semantics

**Runtime fault.** If `_blocks` is treated as authoritative and not rebuilt from ScheduleRevision data on restart, any in-memory corruption or process crash silently alters the running schedule.

## Required Tests

- `server/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

- `TestTimelineSingleAuthority::test_build_initial_uses_load_existing_timeline` — timeline construction uses the persisted data path, not an in-memory shortcut
- `TestTimelineSingleAuthority::test_load_existing_timeline_returns_blocks_and_day_sets` — loaded data fully reconstructs the block cache
