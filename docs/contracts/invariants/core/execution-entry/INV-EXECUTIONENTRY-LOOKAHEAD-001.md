# INV-EXECUTIONENTRY-LOOKAHEAD-001 — ExecutionEntry window MUST extend at least min_execution_horizon_ms ahead of current time

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-LIVENESS`

## Purpose

Ensures ChannelManager always has a populated execution window to present to AIR. If the ExecutionEntry window falls behind real time, ChannelManager has no constitutionally-authorized content, forcing AIR to stall or produce unplanned filler — violating `LAW-LIVENESS`.

## Guarantee

At all times while a channel has at least one active viewer, the ExecutionEntry sequence MUST extend at least `min_execution_horizon_ms` ahead of the current MasterClock time, with no temporal gaps in that window. `min_execution_horizon_ms` is a deployment-configured value injected into HorizonManager at initialization (equivalently expressed as `min_execution_hours`).

This guarantee is subsumed by `INV-HORIZON-EXECUTION-MIN-001`, which enforces `execution_horizon_end - TimeAuthority.now() >= execution_horizon_min_duration_ms` at every `HorizonManager.evaluate_once()` exit point.

## Preconditions

- Channel has at least one active viewer (a live playout session exists).
- MasterClock is established for the session.
- `min_execution_hours` is declared as a deployment-configurable value, injected into HorizonManager at initialization.

## Observability

HorizonManager MUST continuously monitor the distance between current MasterClock time and the `end_utc_ms` of the last ExecutionEntry. When this distance falls below `min_execution_horizon_ms`, the rolling window MUST be extended. If extension fails, a lookahead violation MUST be logged with the channel ID and the depth shortfall. Observable via `HorizonHealthReport.execution_compliant`.

## Deterministic Testability

Using a deterministic clock: construct an ExecutionEntry sequence extending to time T. Advance the clock so remaining depth falls below `min_execution_horizon_ms`. Assert HorizonManager detects the shortfall and triggers extension. Assert that after extension the window again extends at least `min_execution_horizon_ms`. No real-time waits required.

## Failure Semantics

**Runtime fault.** HorizonManager failed to extend the rolling window. Root cause may be upstream (`INV-SCHEDULEDAY-LEAD-TIME-001` violated) or a HorizonManager logic failure.

## Required Tests

- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-001: depth meets minimum after initialization)
- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-002: depth maintained across 48-block 24-hour walk)
- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-003: pipeline failure produces observable depth deficit and planning fault)
- `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` (THEM-004: depth maintained across programming day boundary)

## Enforcement Evidence

- **Subsumed by:** `INV-HORIZON-EXECUTION-MIN-001`. No dedicated guard exists for this invariant. The macro depth guarantee in `INV-HORIZON-EXECUTION-MIN-001` enforces the identical constraint with `min_execution_hours` as the configurable minimum.
- **Guard location:** `HorizonManager.evaluate_once()` in `pkg/core/src/retrovue/runtime/horizon_manager.py`. After computing `exec_depth_h`, if `exec_depth_h < self._min_execution_hours`, calls `_extend_execution()` which loops calling `extend_execution_day()` until `execution_window_end_utc_ms - now_ms >= min_execution_hours * 3_600_000`.
- **Failure handling:** `_extend_execution()` wraps each `extend_execution_day()` call in try/except. On pipeline exception, records an `ExtensionAttempt(success=False, error_code=...)`. The deficit is observable via `HorizonHealthReport.execution_compliant == False`.
- **Observability:** `HorizonHealthReport.execution_compliant` (bool), `extension_attempt_count` (int), `extension_success_count` (int), `extension_attempt_log` (list of `ExtensionAttempt`).
- **Test file:** `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` — THEM-001 (depth meets minimum after init), THEM-002 (depth maintained across 24h walk), THEM-003 (pipeline failure produces deficit), THEM-004 (depth survives programming day boundary).
