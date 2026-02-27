# INV-HORIZON-NEXT-BLOCK-READY-001

## Behavioral Guarantee

At the fence time of any block in the execution horizon, the immediately subsequent block MUST already be present in `ExecutionWindowStore`. Where `required_lookahead_blocks > 1`, the required number of subsequent blocks MUST all be present before the fence. This is the **fence readiness guarantee**: per-boundary block availability for automation. This invariant does not govern aggregate horizon depth (see `INV-HORIZON-EXECUTION-MIN-001`).

## Authority Model

Schedule Manager owns block readiness at fence boundaries. Fence time of block N is defined as `block_N.end_utc_ms`. `required_lookahead_blocks` is a deployment-configured integer (minimum 1, default 1).

## Boundary / Constraint

Let `F_N = block_N.end_utc_ms` (fence time of block N).

At time `F_N`, `ExecutionWindowStore` MUST contain entries for blocks N+1 through N+`required_lookahead_blocks`, each satisfying:

- `block_{N+k}.start_utc_ms` and `block_{N+k}.end_utc_ms` are populated.
- `block_{N+k}.segments` is non-empty.

This MUST hold for every block N whose `end_utc_ms > TimeAuthority.now()` (i.e. every block whose fence has not yet passed).

## Violation

Any of the following at fence time `F_N`:

- `ExecutionWindowStore.get_entry_at(F_N)` returns `None` (block N+1 absent).
- Fewer than `required_lookahead_blocks` subsequent blocks are present.
- A subsequent block is present but has empty `segments`.

MUST be logged as planning fault with fields: `fence_block_id`, `fence_utc_ms = F_N`, `missing_block_index`, `required_lookahead_blocks`.

## Derives From

`LAW-TIMELINE` — schedule defines boundary timing; execution MUST NOT outrun the plan.

## Required Tests

- `pkg/core/tests/contracts/test_inv_horizon_next_block_ready.py` (THNB-001: N+1 present at every fence across 12 consecutive blocks)
- `pkg/core/tests/contracts/test_inv_horizon_next_block_ready.py` (THNB-002: N+1 and N+2 present when required_lookahead_blocks=2)
- `pkg/core/tests/contracts/test_inv_horizon_next_block_ready.py` (THNB-003: missing N+1 at fence detected as planning fault with correct fields)
- `pkg/core/tests/contracts/test_inv_horizon_next_block_ready.py` (THNB-004: fence at programming day crossover has N+1 from next day)
- All tests use `DeterministicClock` via `contract_clock` fixture. No real-time waits. Clock is advanced to exact fence times. Observable state: `ExecutionWindowStore` entry presence and `segments` population.

## Enforcement Evidence

TODO
