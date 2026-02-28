# INV-BROADCASTDAY-PROJECTION-TRACEABLE-001 — Broadcast-day reporting rows must derive from runtime artifacts by interval intersection

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-RUNTIME-AUTHORITY`

## Purpose

Protects the derivation chain from contamination by reporting-layer artifacts that acquire independent authority. Every broadcast-day row is a view projected over committed runtime records. Without this invariant, a reporting layer could create rows with no runtime backing — orphaned projections that assert authority over time windows without `LAW-RUNTIME-AUTHORITY` provenance. Such orphaned rows violate `LAW-DERIVATION` by severing the required traceability from the runtime artifact back to its upstream source.

## Guarantee

Every broadcast-day reporting row or projection that intersects a ExecutionEntry or AsRun record MUST be derived by interval intersection only.

Each such row MUST reference the underlying ExecutionEntry or AsRun record from which it was derived.

A broadcast-day reporting row MUST NOT create independent authority over any time interval.

A broadcast-day reporting row MUST NOT exist without a corresponding committed runtime artifact (ExecutionEntry or AsRun record) from which it was projected.

## Preconditions

- A broadcast-day reporting request covers a window that includes at least one committed ExecutionEntry or AsRun record.

## Observability

The reporting layer MUST record the source ExecutionEntry ID or AsRun record ID for every row it emits. Any row with a null or absent source record reference is a violation. Any row whose covered interval is not a subset of the referenced source record's interval is a violation. Violation: log the reporting window, the offending row's interval, and the absent or mismatched source record reference.

## Deterministic Testability

Create a ExecutionEntry with `start_utc = DAY_BOUNDARY - 1h` and `end_utc = DAY_BOUNDARY + 1h`. Generate broadcast-day reports for the day ending at `DAY_BOUNDARY` and the day beginning at `DAY_BOUNDARY`. Assert: (a) the row for the ending day covering [DAY_BOUNDARY - 1h, DAY_BOUNDARY] references the original ExecutionEntry ID; (b) the row for the beginning day covering [DAY_BOUNDARY, DAY_BOUNDARY + 1h] references the same ExecutionEntry ID; (c) no row is emitted with a null or absent source record reference.

Invalid scenario: the Tuesday 06:00–07:00 report row is created with no source ExecutionEntry ID — this is a violation of this invariant.

## Failure Semantics

**Planning fault** if the reporting layer generated a row without deriving it from a committed runtime artifact. **Planning fault** if the row's interval is not a subset of the referenced source record's interval.

## Required Tests

- `pkg/core/tests/contracts/test_inv_broadcastday_projection_traceable.py`

## Enforcement Evidence

- **Interval-intersection derivation:** Broadcast-day reporting rows are projected by interval intersection over committed runtime artifacts (`ExecutionEntry` / `AsRun`); they do not create independent authority over any time interval.
- **Source reference required:** Each reporting row must reference the underlying `ExecutionEntry` or `AsRun` record ID from which it was derived — a null or absent source reference is a violation.
- **Cross-day safe:** `TestInvScheduledaySeamNoOverlap001` in `test_scheduling_constitution.py` validates that broadcast-day boundary handling does not produce overlapping or orphaned records — the same integrity applies to reporting projections.
- Dedicated contract test (`test_inv_broadcastday_projection_traceable.py`) is referenced in `## Required Tests` but not yet implemented in the current tree.
