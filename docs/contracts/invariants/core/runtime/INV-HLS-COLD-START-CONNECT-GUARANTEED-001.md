# INV-HLS-COLD-START-CONNECT-GUARANTEED-001

## Behavioral Guarantee

A single HLS manifest request to a cold channel (no active producer, empty segment ring)
MUST result in an HTTP 200 response with a valid playlist within the channel's bounded
startup window, without requiring the client to retry.

The manifest endpoint MUST NOT return 503 as a result of normal cold-start latency.
503 is permitted ONLY when the startup concurrency cap is exhausted
(per INV-CHANNEL-STARTUP-CONCURRENCY-001).

## Authority Model

ProgramDirector owns the manifest endpoint and activation dispatch.
HlsConsumptionAdapter.activate() owns the full HLS activation lifecycle.
SegmentRing is the readiness signal: ring.count() > 0 means segments are available.

## Boundary / Constraint

- The manifest endpoint MUST await activation rather than fire-and-forget it.
- activate() MUST be safe to run on the asyncio event loop — no threading.Lock
  acquisitions may occur directly on the event loop thread inside activate().
- All blocking operations inside activate() (threading.Lock, fanout creation)
  MUST run in a bounded executor thread.
- The fanout wait loop inside activate() MUST proceed as soon as the fanout
  exists (fanout is not None), not wait for fanout.is_running(). The fanout
  is started by _activate_phantom() below the loop; waiting for is_running()
  causes unnecessary delay that allows Air's socket buffer to overflow.
- Pre-warming channels to satisfy this invariant is PROHIBITED.
  Channel activation MUST only occur in response to a viewer request.
- Warm channel requests (ring.count() > 0) MUST return 200 immediately.

## Violation

A cold HLS request returns 503 because: (a) activation was fire-and-forget and the
ring was empty at check time, (b) activate() blocked the event loop via threading.Lock,
causing a server-wide deadlock, or (c) the fanout loop delayed activation long enough
for Air's socket to overflow and disconnect.

## Derives From

`LAW-LIVENESS`, `INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001`,
`INV-HLS-LIFECYCLE-SEGMENT-READY-001`, `INV-CHANNEL-STARTUP-CONCURRENCY-001`

## Required Tests

- `tests/contracts/hls_delivery/test_hls_cold_start_connect.py`

## Enforcement Evidence

Verified 2026-03-30 — cold channel single HLS request returns HTTP 200 within
~7s on standard hardware.
