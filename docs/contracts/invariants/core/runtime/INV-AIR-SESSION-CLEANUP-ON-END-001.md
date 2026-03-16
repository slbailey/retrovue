# INV-AIR-SESSION-CLEANUP-ON-END-001

## Behavioral Guarantee

When AIR sends a `SessionEnded` event, the AIR subprocess MUST be terminated before the recovery callback fires. This prevents orphaned AIR processes from accumulating during recovery cycles.

## Authority Model

PlayoutSession owns AIR subprocess lifecycle. The `SessionEnded` event handler MUST call `_terminate_air_process()` before invoking `on_session_end` callback.

## Boundary / Constraint

- On receiving `SessionEnded` from AIR's gRPC event stream, PlayoutSession MUST terminate the AIR subprocess (SIGTERM + wait) BEFORE firing the `on_session_end` callback.
- The callback triggers ChannelManager recovery, which may spawn a new AIR. If the old AIR is not dead, both run simultaneously — wasting CPU and potentially fighting over the UDS socket.
- `terminate()` MUST be called with a timeout; if AIR does not exit, `kill()` MUST follow.

## Violation

AIR subprocess still running after `on_session_end` callback fires; multiple AIR processes for the same channel; increasing AIR process count during recovery cycles.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `tests/contracts/hls_delivery/test_startup_headroom.py`

## Enforcement Evidence

TODO
