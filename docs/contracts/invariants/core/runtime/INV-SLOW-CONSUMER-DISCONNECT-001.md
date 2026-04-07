# INV-SLOW-CONSUMER-DISCONNECT-001

## Behavioral Guarantee

A live viewer whose consumption rate cannot keep pace with the TS stream MUST be disconnected before its degraded TCP state can produce sustained artifacts for itself or cascade backpressure into shared delivery components.

## Authority Model

**Owner:** ChannelStream (runtime/channel_stream.py)

ChannelStream owns per-client queue management and backpressure policy enforcement. When a client's queue overflows (hits the byte cap), the configured backpressure policy determines the response. The `disconnect` policy sends an EOF sentinel to the client queue, causing the HTTP generator to close the connection. The client (e.g. VLC) reconnects automatically and resumes from the live point with a fresh TCP state.

## Boundary / Constraint

- The default backpressure policy MUST be `disconnect`.
- When a client queue overflow is detected (put_nowait returns eviction), the `disconnect` policy MUST send an EOF sentinel (`b""`) to that client's queue and remove the subscriber.
- A client that triggers BACKPRESSURE MUST NOT remain connected indefinitely in a degraded state — the system MUST sever the connection within a bounded number of overflow events.
- The disconnect MUST be logged as a structured event with `client_id`, `channel_id`, and `reason=backpressure_disconnect`.
- Transient congestion (single overflow events that self-resolve) is acceptable; persistent overflow (continuous eviction across multiple fanout cycles) MUST trigger disconnect.

## Violation

- A backpressure policy of `drop_oldest` is used as default, allowing permanently degraded clients to remain connected indefinitely while receiving a gapped stream.
- A client in sustained BACKPRESSURE state is never disconnected, producing continuous visual/audio artifacts with no recovery path.
- A disconnect event occurs without a structured log entry.

## Derives From

- LAW-LIVENESS: A degraded client that is never disconnected violates liveness for that viewer — they receive an unplayable stream indefinitely rather than reconnecting to a clean live point.
- LAW-RUNTIME-AUTHORITY: The runtime delivery path must make authoritative decisions about connection health; deferring to a permanently slow client undermines runtime correctness.

## Required Tests

- pkg/core/tests/contracts/runtime/test_slow_consumer_disconnect.py

## Enforcement Evidence

- `_fanout_loop()` in `channel_stream.py`: when `backpressure_policy == "disconnect"` and `put_nowait` reports eviction, the client is removed from subscribers, sent an EOF sentinel, and a structured `SLOW_CONSUMER_DISCONNECT` event is logged with `client_id`, `channel_id`, and `reason=backpressure_disconnect`.
- Per-client throttle state (`_backpressure_log_last`) is cleaned up on disconnect to prevent memory leaks.
- `generate_ts_stream_async()`: write timeout (default 10s) detects dead clients when `yield` (TCP write) stalls beyond the threshold, logging `WRITE_TIMEOUT` and closing the connection.
- Contract tests at `pkg/core/tests/contracts/runtime/test_slow_consumer_disconnect.py` prove all six guarantees (disconnect + EOF, backpressure log, drop_oldest regression guard, state cleanup, reason field, write timeout).
