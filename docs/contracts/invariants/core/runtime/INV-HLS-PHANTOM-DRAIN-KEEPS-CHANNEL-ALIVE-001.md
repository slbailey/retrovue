# INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001

## Behavioral Guarantee

When a canonical HLS manifest request activates a channel, a phantom drain subscriber MUST be attached to the channel's ChannelStream fanout. This phantom keeps the runtime byte pipeline alive — without it, the channel producer cycle-stops because no subscriber drains the fanout. The phantom MUST exist for exactly as long as HLS clients are actively polling.

## Authority Model

ProgramDirector owns phantom lifecycle. The phantom subscribes via the existing ChannelStream fanout model. ChannelManager viewer lifecycle (tune_in/tune_out, first-viewer/last-viewer, linger) governs producer start/stop. The phantom does not create a parallel lifecycle.

## Boundary / Constraint

- Exactly one phantom drain MUST exist per channel for canonical HLS. Concurrent manifest requests MUST NOT start multiple phantoms.
- The phantom MUST subscribe to the ChannelStream fanout and continuously drain bytes, keeping the subscriber list non-empty.
- The phantom MUST monitor HLS client activity (manifest/segment request recency). When no HLS client has made a successful request within the idle timeout, the phantom MUST disconnect.
- Phantom disconnect MUST call `tune_out()` and `unsubscribe()`, allowing the normal viewer_count → 0 → linger → teardown lifecycle to proceed.
- Phantom startup failure (no fanout established) MUST clean up the phantom session and call `tune_out()`.
- The phantom MUST NOT create a second producer or a second encoder. It MUST use the existing single-producer-per-channel model.

## Violation

Multiple phantom drains for the same channel; phantom running with no HLS client activity beyond idle timeout; phantom preventing channel teardown after all HLS clients depart; phantom creating a second producer; no phantom started on HLS activation (causing channel cycle-stop).

## Derives From

`INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001`, `LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `tests/contracts/hls_delivery/test_hls_phantom_drain.py`

## Enforcement Evidence

TODO
