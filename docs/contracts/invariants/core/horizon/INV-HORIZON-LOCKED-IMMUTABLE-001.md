# INV-HORIZON-LOCKED-IMMUTABLE-001

## Behavioral Guarantee

Execution data within the locked window is immutable. The locked window is defined as `[TimeAuthority.now(), execution_horizon_end)` — all entries in `ExecutionWindowStore` whose time range overlaps this interval. No in-place mutation of block fields or segment contents is permitted within the locked window. Modification occurs only via atomic replacement per `INV-HORIZON-ATOMIC-PUBLISH-001`, triggered by explicit operator override carrying `publish_reason_code = REASON_OPERATOR_OVERRIDE`.

## Authority Model

Schedule Manager owns lock enforcement. The locked window boundary advances with `TimeAuthority.now()`. `ExecutionWindowStore` rejects writes to the locked window unless `operator_override = True`.

## Boundary / Constraint

Let `T = TimeAuthority.now()` in milliseconds UTC. Let `E = execution_horizon_end`.

An entry is **locked** if `entry.end_utc_ms > T` and `entry.start_utc_ms < E`.

For any locked entry:

- `ExecutionWindowStore` MUST reject write, update, or delete operations unless `operator_override = True` is set on the request.
- When `operator_override = True`, the replacement MUST be atomic per `INV-HORIZON-ATOMIC-PUBLISH-001` and MUST assign a new `generation_id`.
- Entries where `entry.end_utc_ms <= T` are **past** (historical, immutable by separate as-run contract, not governed here).
- Entries where `entry.start_utc_ms >= E` are in the **flexible future** and accept normal writes without override.

## Violation

Any of the following:

- Write to a locked entry accepted without `operator_override = True`.
- In-place field mutation of a locked entry (segment content, asset_uri, duration, timestamps) by any automated process.
- Override replacement that does not assign a new `generation_id`.

MUST be logged as planning fault with fields: `mutated_block_id`, `block_start_utc_ms`, `lock_boundary_T`, `operator_override` (true/false), `mutation_source` (caller identifier).

## Required Tests

- `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` (THLI-001: write to locked entry without override rejected)
- `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` (THLI-002: automated process write to locked entry rejected)
- `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` (THLI-003: operator override replaces atomically with new generation_id)
- `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` (THLI-004: entry in flexible future accepts write without override)
- `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` (THLI-005: clock advance moves lock boundary; previously-future entry becomes locked and rejects mutation)
- All tests use `DeterministicClock` via `contract_clock` fixture. No real-time waits. Observable state: write acceptance/rejection, `operator_override` flag, `generation_id` on replaced entries, lock boundary `T` from `TimeAuthority.now()`.

## Enforcement Evidence

- **Guard location:** `ExecutionWindowStore.publish_atomic_replace()` in `pkg/core/src/retrovue/runtime/execution_window_store.py`. Before the generation-monotonicity check, if `clock_fn` and `locked_window_ms` are configured and `operator_override=False`, the method computes the locked window `[now, now + locked_window_ms)` and checks half-open overlap with `[range_start_ms, range_end_ms)`. On overlap, returns `PublishResult(ok=False, error_code="INV-HORIZON-LOCKED-IMMUTABLE-001-VIOLATED: locked window")`.
- **Helper:** `ExecutionWindowStore._locked_window_end_ms(now_ms, locked_window_ms) -> int` — pure static computation of the locked window upper bound.
- **Configuration:** `clock_fn: Callable[[], int]` and `locked_window_ms: int` are keyword-only constructor parameters. Deployment-configurable; fixture-injected in tests.
- **Override path:** `operator_override=True` bypasses the locked-window guard, allowing atomic replacement per `INV-HORIZON-ATOMIC-PUBLISH-001`.
- **Test file:** `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` — THLI-001 through THLI-005.
