# INV-HORIZON-ATOMIC-PUBLISH-001

## Behavioral Guarantee

Every execution horizon publish assigns a monotonically increasing `generation_id` (integer, starting at 1). All entries within a published time range carry the same `generation_id`. Channel Manager reading any contiguous time range from `ExecutionWindowStore` MUST observe entries from exactly one `generation_id` per original publish range. Partial visibility of an in-progress publish is prohibited.

## Authority Model

Schedule Manager owns `generation_id` assignment. `ExecutionWindowStore` enforces atomic visibility. `generation_id` is monotonically increasing; no reset across session lifetime.

## Boundary / Constraint

Let a publish operation P cover time range `[range_start_utc_ms, range_end_utc_ms)` with `generation_id = G`.

- Every entry written by P MUST carry `generation_id = G`.
- `G` MUST be strictly greater than any previously assigned `generation_id`.
- After P completes, all entries in `ExecutionWindowStore` within `[range_start_utc_ms, range_end_utc_ms)` MUST have `generation_id = G`.
- Entries outside `[range_start_utc_ms, range_end_utc_ms)` MUST NOT have their `generation_id` altered by P.
- A Channel Manager read of any sub-range of `[range_start_utc_ms, range_end_utc_ms)` MUST return entries with a single `generation_id`. If P is in progress, the read MUST return either all pre-P entries or all post-P entries for the affected range.

## Violation

Any of the following:

- Channel Manager read returns entries with more than one distinct `generation_id` within a single publish range.
- `generation_id` assigned to a publish is less than or equal to a previously assigned `generation_id`.
- Entry outside the publish range has its `generation_id` modified.

MUST be logged as planning fault with fields: `observed_generation_ids` (set), `time_range_start_utc_ms`, `time_range_end_utc_ms`, `expected_generation_id`.

## Required Tests

- `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py` (THAP-001: publish G2 over G1 range; all entries in range read as G2)
- `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py` (THAP-002: entries outside publish range retain original generation_id)
- `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py` (THAP-003: read during publish returns single generation_id for affected range)
- `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py` (THAP-004: operator override assigns new generation_id; partial range replacement is generation-consistent)
- All tests use `DeterministicClock` via `contract_clock` fixture. No real-time waits. Observable state: `generation_id` on every `ExecutionWindowStore` entry; `generation_id` monotonicity via publish event log.

## Enforcement Evidence

`publish_atomic_replace()` in `pkg/core/src/retrovue/runtime/execution_window_store.py` — atomic publish method on `ExecutionWindowStore`. Under a single lock acquisition: rejects non-monotonic `generation_id` with `PublishResult(ok=False, error_code="INV-HORIZON-ATOMIC-PUBLISH-001-VIOLATED: ...")`, stamps all new entries with the provided `generation_id`, removes existing entries overlapping the publish range, inserts new entries, and updates `_max_generation_id`. Returns `PublishResult` with outcome.

`read_window_snapshot()` in `pkg/core/src/retrovue/runtime/execution_window_store.py` — snapshot reader on `ExecutionWindowStore`. Under lock: collects entries overlapping `[start_utc_ms, end_utc_ms)`, verifies single `generation_id`. Logs `INV-HORIZON-ATOMIC-PUBLISH-001-OBSERVATION` warning if multiple generation_ids are observed.

`generation_id` field on `ExecutionEntry` — integer field (default `0`) carrying the publish generation. Stamped by `publish_atomic_replace()`.

Tests: `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py::TestInvHorizonAtomicPublish001` — THAP-001 (complete generation after publish), THAP-002 (non-overlapping range unaffected), THAP-003 (snapshot single-generation monotonicity), THAP-004 (operator override partial range).
