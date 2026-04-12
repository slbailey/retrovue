# INV-EPG-HORIZON-COVERAGE-001 — EPG serves the full compiled horizon

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-LIVENESS`

## Purpose

EPG coverage MUST match the scheduler daemon's compiled horizon. If the scheduler has compiled a broadcast day, the EPG MUST serve that day's listings. A viewer querying EPG for a date within `[now, now + HORIZON_DAYS]` and receiving no results despite a healthy scheduler indicates a derivation gap between compilation and the EPG read path, violating `LAW-DERIVATION`. Continuous EPG availability within the horizon upholds `LAW-LIVENESS` at the presentation layer.

## Guarantee

For any date within `[now, now + HORIZON_DAYS]`, `get_horizon_epg()` MUST return a non-empty EPG result if the scheduler daemon has compiled that date. For dates beyond the compiled horizon, the method MUST return an empty list (not an error or None). The EPG read path MUST NOT trigger schedule compilation — compilation is the scheduler daemon's exclusive responsibility (`INV-SCHEDULE-PREWARM-001`).

## Preconditions

- The scheduler daemon is healthy and has compiled at least `[now, now + HORIZON_DAYS]`.
- A `DslScheduleService` instance exists with compiled blocks in memory.

## Observability

Query EPG for each date in `[now, now + HORIZON_DAYS]`. If any date returns empty despite the scheduler daemon having compiled it, the invariant is violated. Log structured events when the EPG falls back to in-memory blocks instead of DB.

## Deterministic Testability

Create a `DslScheduleService` with pre-populated `_blocks` and `_compiled_days` covering a known horizon. Mock the DB to return no `ScheduleRevision` data. Verify `get_horizon_epg()` returns EPG entries derived from in-memory blocks. Verify dates beyond the horizon return an empty list. No real-time waits required.

## Failure Semantics

**Planning fault.** Empty EPG for a compiled date means the derivation pipeline from compiled blocks to EPG entries is broken or the scheduler daemon failed to compile the expected horizon.

## Required Tests

- `server/tests/contracts/epg/test_inv_epg_horizon_coverage_001.py`

## Enforcement Evidence

| Test ID | Test Method | Tier | Status |
|---------|------------|------|--------|
| TL-EPG-HC-001 | `test_compiled_day_returns_epg_from_in_memory_blocks` | 2 | PASS |
| TL-EPG-HC-002 | `test_beyond_horizon_returns_empty_list` | 2 | PASS |
| TL-EPG-HC-003 | `test_within_horizon_no_compiled_blocks_returns_empty` | 2 | PASS |
| TL-EPG-HC-004 | `test_db_data_preferred_over_in_memory` | 2 | PASS |
| TL-EPG-HC-005 | `test_no_compilation_triggered` | 2 | PASS |
| TL-EPG-HC-006 | `test_horizon_extends_as_daemon_compiles` | 3 | PASS |
