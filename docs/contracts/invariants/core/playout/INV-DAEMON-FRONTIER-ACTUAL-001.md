# INV-DAEMON-FRONTIER-ACTUAL-001

## Behavioral Guarantee

`PlaylistBuilderDaemon._farthest_end_utc_ms` reflects the actual playlog plan frontier in the database at the start of each `evaluate_once()` cycle. Deleted PlaylistEvent rows cause the frontier to regress, and the daemon detects the gap on the next tick.

## Authority Model

`PlaylistBuilderDaemon` owns `_farthest_end_utc_ms`. The value is derived from `_get_frontier_utc_ms()` which queries the database.

## Boundary / Constraint

- `evaluate_once()` MUST assign `_farthest_end_utc_ms = frontier_ms` (direct assignment, not monotonic max).
- After PlaylistEvent rows are deleted mid-window, the next `evaluate_once()` cycle MUST detect reduced depth and trigger `_extend_to_target()`.
- `_extend_to_target()` cursor MUST start from the actual frontier, not a stale high-water mark.

## Violation

- Using `_farthest_end_utc_ms = max(_farthest_end_utc_ms, frontier_ms)` in the evaluate-once frontier sync.
- Reporting healthy horizon depth after rows are deleted.
- Starting `_extend_to_target()` scan past a gap left by deleted rows.

## Derives From

LAW-TIMELINE

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_daemon_frontier_actual.py`

## Enforcement Evidence

TODO
