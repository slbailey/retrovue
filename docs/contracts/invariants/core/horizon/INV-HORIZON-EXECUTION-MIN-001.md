# INV-HORIZON-EXECUTION-MIN-001

## Behavioral Guarantee

Schedule Manager maintains execution-ready data (Transmission Log entries) such that `execution_horizon_end - TimeAuthority.now() >= execution_horizon_min_duration_ms` at every evaluation point. This is the **macro depth guarantee**: the total coverage window ahead of authoritative time meets a configured minimum. This invariant does not govern per-fence block readiness (see `INV-HORIZON-NEXT-BLOCK-READY-001`).

## Authority Model

Schedule Manager owns execution horizon depth. `execution_horizon_min_duration_ms` is a deployment-configured value. `execution_horizon_end` is the `end_utc_ms` of the last Transmission Log entry in the execution store.

## Boundary / Constraint

Let `T = TimeAuthority.now()` in milliseconds UTC. Let `E = execution_horizon_end` (the `end_utc_ms` of the farthest entry in `ExecutionWindowStore`).

`E - T >= execution_horizon_min_duration_ms` MUST hold at every `HorizonManager.evaluate_once()` exit point where the planning pipeline returned success.

When the planning pipeline returns failure, `E - T` may fall below `execution_horizon_min_duration_ms`. This deficit MUST be reported as a planning fault with the observed depth `E - T` and the required minimum.

## Violation

`E - T < execution_horizon_min_duration_ms` after a successful `evaluate_once()` cycle. MUST be logged as planning fault with fields: `observed_depth_ms = E - T`, `required_min_ms = execution_horizon_min_duration_ms`, `T`, `E`.

## Required Tests

- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-001: depth meets minimum after initialization)
- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-002: depth maintained across 48-block 24-hour walk)
- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-003: pipeline failure produces observable depth deficit and planning fault)
- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-004: depth maintained across programming day boundary at PROG_DAY_START_HOUR)
- All tests use `DeterministicClock` via `contract_clock` fixture. No real-time waits. Observable state: `execution_horizon_end`, `TimeAuthority.now()`, `HorizonHealthReport.execution_compliant`.

## Enforcement Evidence

- **Guard location:** `HorizonManager.evaluate_once()` in `pkg/core/src/retrovue/runtime/horizon_manager.py`. After computing `exec_depth_h`, if `exec_depth_h < self._min_execution_hours`, calls `_extend_execution()` which loops calling `extend_execution_day()` until `execution_window_end_utc_ms - now_ms >= min_execution_hours * 3_600_000`.
- **Depth check:** `exec_depth_h < self._min_execution_hours` (line in `evaluate_once()`) triggers the extension loop in `_extend_execution()`.
- **Failure handling:** `_extend_execution()` wraps each `extend_execution_day()` call in try/except. On pipeline exception, records an `ExtensionAttempt(success=False, error_code=...)` and breaks the extension loop. The deficit is then observable via `HorizonHealthReport.execution_compliant == False`.
- **Observability:** `HorizonHealthReport.execution_compliant` (bool), `extension_attempt_count` (int), `extension_success_count` (int), `extension_attempt_log` (list of `ExtensionAttempt` with `success`, `error_code`, `reason_code`, `triggered_by` fields).
- **Test file:** `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` — THEM-001 (depth meets minimum after init), THEM-002 (depth maintained across 24h walk), THEM-003 (pipeline failure produces deficit), THEM-004 (depth survives programming day boundary).
