# Stream Bootstrap Contract

## Purpose

A live MPEG-TS stream must be **joinable at arbitrary time**. A viewer
tuning into the channel at any point must be able to begin decoding
video within a bounded interval without relying on data transmitted
before they connected.

This contract defines the observable requirements on the encoded
transport stream that make this possible.

## Invariants

### INV-STREAM-JOINABLE

A viewer joining the transport stream at any time MUST receive
the H.264 SPS (Sequence Parameter Set) and PPS (Picture Parameter
Set) NAL units before the first slice NAL unit they need to decode.

Without these parameter sets, the decoder cannot interpret slice
data and will report errors such as `non-existing PPS 0 referenced`.

### INV-H264-PARAMETER-SETS

Every IDR (Instantaneous Decoder Refresh) frame in the encoded
stream MUST be preceded by SPS and PPS NAL units within the same
access unit.

This ensures that any viewer who receives an IDR frame — the only
frame type that does not depend on prior reference frames — also
receives the parameter sets required to decode it.

### INV-STREAM-BOOTSTRAP-BOUND

The bootstrap interval — the maximum time between a viewer
connecting and receiving the first decodable frame — MUST NOT
exceed one GOP (Group of Pictures) duration.

Since IDR frames occur at GOP boundaries and carry SPS/PPS
(per INV-H264-PARAMETER-SETS), a viewer connecting at the worst
possible moment (immediately after an IDR) will wait at most one
full GOP before the next IDR arrives with its parameter sets.

## Observable Behavior

The contract is verified by inspecting the NAL unit types in the
encoded H.264 byte stream. The following NAL unit types are relevant:

| NAL Type | Value | Meaning |
|----------|-------|---------|
| SPS      | 7     | Sequence Parameter Set |
| PPS      | 8     | Picture Parameter Set |
| IDR      | 5     | Instantaneous Decoder Refresh (keyframe) |
| Non-IDR  | 1     | Coded slice of a non-IDR picture (P-frame) |

For every IDR NAL unit observed in the stream, there MUST be at
least one SPS NAL unit and at least one PPS NAL unit preceding it
within the same access unit (i.e., since the last slice NAL unit
of the previous frame).

## Scope

This contract applies to all H.264 video output produced by the
EncoderPipeline, regardless of whether the output path is:

1. **MpegTSOutputSink** (MuxLoop / live viewers)
2. **PipelineManager** (BlockPlan execution)

Both paths use the same EncoderPipeline and therefore the same
encoder configuration.

## Design Note: Wall-Clock Bootstrap Latency

INV-STREAM-BOOTSTRAP-BOUND ties worst-case join latency to GOP duration.
At current settings (gop_size=30, 29.97fps) this is ~1 second — well within
acceptable viewer experience.

If `gop_size` is ever increased significantly (e.g., 120 → ~4s latency),
consider adding a wall-clock cap such as `bootstrap_latency ≤ 2s`. The fix
is straightforward: either cap `gop_size ≤ max_bootstrap_seconds * fps`, or
insert periodic IDR frames independent of GOP structure (forced keyframe
injection). The existing contract tests already have the machinery to enforce
a time-based bound — just add a duration assertion alongside the frame-count
assertion in INV_STREAM_BOOTSTRAP_BOUND_SpsPpsPerGop.

This is a design decision, not a bug. Documented here so the tradeoff is
visible when encoder parameters change.

## Relationship to Other Contracts

- **INV-MUX-WRITE-ORDER**: Governs packet ordering in the mux.
  Orthogonal — correct mux ordering does not guarantee parameter
  set presence.

- **INV-AIR-IDR-BEFORE-OUTPUT**: Existing invariant requiring the
  first video packet to be an IDR. This contract extends that
  requirement to ALL IDR frames, not just the first.

- **INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT**: Governs muxer buffering
  and emission latency. Complementary — low-latency emission is
  necessary but not sufficient for joinability.
