# INV-HORIZON-CONTINUOUS-COVERAGE-001

## Behavioral Guarantee

Within `ExecutionWindowStore`, all entries ordered by `start_utc_ms` form a contiguous, non-overlapping sequence. For every adjacent pair of entries, the predecessor's `end_utc_ms` equals the successor's `start_utc_ms` exactly. No gap (predecessor ends before successor starts) and no overlap (predecessor ends after successor starts) exists.

## Authority Model

Schedule Manager owns execution horizon seam integrity. Seam validation runs on every `ExecutionWindowStore` mutation (entry addition, atomic replacement).

## Boundary / Constraint

Let entries E_0, E_1, ..., E_n be all entries in `ExecutionWindowStore` ordered by `start_utc_ms`.

For every adjacent pair `(E_i, E_{i+1})`:

`E_i.end_utc_ms == E_{i+1}.start_utc_ms` MUST hold (integer equality, no tolerance).

Additionally:

- `E_i.end_utc_ms > E_i.start_utc_ms` MUST hold (positive duration).
- No two entries share the same `start_utc_ms`.

## Violation

Any of the following:

- `E_i.end_utc_ms < E_{i+1}.start_utc_ms` (gap of `E_{i+1}.start_utc_ms - E_i.end_utc_ms` ms).
- `E_i.end_utc_ms > E_{i+1}.start_utc_ms` (overlap of `E_i.end_utc_ms - E_{i+1}.start_utc_ms` ms).
- `E_i.end_utc_ms <= E_i.start_utc_ms` (zero or negative duration).

MUST be logged as planning fault with fields: `left_block_id`, `left_end_utc_ms`, `right_block_id`, `right_start_utc_ms`, `delta_ms = right_start_utc_ms - left_end_utc_ms`.

## Required Tests

- `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` (THCC-001: full horizon seam validation, all pairs contiguous)
- `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` (THCC-002: injected 1 ms gap detected with correct delta_ms)
- `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` (THCC-003: injected 1 ms overlap detected with correct delta_ms)
- `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` (THCC-004: seam at extension join validated after horizon extension)
- `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` (THCC-005: 48-step 24-hour walk, zero seam violations)
- All tests use `DeterministicClock` via `contract_clock` fixture. No real-time waits. Observable state: seam validation result with per-pair `delta_ms`.

## Enforcement Evidence

- **Guard location:** `HorizonManager._check_seam_contiguity()` called from `evaluate_once()` in `pkg/core/src/retrovue/runtime/horizon_manager.py`. After execution depth, next-block readiness, and any extension attempts, `_check_seam_contiguity()` runs when an `execution_store` is configured.
- **Seam check:** Retrieves all entries from `ExecutionWindowStore.get_all_entries()` (sorted by `start_utc_ms`). For every adjacent pair `(E_i, E_{i+1})`, computes `delta = E_{i+1}.start_utc_ms - E_i.end_utc_ms`. If `delta != 0`, a `SeamViolation` is recorded with `left_block_id`, `left_end_utc_ms`, `right_block_id`, `right_start_utc_ms`, `delta_ms`.
- **Violation logging:** Each violation is logged at WARNING level with tag `INV-HORIZON-CONTINUOUS-COVERAGE-001-VIOLATED`, including gap/overlap classification and magnitude.
- **Observability:** `HorizonHealthReport.coverage_compliant` (bool), `HorizonManager.coverage_compliant` property, `HorizonManager.seam_violations` (list of `SeamViolation` from most recent evaluation).
- **Test file:** `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` — THCC-001 (contiguous boundaries after init), THCC-002 (1 ms gap detected), THCC-003 (1 ms overlap detected), THCC-004 (contiguity at extension join), THCC-005 (48-step 24h walk zero violations).
