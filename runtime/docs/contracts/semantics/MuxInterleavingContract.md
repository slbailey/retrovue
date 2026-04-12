# Mux Interleaving Contract

_Related: [OutputContinuity Contract](OutputContinuityContract.md) · [OutputTiming Contract](OutputTimingContract.md)_

**Status:** Active
**Scope:** Air (C++) playout engine runtime — EncoderPipeline mux layer
**Audience:** Engine implementers, future maintainers

---

## 1. Overview

**Mux Interleaving** ensures that encoded packets from all elementary streams
(video + audio) are written to the MPEG-TS muxer in globally non-decreasing DTS
order. This is a cross-stream ordering constraint, distinct from
OutputContinuity (which enforces per-stream monotonicity).

Without interleaving enforcement, encoder latency differences between video
(H.264) and audio (AAC) cause packets to arrive at the muxer in the wrong
global order. For example, AAC produces output immediately while H.264 may
buffer one frame — causing audio packets to be written before the first video
packet, violating the MPEG-TS DTS monotonicity requirement.

---

## 2. Invariants

### INV-MUX-GLOBAL-DTS-MONOTONIC
**Every packet written to the MPEG-TS muxer MUST have a DTS greater than or
equal to the DTS of the previously written packet, regardless of stream.**

Observable property: For the sequence of all `av_write_frame()` calls across
all streams, the DTS values (when rescaled to a common timebase) form a
non-decreasing sequence.

Violation signal: ffmpeg error `"non monotonically increasing dts to muxer"`.

### INV-MUX-INTERLEAVE-BY-DTS
**Packets from different elementary streams MUST be interleaved by DTS before
being passed to the muxer.** The interleaving buffer collects packets from
both video and audio encoders and drains them in DTS order.

Observable property: When the MuxLoop encodes video frame N and its
corresponding audio, the resulting packets are sorted by DTS before any
`av_write_frame()` call.

### INV-MUX-BOUNDED-BUFFERING
**The interleaving buffer MUST NOT accumulate unbounded packets.** It is
flushed after each MuxLoop iteration (one video frame + associated audio).
The maximum buffer depth is bounded by the number of packets produced per
iteration (typically 1–2 video + 1–3 audio = 5 packets maximum).

Observable property: Buffer depth after each flush is zero.

### INV-MUX-NO-STARVATION
**The interleaving buffer MUST NOT hold packets indefinitely waiting for a
stream that may never produce.** If only one stream produces packets in an
iteration (e.g., video encoder delay on first frame), those packets are
flushed at the end of the iteration rather than held.

Observable property: All packets enqueued during an iteration are written
before the next iteration begins.

### INV-MUX-PRESERVE-STREAM-ORDER
**Packets within the same elementary stream MUST maintain their original
ordering through the interleaving buffer.** The buffer reorders across
streams but never within a stream.

Observable property: Per-stream DTS sequence after interleaving is identical
to per-stream DTS sequence before interleaving.

### INV-MUX-STARTUP-SYNC
**On startup, the interleaving buffer MUST NOT flush audio-only packets
until the first video packet is observed.** H.264 encoders may delay output
by one or more frames due to lookahead/B-frame buffering. During this
startup window, audio packets (from AAC, which outputs immediately) must be
held rather than flushed, because flushing audio before video violates
INV-MUX-GLOBAL-DTS-MONOTONIC.

Once the first video packet enters the buffer, the holdoff is released and
all buffered packets (video + audio) are flushed in DTS order.

Observable property: No `av_interleaved_write_frame()` calls occur until the
buffer contains at least one video packet, or a configurable startup timeout
is reached.

---

## 3. Mechanism

**MuxInterleaver** (owned by MpegTSOutputSink, not EncoderPipeline)
maintains a per-iteration packet buffer (min-heap keyed by DTS, tie-broken
by stream index with video before audio on tie).

EncoderPipeline has a **PacketCaptureCallback**. When set, `encodeFrame()`
and `encodeAudioFrame()` clone each encoded packet and deliver it to the
callback instead of writing directly. MpegTSOutputSink's callback routes
cloned packets into MuxInterleaver.

After both video and audio for the current MuxLoop tick are encoded,
`MuxInterleaver::Flush()` drains the buffer in DTS order, calling
`EncoderPipeline::WriteMuxPacket()` for each packet. WriteMuxPacket uses
`av_interleaved_write_frame()` for the actual muxer write.

**Startup holdoff** (INV-MUX-STARTUP-SYNC): On creation, MuxInterleaver
starts with holdoff enabled. Flush() is a no-op until the first video packet
is enqueued. This prevents audio-only writes during H.264 startup delay.

---

## 4. Relationship to OutputContinuity

- **OutputContinuity** (per-stream): ensures `current_dts >= last_dts` within
  each stream independently.
- **Mux Interleaving** (cross-stream): ensures the global write sequence is
  DTS-ordered across all streams.

Both are required. OutputContinuity alone does not prevent cross-stream
misordering. Mux Interleaving alone does not prevent per-stream regression.

---

## 5. Failure Modes Prevented

- `"non monotonically increasing dts to muxer"` from ffmpeg
- Audio packets written before first video packet (encoder delay)
- Decoder stalls in downstream consumers due to illegal packet ordering
- VLC/ffplay re-probing or stream reset on DTS violations
