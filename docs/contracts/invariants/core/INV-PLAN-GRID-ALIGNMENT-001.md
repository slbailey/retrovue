# INV-PLAN-GRID-ALIGNMENT-001 — All zone boundaries must align to the channel grid

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`

## Purpose

Ensures that ScheduleDay generation produces grid-aligned slot times. A zone with an off-grid boundary propagates a misaligned time into ScheduleDay, Playlist, and PlaylogEvent — cascading a `LAW-GRID` violation through the entire derivation chain.

## Guarantee

All zone `start_time` and `end_time` values must coincide with a valid grid boundary for the owning channel, as defined by `grid_block_minutes`, `block_start_offsets_minutes`, and `programming_day_start`.

## Preconditions

- Channel grid configuration is defined (`grid_block_minutes` and `block_start_offsets_minutes` are set).
- Boundary validation is performed at zone creation, zone modification, and ScheduleDay generation.

## Observability

At zone save, compute the set of valid grid boundaries for the channel. Assert `start_time` and `end_time` each fall on a boundary. Report the misaligned time and the nearest valid boundaries on violation.

## Deterministic Testability

Given a channel with `grid_block_minutes=30`, construct a zone with `start_time=18:15` (off-grid). Assert validation raises a grid-alignment fault identifying 18:15 as invalid and reporting 18:00 and 18:30 as valid alternatives. No real-time waits required.

## Failure Semantics

**Planning fault.** The operator specified zone boundaries that do not align to the channel grid. System must reject the zone configuration.

## Required Tests

- `pkg/core/tests/contracts/test_inv_plan_grid_alignment.py`

## Enforcement Evidence

TODO
