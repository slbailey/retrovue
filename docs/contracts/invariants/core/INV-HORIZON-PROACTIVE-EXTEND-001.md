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

`LAW-CLOCK` — time authority drives scheduling decisions, not downstream demand.

## Required Tests

- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-001: advance clock past threshold, verify extension with REASON_TIME_THRESHOLD)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-002: ChannelManager.get_current_block() does not trigger extension; pipeline call count unchanged)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-003: viewer tune-in event does not trigger extension)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-004: BlockCompleted event does not trigger extension)
- `pkg/core/tests/contracts/test_inv_horizon_proactive_extend.py` (THPE-005: repeated evaluate_once at same clock value produces no duplicate extension)
- All tests use `DeterministicClock` via `contract_clock` fixture. No real-time waits. Extension trigger is observable via `publish_reason_code` on recorded extension events.

## Enforcement Evidence

TODO
