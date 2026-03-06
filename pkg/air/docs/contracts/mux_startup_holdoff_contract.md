# Mux Startup Holdoff Contract

## Invariants

### INV-MUX-STARTUP-HOLDOFF

The muxer MUST NOT write ANY packet (of any stream) to `av_write_frame()`
until at least one VIDEO packet AND at least one AUDIO packet have been
**observed** for this program.

**Observed** means: a packet has been produced by its encoder and is
available to the mux layer, even if not yet written.

### INV-MUX-STARTUP-FIRST-PACKET

The very first packet written to `av_write_frame()` must have the minimum
DTS among all packets buffered so far, across all streams.

Specifically, when the first video packet has DTS=0 and audio packets have
DTS>0, the video packet MUST be written first. When video DTS=0 ties with
audio DTS=0, video MUST be written first (video stream_index < audio
stream_index in the min-heap comparator).

### INV-MUX-GLOBAL-DTS-MONOTONIC

The sequence of DTS values observed at `av_write_frame()`, when rescaled
into a common 90kHz timebase, MUST be non-decreasing globally across all
elementary streams.

## Rationale

Encoders produce packets at different startup times:

- AAC audio encoders produce output immediately (no lookahead).
- H.264 video encoders buffer 1+ frames due to lookahead/B-frame logic.

If the mux writes audio packets before the first video packet arrives, the
mux timeline advances forward (e.g. audio DTS = 1, 2, 1920, 3840...).
When the first video packet finally arrives with DTS=0, the muxer sees a
DTS regression and reports:

    "Application provided invalid, non monotonically increasing dts
     to muxer in stream 1: N >= N"

This is a broadcast-correctness violation.

## Observed Failure (production evidence)

```
A(1) dts=0.000011     audio written first (encoder startup)
A(1) dts=0.000022     audio continues
A(1) dts=0.021333     audio at AAC cadence
A(1) dts=0.042667     audio at AAC cadence
V(0) dts=0.000000     video arrives AFTER audio DTS > 0  <-- VIOLATION
```

The first video packet (DTS=0) appears after audio has already advanced
past DTS=0. This is a global DTS regression.

## Observable Behavior

1. Before the first flush, the mux layer must have seen:
   - At least one audio packet (from the audio encoder)
   - At least one video packet (from the video encoder)

2. While either stream is missing, no packet of ANY stream is written to
   `av_write_frame()`. Packets accumulate in a buffer.

3. Once both streams have contributed at least one packet, the buffer
   drains in global DTS order (min-heap). The first written packet has
   the minimum DTS across all buffered packets.

4. After the holdoff is satisfied, it is permanently released for the
   lifetime of the session. Subsequent writes do not re-check.

5. After holdoff release, every subsequent packet written has DTS >=
   the DTS of the previously written packet (global monotonicity).

## Scope

This contract applies to ALL code paths that produce encoded packets and
write them to the MPEG-TS muxer. This includes:

- MpegTSOutputSink MuxLoop path (external MuxInterleaver)
- PipelineManager BlockPlan path (internal interleaver in EncoderPipeline)

There MUST be no code path that can call `av_write_frame()` before the
holdoff conditions are met. All write paths route through the same gate.

## Acceptance Criterion

After this contract is enforced, the following output is IMPOSSIBLE:

    A, A, A, A, V(dts=0)

Instead, the first packets must start with:

    V(dts=0) before any audio packet with dts>0

## Relationship to Other Contracts

- **INV-MUX-GLOBAL-DTS-MONOTONIC**: This contract is a prerequisite.
  Startup holdoff prevents the specific DTS regression that violates
  global monotonicity during encoder startup.

- **INV-MUX-BOUNDED-BUFFERING**: Holdoff may cause temporary buffering
  of packets from the fast stream. Once released, all held packets
  drain in a single flush.

- **INV-AUDIO-SAMPLE-CLOCK**: Audio PTS authority is orthogonal.
  Even with correct audio PTS values, the mux ordering problem occurs
  if audio is written before video.
