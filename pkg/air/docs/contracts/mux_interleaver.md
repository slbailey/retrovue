# Mux Interleaver Contract

## Clock Authority

The mux timeline is a single 90kHz clock that begins at zero at session
start and advances monotonically for the lifetime of the session.

Both video and audio DTS values exist in this 90kHz domain. There is no
independent audio clock or video clock — there is only the mux timeline.

### Clock ownership

| Component | Role |
|-----------|------|
| Mux timeline (90kHz) | Authoritative global clock |
| Video encoder | Produces packets with DTS in mux timeline |
| Audio encoder | Produces packets with DTS in mux timeline |
| MuxInterleaver | Orders packets by DTS before writing |

Neither encoder owns the clock. The mux timeline is the authority, and
both encoders produce timestamps that reference it.

### Timestamp derivation

Video DTS is derived from the caller-provided `pts90k` (session
presentation time), rescaled through the H.264 codec time base and back
to the video stream time base ({1, 90000}).

Audio DTS is derived from `audio_encode_sample_counter_` (an internal
sample counter that advances by exactly `frame_size` per AAC chunk).
The counter is converted to 90kHz: `(counter * 90000) / sample_rate`.
This produces DTS values 0, 1920, 3840, 5760, ... which represent
real presentation times in the mux 90kHz domain.

Both produce DTS starting at zero and advancing at their respective
frame rates. They are in the same clock domain.

## Invariants

### INV-MUX-PER-STREAM-DTS-MONOTONIC

Within each elementary stream, the sequence of DTS values at
`av_interleaved_write_frame()` MUST be non-decreasing.

A packet whose DTS regresses within its own stream is DROPPED and
a violation is logged.

Cross-stream DTS differences are **normal and expected**. Audio and
video have different codec delays (AAC priming vs H.264 zerolatency)
and different cadences (1920 vs 3003 ticks). An audio packet with
DTS lower than the last video DTS is NOT a violation — MPEG-TS
requires per-stream monotonicity, not global monotonicity.

### INV-AAC-PRIMING-DROP

The AAC encoder produces a priming packet with negative DTS/PTS
(typically -1024 samples = -1920 in 90kHz). This packet contains
encoder delay padding, not real audio.

Priming packets (DTS < 0 after rescaling to stream time_base) are
**dropped silently**. `last_audio_mux_dts_` is NOT advanced when
dropping a priming packet. The first real audio packet (DTS=0)
becomes the true first audio packet.

### INV-MUX-SESSION-CLOCK-AUTHORITY

The mux timeline is derived from the session clock. It starts at zero
at session start and does NOT reset when:

- A new segment begins
- A producer switch occurs
- The audio buffer refills after underflow
- Silence injection starts or stops

The `audio_encode_sample_counter_` and video `pts90k` both start at
zero and advance monotonically for the session lifetime.

### INV-MUX-WRITE-ORDER

Packets written to the mux MUST be emitted in ascending DTS order across
all streams. The MuxInterleaver buffers packets from video and audio
encoders and drains them through a min-heap ordered by `dts_90k`. This
produces a globally non-decreasing DTS sequence at the write callback.

This is how real TS muxers work. Per-stream monotonicity
(INV-MUX-PER-STREAM-DTS-MONOTONIC) is a necessary but not sufficient
property — the interleaver must also merge the two streams into a single
correctly-ordered output.

Example with video cadence 3003 and audio cadence 1920:

```
V dts=0  →  written 1st
A dts=0  →  written 2nd  (tie: video before audio)
A dts=1920 → written 3rd
V dts=3003 → written 4th
A dts=3840 → written 5th
V dts=6006 → written 6th
```

### INV-MUX-CYCLE-FLUSH

The MuxInterleaver MUST be flushed at **encode-cycle boundaries**,
not per-packet.

An encode cycle is one iteration of the playout loop:
1. Encode one video frame
2. Encode corresponding audio frame(s)
3. Flush the interleaver

Flushing per-packet can cause one stream to advance far ahead of
the other. Cycle-flush ensures all packets from the same time range
are in the buffer before draining, producing correct interleaving.

## Observed Failures and Fixes

### Failure 1: Global DTS monotonicity was too strict

**Symptom:**
```
[MuxInterleaver] INV-MUX-GLOBAL-DTS-MONOTONIC VIOLATION:
  stream=1 dts_90k=1920 < last_global=3003 — DROPPING packet
```

**Root cause:** The interleaver enforced a single `last_global_dts`
across all streams. Audio and video have different cadences (1920 vs
3003 ticks at 90kHz) and different encoder delays. Audio packets are
routinely "behind" the last video DTS. This is normal MPEG-TS
behavior, not a violation.

**Fix:** Changed to per-stream monotonicity
(INV-MUX-PER-STREAM-DTS-MONOTONIC). Each stream tracks its own
`last_dts`. Cross-stream comparisons are not enforced.

### Failure 2: AAC priming produced garbage DTS

**Symptom:**
```
[INV-MUX-DTS-TRACE] audio pkt#0 raw_encoder: dts=-1024
  → clamp to 0 → EnforceMonotonicDts bumps to 1 → dts_90k=1
[INV-MUX-DTS-TRACE] audio pkt#1 raw_encoder: dts=0
  → EnforceMonotonicDts bumps to 2 → dts_90k=2
```

**Root cause:** The first-packet clamp block set `last_audio_mux_dts_=0`,
then `EnforceMonotonicDts` saw `dts=0 <= last=0` and bumped to 1.
The next real packet (DTS=0) got bumped to 2. This created artificial
DTS values (1, 2) that don't correspond to real audio timing.

**Fix:** Drop priming packets entirely (INV-AAC-PRIMING-DROP).
Do not advance `last_audio_mux_dts_`. First real packet starts
cleanly at DTS=0.

## Scope

This contract applies to both production code paths:

1. **MpegTSOutputSink** (MuxLoop): Uses external MuxInterleaver, flushed
   at end of MuxLoop iteration. Already satisfies INV-MUX-CYCLE-FLUSH.

2. **PipelineManager** (BlockPlan): Uses internal MuxInterleaver in
   EncoderPipeline. Must be flushed at encode-cycle boundaries via
   `EncoderPipeline::FlushMuxInterleaver()`.

## Relationship to Other Contracts

- **INV-MUX-STARTUP-HOLDOFF**: Prevents writes before both streams
  observed. A prerequisite for this contract.

- **INV-AUDIO-SAMPLE-CLOCK**: Governs PTS generation for audio chunks.
  Orthogonal — correct PTS generation does not guarantee correct mux
  ordering without proper interleaving.

- **OutputContinuityContract**: Per-stream monotonicity via
  `EnforceMonotonicDts()`. Consistent with INV-MUX-PER-STREAM-DTS-MONOTONIC.
