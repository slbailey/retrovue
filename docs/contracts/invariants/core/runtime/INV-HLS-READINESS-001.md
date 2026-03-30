# INV-HLS-READINESS-001

## Behavioral Guarantee

The HLS manifest endpoint MUST NOT serve a playlist until the SegmentRing has produced a valid, playable playlist window.

On a cold-start request, the manifest handler MUST await an HLS-readiness signal rather than poll or return 503. The readiness signal is set when the ring first satisfies the playable-window criteria and remains set for the lifetime of the activation.

## Authority Model

SegmentRing owns the readiness signal and the definition of "playable window." ProgramDirector's manifest handler awaits the signal with a bounded timeout.

## Boundary / Constraint

- SegmentRing MUST expose an `asyncio.Event`-compatible readiness signal, set when the ring contains a playable playlist window.
- What constitutes a playable window is a SegmentRing configuration parameter, not defined by this invariant.
- The manifest handler MUST `await` this signal on cold-start, with a bounded timeout.
- If the timeout expires before readiness, the handler MUST return HTTP 503 with `Retry-After`.
- Once readiness is achieved, the signal remains set for the lifetime of the activation. Subsequent manifest requests MUST NOT await — they serve immediately.
- On channel teardown or ring clear, the readiness signal MUST be reset so the next activation starts unready.
- Warm-channel requests (readiness already set) MUST NOT incur any await or polling overhead.

## Violation

Manifest endpoint returns HTTP 200 before the readiness signal is set. Manifest handler polls ring state in a loop instead of awaiting a readiness signal. Cold-start request returns 503 due to fire-and-forget activation.

## Derives From

`INV-HLS-COLD-START-CONNECT-GUARANTEED-001`, `INV-HLS-LIFECYCLE-SEGMENT-READY-001`, `LAW-LIVENESS`

## Required Tests

- `tests/contracts/hls_delivery/test_hls_readiness.py`

## Enforcement Evidence

TODO
