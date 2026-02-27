# INV-PLAN-GRID-ALIGNMENT-001 — All zone boundaries must align to the channel grid

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`

## Purpose

Ensures that ScheduleDay generation produces grid-aligned slot times. A zone with an off-grid boundary propagates a misaligned time into ScheduleDay, Playlist, and ExecutionEntry — cascading a `LAW-GRID` violation through the entire derivation chain.

## Guarantee

All zone `start_time` and `end_time` values MUST be multiples of `grid_block_minutes`. Zone duration (`end_time - start_time`) MUST also be a multiple of `grid_block_minutes`.

## Preconditions

- Channel grid configuration is defined (`grid_block_minutes` is set).
- Boundary validation is performed at zone creation, zone modification, and block assignment validation.

## Observability

At zone save, verify `start_time`, `end_time`, and duration are each divisible by `grid_block_minutes`. Report the misaligned value on violation.

## Deterministic Testability

Given a channel with `grid_block_minutes=30`, construct a zone with `end_time=17:59` (off-grid). Assert validation raises a grid-alignment fault. Repeat for off-grid `start_time` and off-grid duration. No real-time waits required.

## Failure Semantics

**Planning fault.** The operator specified zone boundaries that do not align to the channel grid. System MUST reject the zone configuration.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvPlanGridAlignment001`

## Enforcement Evidence

- `pkg/core/src/retrovue/usecases/zone_coverage_check.py` — `check_grid_alignment()`, `validate_zone_plan_integrity()`
- `pkg/core/src/retrovue/usecases/zone_add.py` — called before `db.commit()`
- `pkg/core/src/retrovue/usecases/zone_update.py` — called before `db.commit()`
- `pkg/core/src/retrovue/core/scheduling/contracts.py` — `validate_block_assignment()` checks block-level grid alignment
- Error tag: `INV-PLAN-GRID-ALIGNMENT-001-VIOLATED`
