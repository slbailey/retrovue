# Mux Startup Interleave Contract

## Invariant

**INV-MUX-STARTUP-HOLDOFF**

The muxer MUST NOT write any packet to `av_write_frame()` until at least
one packet from **every active stream** (audio and video) has been observed
in the interleave buffer.

## Rationale

Encoders produce packets at different startup times:

- AAC audio encoders produce output immediately (no lookahead).
- H.264 video encoders buffer 1+ frames due to lookahead/B-frame logic.

If the mux writes audio packets before the first video packet arrives, the
mux timeline advances forward (e.g. audio DTS = 1, 2, 1920, 3840...).
When the first video packet finally arrives with DTS = 0, the muxer sees a
DTS regression and reports:

    "Application provided invalid, non monotonically increasing dts
     to muxer in stream 1: N >= N"

This is a broadcast-correctness violation.

## Observable Behavior

1. Before the first flush, the interleave buffer must have seen:
   - At least one audio packet (stream_index corresponding to audio)
   - At least one video packet (stream_index corresponding to video)

2. While either stream is missing, `Flush()` is a no-op. Packets
   accumulate in the buffer but are not written.

3. Once both streams have contributed at least one packet, `Flush()`
   drains the buffer in global DTS order (min-heap).

4. After the holdoff is satisfied, it is permanently released for the
   lifetime of the session. Subsequent flushes do not re-check.

## Failure Mode

If a packet is written before both streams are observed:

- The mux timeline may advance past DTS = 0 on the fast stream.
- The delayed stream's first packet appears to regress in DTS.
- FFmpeg emits a non-monotonic DTS warning.
- Players may drop frames or lose A/V sync at startup.

## Relationship to Other Contracts

- **INV-MUX-GLOBAL-DTS-MONOTONIC**: This contract is a prerequisite.
  Startup holdoff prevents the specific DTS regression that violates
  global monotonicity during encoder startup.

- **INV-MUX-BOUNDED-BUFFERING**: Holdoff may cause temporary buffering
  of packets from the fast stream. Once released, all held packets
  drain in a single flush.

## Scope

This contract applies to the MuxInterleaver component. It defines
observable behavior only and does not prescribe implementation details.
