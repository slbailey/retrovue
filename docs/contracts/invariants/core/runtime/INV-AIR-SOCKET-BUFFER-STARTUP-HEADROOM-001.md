# INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001

## Behavioral Guarantee

AIR's output socket buffer MUST be large enough to absorb at least 3 seconds of encoded output at the configured CBR mux rate without overflowing. This prevents SocketSink detach during channel startup, when Core has not yet connected the ChannelStream reader to drain the socket.

## Authority Model

AIR's PipelineManager owns buffer sizing via `kSinkBufferCapacity`. Core's channel activation path (ChannelManager → BlockPlanProducer → ChannelStream) owns the reader connection timing.

## Boundary / Constraint

- `kSinkBufferCapacity` MUST be >= `mux_rate_bytes_per_second * 3`. At 10Mbps CBR mux (~1.25MB/s), the minimum is 3.75MB.
- If the buffer is too small, AIR's SocketSink overflows before Core connects, triggering detach → `stop_requested` → `SessionEnded(reason=stopped)` → recovery loop → orphaned AIR processes.
- The buffer size MUST NOT be reduced below the startup headroom without also reducing the Core reader connection latency.

## Violation

`SocketSink detach` during channel startup due to buffer overflow before Core connects; recovery crash-loop on channel activation; orphaned AIR processes.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `tests/contracts/hls_delivery/test_startup_headroom.py`

## Enforcement Evidence

TODO
