# INV-PLAYLIST-GRID-ALIGNMENT-001 — TransmissionLogEntry boundaries must align to the channel grid

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`

## Purpose

Ensures TransmissionLogEntries carry forward the grid alignment guarantee from ResolvedScheduleDay. Off-grid TransmissionLog boundaries produce off-grid ExecutionEntry fences at the next derivation step, cascading a `LAW-GRID` violation into the runtime layer silently. This invariant is the TransmissionLog-layer checkpoint in the grid integrity cascade.

## Guarantee

All TransmissionLogEntry `start_time` and `end_time` values must align to the channel's valid grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`).

The one permitted exception is the **origin** time of a carry-in entry: a longform asset carrying in from a prior broadcast day may begin at its original play position (which may be non-grid). Its end time, however, must still align to a grid boundary.

## Preconditions

- Channel grid configuration is defined.
- The entry is not a carry-in origin (or if it is, only its start time is exempt, not its end time).

## Observability

At TransmissionLog generation, each entry's `start_time` and `end_time` are validated against the set of valid grid boundaries for the channel. Any boundary not coinciding with a valid grid point (excluding carry-in origin starts) is a violation. The misaligned time and the nearest valid grid boundaries MUST be reported.

## Deterministic Testability

Generate a TransmissionLogEntry with `start_time=18:15` against a 30-minute grid. Assert validation raises a grid-alignment fault. Generate a carry-in entry with `start_time=23:47` (non-grid, origin of a cross-midnight longform) and `end_time=00:30` (grid-aligned). Assert the carry-in start is accepted and the grid-aligned end passes. No real-time waits required.

## Failure Semantics

**Planning fault.** Off-grid TransmissionLog boundaries indicate that upstream zone or ResolvedScheduleDay grid alignment (enforced by `INV-PLAN-GRID-ALIGNMENT-001` and `INV-SCHEDULEDAY-NO-GAPS-001`) was bypassed or failed. The TransmissionLog layer is a secondary enforcement checkpoint.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (PLAYLIST-GRID-001, PLAYLIST-GRID-002, PLAYLIST-GRID-003)

## Enforcement Evidence

**Enforcement function:**
- `validate_transmission_log_grid_alignment(log, grid_block_minutes)` in `pkg/core/src/retrovue/runtime/transmission_log_validator.py` — For each entry, checks `start_utc_ms % (grid_block_minutes * 60_000) == 0` and `end_utc_ms % (grid_block_minutes * 60_000) == 0`. On violation: raises `ValueError` with tag `INV-PLAYLIST-GRID-ALIGNMENT-001-VIOLATED`, the misaligned value, and nearest valid grid boundaries (floor and ceil). Empty entry lists pass trivially.

**Tests:**
- PLAYLIST-GRID-001 (`test_inv_playlist_grid_alignment_001_reject_off_grid`): Entry at 18:15 on 30-min grid rejected; fault identifies misaligned boundary.
- PLAYLIST-GRID-002 (`test_inv_playlist_grid_alignment_001_accept_pds_rollover`): Entry spanning [05:30, 06:30] crossing `programming_day_start=06:00` accepted — both boundaries grid-aligned.
- PLAYLIST-GRID-003 (`test_inv_playlist_grid_alignment_001_accept_cross_midnight`): Two adjacent entries meeting at midnight accepted — no micro-gap, both boundaries grid-aligned.

**Carry-in exception:** Deferred. `TransmissionLogEntry` has no `carry_in` flag yet. The basic grid check covers the three test matrix cases. Carry-in handling will be added when the carry-in system is built.
