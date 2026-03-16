# INV-HLS-SEGMENT-IDENTITY-001

## Behavioral Guarantee

Every completed HLS segment receives a channel-scoped integer index. Indices are strictly monotonically increasing with no gaps during a continuous producer session. No two segments within the same channel share an index.

## Authority Model

HLSSegmenter owns index assignment. Index counter is channel-scoped and persists across producer restarts within a single ChannelManager lifetime.

## Boundary / Constraint

- Segment identity MUST be `(channel_id, index)`. No other dimension (viewer session, connection time, client identity) MUST participate in identity.
- Indices MUST be strictly monotonically increasing within a producer session.
- Two references to the same `(channel_id, index)` MUST denote the same segment.
- Index MUST NOT reset to zero on producer restart if the ChannelManager instance persists.

## Violation

Duplicate index assigned to distinct segments; index gap within a continuous producer session; segment identity incorporating client-specific state.

## Derives From

`LAW-CLOCK`, `LAW-DERIVATION`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_production.py`

## Enforcement Evidence

TODO
