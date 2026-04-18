# INV-CM-SUPPLY-RESOLUTION-SOLE-OWNER-001

## Behavioral Guarantee

Per-channel block resolution against `ExecutionRuntimeReader` and the associated failure-surfacing path (logging the failure, invoking the `on_producer_failure` callback) MUST be owned exclusively by a `SupplyController` instance. No other runtime-path component may call `get_current_execution_block` / `get_next_execution_block` for a channel whose supply is managed by a `SupplyController`, nor may any other component dispatch the producer-failure callback.

## Authority Model

`SupplyController` holds the injected `ExecutionRuntimeReader` reference and the injected `on_failure` callback for one channel. It is the sole caller of the reader's block-resolution methods and the sole dispatcher of the failure callback. `BlockPlanProducer` delegates startup-block resolution, next-block resolution, and failure surfacing to its `SupplyController`.

## Boundary / Constraint

- `SupplyController` MUST expose `resolve_current(now_utc_ms)`, `resolve_next(after_utc_ms)`, and `fail(reason)` methods in addition to the Phase 3A surface.
- `BlockPlanProducer` MUST NOT call `ExecutionRuntimeReader.get_current_execution_block` or `get_next_execution_block` directly.
- `BlockPlanProducer` MUST NOT hold a `_resolve_next_block` method after Phase 3B.
- Failure surfacing (log + callback dispatch) MUST go through `SupplyController.fail`; `BlockPlanProducer._fail` (if retained) MUST be a thin wrapper that updates `ProducerStatus` and delegates.

## Violation

Any block-resolution call (`get_current_execution_block` / `get_next_execution_block`) inside `BlockPlanProducer`. Any code path that invokes the `on_producer_failure` callback from inside BPP rather than routing through `SupplyController.fail`.

## Scope

This invariant governs the **BPP → SupplyController** migration boundary (ADR-004 Phase 3B). Other runtime-path components that legitimately read the execution reader (`ChannelManager`, `ProgramDirector._validate_execution_ready`, the `ExecutionRuntimeReader` Protocol declaration itself) are out of scope for this invariant and governed by their own migration contracts.

## Derives From

`LAW-MIGRATION-SAFETY`, `LAW-RUNTIME-AUTHORITY`, `INV-CM-SUPPLY-STATE-SOLE-WRITER-001`

## Required Tests

- `server/tests/contracts/runtime/test_inv_cm_supply_resolution_ownership.py` — SupplyController exposes `resolve_current`, `resolve_next`, `fail`; BPP contains no `_resolve_next_block` method and no direct `ExecutionRuntimeReader` block-resolution calls.

## Enforcement Evidence

TODO
