# INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001

## Behavioral Guarantee

The first successful HLS manifest request for an inactive channel MUST activate the channel through the same ChannelManager lifecycle used by raw TS viewers. HLS activation MUST be idempotent — concurrent or repeated manifest requests MUST NOT start multiple producers.

## Authority Model

ProgramDirector owns channel activation routing. ChannelManager owns the viewer lifecycle (tune_in → first-viewer → producer start). The HLS manifest endpoint delegates to this existing lifecycle.

## Boundary / Constraint

- An HLS manifest request for a configured channel that has no active ChannelManager MUST create one through the same path as raw TS requests (`_get_or_create_manager`).
- An HLS manifest request for an active channel with zero viewers MUST trigger `tune_in()` to activate the producer via the first-viewer lifecycle transition.
- Multiple concurrent manifest requests MUST NOT start multiple producers. The ChannelManager's existing serialization guarantees this.
- After activation, the manifest endpoint MUST return 503 + `Retry-After` until segments are available, then 200 with a valid playlist.
- HLS activation MUST NOT create a parallel lifecycle. It MUST use the same `ChannelManager.tune_in()` path as raw TS.

## Violation

HLS manifest request for a configured channel fails to activate the channel; multiple producers started from concurrent HLS requests; HLS activation bypasses ChannelManager tune_in; channel activation creates parallel lifecycle outside ChannelManager ownership.

## Derives From

`LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `tests/contracts/hls_delivery/test_hls_activation.py`

## Enforcement Evidence

TODO
