# INV-HORIZON-PROACTIVE-EXTEND-001

## Behavioral Guarantee

Horizon extension is triggered exclusively by authoritative time crossing a defined threshold. Schedule Manager evaluates extension eligibility when `TimeAuthority.now()` exceeds `execution_horizon_end - extension_trigger_margin`. No code path reachable from Channel Manager, viewer lifecycle, or block consumption may invoke the extension pipeline.

## Authority Model

Schedule Manager owns horizon extension. `TimeAuthority.now()` is the sole input that determines when extension occurs. Every extension event MUST carry a `publish_reason_code` identifying the trigger.

## Boundary / Constraint

Allowed extension triggers (exhaustive):

- `REASON_TIME_THRESHOLD`: `TimeAuthority.now() >= execution_horizon_end - extension_trigger_margin`
- `REASON_OPERATOR_OVERRIDE`: explicit operator command with override credentials

Forbidden extension triggers (any invocation from these paths is a violation):

- `ChannelManager.get_current_block()`
- `ChannelManager.get_next_block()`
- `ExecutionWindowStore.get_entry_at()`
- Viewer tune-in or tune-out RPC handlers
- `BlockCompleted` event handlers
- Any consumer read path

Extension MUST NOT execute more than once per threshold crossing at the same `TimeAuthority.now()` value. The `publish_reason_code` MUST be recorded on every extension event and MUST be one of the allowed values above.

## Violation

Any of the following:

- Extension event with `publish_reason_code` not in allowed set.
- Extension event reachable via call stack originating from a forbidden trigger path.
- Duplicate extension for the same threshold crossing without intervening clock advancement.

MUST be logged as planning fault with the observed `publish_reason_code` and call-site identifier.

## Derives From

`LAW-RUNTIME-AUTHORITY` — time authority drives scheduling decisions, not downstream demand.
`LAW-DERIVATION` — every extension event carries an auditable `publish_reason_code`.

## Required Tests

- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-001: advance clock past threshold, verify extension with REASON_TIME_THRESHOLD)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-002: ChannelManager.get_current_block() does not trigger extension; pipeline call count unchanged)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-003: viewer tune-in event does not trigger extension)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-004: BlockCompleted event does not trigger extension)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-005: repeated evaluate_once at same clock value produces no duplicate extension)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (TPX-001: no extension when remaining > threshold)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (TPX-002: extension when crossing threshold, depth increased)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (TPX-003: fires before min_execution_hours violation)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (TPX-004: pipeline failure during proactive extend logged, store not corrupted)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (TPX-005: idempotent per tick — second evaluate at same clock produces no duplicate)
- All tests use `DeterministicClock` via `contract_clock` fixture. No real-time waits. Extension trigger is observable via `publish_reason_code` on recorded extension events.

## Enforcement Evidence

- **Guard location:** `HorizonManager._check_proactive_extend()` called from `evaluate_once()` in `pkg/core/src/retrovue/runtime/horizon_manager.py`. Runs after execution depth, next-block readiness, and seam contiguity checks.
- **Watermark condition:** `remaining_ms = execution_window_end_utc_ms - now_ms`. If `remaining_ms <= proactive_extend_threshold_ms` and `proactive_extend_threshold_ms > 0`, a single extension attempt is made via `extend_execution_day()`.
- **Single-attempt-per-tick:** At most one proactive extension attempt per `evaluate_once()` call. After extension succeeds, `remaining` exceeds the threshold, so the next tick will not re-trigger unless clock advances further.
- **Interaction with EXECUTION-MIN:** Proactive extension fires independently of `_extend_execution()`. The threshold can be set above `min_execution_hours` to trigger extension before the hard minimum is breached.
- **Interaction with LOCKED-IMMUTABLE:** Proactive extension uses `publish_atomic_replace()` with `reason_code="REASON_TIME_THRESHOLD"`. The publish range covers only future entries beyond the current window end, so locked-window constraints are not violated.
- **Pipeline failure:** Caught, logged as `ExtensionAttempt(success=False, error_code=...)`. `proactive_extension_triggered` is still set to `True` (the attempt was made).
- **Observability:** `HorizonHealthReport.proactive_extension_triggered` (bool), `HorizonManager.proactive_extension_triggered` property, `extension_attempt_log` entries with `reason_code="REASON_TIME_THRESHOLD"`.
- **Test file:** `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` — TPX-001 (no extension above threshold), TPX-002 (extension when crossing), TPX-003 (fires before min violation), TPX-004 (pipeline failure), TPX-005 (idempotent per tick).
