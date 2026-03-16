# INV-HLS-SEGMENT-INDEX-GUARD-001

## Behavioral Guarantee

The segment index counter advances by exactly 1 per completed segment. An index value MUST never be reused, skipped, or decrease. The counter is the sole source of segment indices.

## Authority Model

HLSSegmenter owns the counter. Counter state is protected by the segmenter's internal lock. No external component may read or mutate the counter directly.

## Boundary / Constraint

- Before assigning an index, the segmenter MUST verify `next_index == previous_index + 1`.
- If the check fails, the segmenter MUST log at ERROR level with invariant ID and the expected vs. actual values, then force-correct the counter to `max(next_index, previous_index + 1)`.
- The counter MUST NOT be decremented under any circumstance.
- On ChannelManager destruction, the counter is lost. On ChannelManager persistence across producer restarts, the counter MUST survive.

## Violation

Index reuse; index gap within a continuous session; index decrease; counter mutation from outside the segmenter.

## Derives From

`INV-HLS-SEGMENT-IDENTITY-001`, `LAW-CLOCK`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_timeline.py`

## Enforcement Evidence

TODO
