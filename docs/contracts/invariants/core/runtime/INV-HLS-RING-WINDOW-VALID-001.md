# INV-HLS-RING-WINDOW-VALID-001

## Behavioral Guarantee

After every push operation, the ring's internal state is self-consistent: `newest_index - oldest_index + 1 == len(segments)` and `len(segments) <= capacity`. This check detects partial writes, double evictions, and index drift.

## Authority Model

SegmentRing owns the consistency check. The check MUST execute inside the same critical section as the push.

## Boundary / Constraint

- After every push, the ring MUST verify: `newest_index - oldest_index + 1 == len(segments) <= capacity`.
- If the check fails, the ring MUST log at ERROR level with invariant ID, `oldest_index`, `newest_index`, `len(segments)`, and `capacity`.
- On failure, the ring MUST rebuild its index range from the actual segment keys to restore consistency, then log the corrective action.
- The consistency check MUST NOT be skippable or configurable.

## Violation

`newest_index - oldest_index + 1 != len(segments)`; `len(segments) > capacity`; consistency check absent after push.

## Derives From

`INV-HLS-RING-BOUNDED-001`, `INV-HLS-RING-OBSERVATION-001`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_ring_integrity.py`

## Enforcement Evidence

TODO
