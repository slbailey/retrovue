# Segment Seam Overlap Contract (AIR)

**Classification**: Semantic Contract (Layer 1)
**Owner**: `PipelineManager` / `SeamPreparer` (replaces `ProducerPreloader` for segment scope)
**Derives From**: INV-SEAM-006 (Eager Decoder Preparation, SeamContinuityEngine.md), INV-SEAM-004 (Mechanical Equivalence), INV-SEAM-001 (Clock Isolation)
**Refines**: SegmentContinuityContract.md (OUT-SEG-001..006)
**Governs**: All intra-block segment transitions — content→filler, filler→content, content→pad, pad→content, filler→pad, pad→filler
**Scope**: AIR runtime playout engine

---

## Preamble

This contract specifies the implementation constraints for decoder-overlapped segment transitions within a program block. It is the companion to SeamContinuityEngine.md, which defines the overlap *model*. This contract defines the overlap *enforcement* for intra-block seams specifically.

The existing block-level overlap (ProducerPreloader → TAKE → rotation) satisfies INV-SEAM-006 for inter-block seams. But intra-block segment transitions currently violate INV-SEAM-006: `AdvanceToNextSegment()` performs synchronous decoder close/open on the fill thread, producing a zero-length overlap window. This contract codifies what the replacement must guarantee.

The invariants here are structural. They constrain which thread may perform which operation. A system that satisfies all six invariants cannot produce a reactive segment transition. A system that violates any one of them has a code path where decoder I/O occurs on a thread that should be decode-only or clock-only.

---

## Definitions

- **Segment activation**: The moment a segment becomes the source of frames consumed by the tick thread. For segment 0, this is block activation (TAKE or initial load). For segment N+1, this is the pointer swap at the segment seam tick.
- **Segment seam tick**: The deterministic session-frame index at which the tick thread transitions from segment N's buffers to segment N+1's buffers. Computed from block-local content-time boundaries and rational frame rate.
- **Seam-prep thread**: A single persistent worker thread (session lifetime) responsible for all decoder lifecycle operations: open, probe, seek, prime. Neither the tick thread nor any fill thread may perform these operations.
- **Synthetic FedBlock**: A FedBlock containing a single segment, derived from the parent block's segment list. Used by the seam-prep thread to prepare a segment independently of its block context.
- **Incoming slot**: The preview buffer pair (video + audio) and associated producer, pre-filled and ready for swap at the seam tick. At most one incoming slot is active at any time.

---

## Scope

These invariants apply to:

- **All intra-block segment transitions**: every change of active segment within a single program block, regardless of segment type.
- **The seam-prep thread**: all decoder lifecycle work for upcoming segments.
- **The fill thread**: its permitted and forbidden operations during segment playback.
- **The tick thread**: its seam-tick evaluation and pointer-swap logic for segment seams.
- **Segment seam tick computation**: the deterministic formula that converts content-time boundaries to session frame indices.

These invariants do NOT apply to:

- **Inter-block (program block) seams**: governed by INV-BLOCK-WALLFENCE-001 and the existing block TAKE mechanism. The invariants here apply to *intra-block* seams only, but INV-SEAM-SEG-005 requires the two mechanisms to be identical.
- **Steady-state decoding** within a single segment (no transition).
- **Fence tick computation**: remains owned by Program Block Authority.
- **Session boot** (first frame of first block): governed by INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT.
- **Decoder internals**: how FFmpeg decodes a frame. Only lifecycle events (open/close/seek) are constrained.

---

## INV-SEAM-SEG-001: Clock Isolation at Segment Seams

### Statement

**The tick thread MUST NOT perform any FFmpeg work at any seam — segment or block.**

At a segment seam tick, the tick thread evaluates `session_frame_index >= next_seam_frame_`, swaps buffer pointers (incoming → current), and pops a frame from the new current buffer. This is a pointer assignment and a deque pop. No decoder open, no probe, no seek, no decode, no format negotiation.

If the incoming slot is not ready at the segment seam tick (prep thread did not finish in time), the tick thread selects fallback: continue popping from the outgoing buffers (hold-last / pad) or emit pad frames. In no case does it wait for the prep thread.

This invariant restates INV-SEAM-001 (Clock Isolation) with explicit focus on segment seams, which currently violate it via `AdvanceToNextSegment` propagating decoder stalls through the fill thread to the tick thread's buffer.

### Violation Evidence

**In logs:**
- `SEGMENT_DECODER_OPEN` logged on the fill thread or tick thread (rather than the seam-prep thread) indicates FFmpeg work escaped the prep thread.
- `max_inter_frame_gap_us` spiking at intra-block segment boundaries indicates fill-thread stall propagated to tick thread.

**In metrics:**
- `air_continuous_late_ticks_total` incrementing in correlation with segment transitions within a block.

### Classification

**Fatal if systematic.** A single late tick at an intra-block seam indicates the fill thread stalled on decoder I/O and the buffer drained. A pattern at every segment seam indicates the reactive path (`AdvanceToNextSegment`) is still active.

---

## INV-SEAM-SEG-002: No Reactive Transitions in TryGetFrame

### Statement

**`TickProducer::TryGetFrame()` MUST NOT perform decoder lifecycle operations or segment advancement.**

`TryGetFrame()` decodes frames from an already-open decoder. When the current segment's content is exhausted (CT boundary, asset duration, decoder EOF), `TryGetFrame()` returns `std::nullopt`. It does not:

- Call `AdvanceToNextSegment()` or any successor.
- Construct, open, close, or seek an `FFmpegDecoder`.
- Modify `current_segment_index_`.
- Destroy `decoder_` and create a new one.

The function `AdvanceToNextSegment()` must not exist in `TickProducer`. Any code path within `TryGetFrame()` that previously called it must be replaced with `return std::nullopt`.

Segment advancement is the exclusive responsibility of the tick thread's pointer-swap mechanism, informed by pre-computed seam ticks and the seam-prep thread's output.

### Violation Evidence

**In code (structural):**
- Any call to `FFmpegDecoder::Open()`, `decoder_.reset()`, or `SeekPreciseToMs()` reachable from `TryGetFrame()` is a violation.
- `AdvanceToNextSegment()` existing as a callable method is a violation.
- `current_segment_index_` being modified inside `TryGetFrame()` is a violation.

**In logs:**
- `SEGMENT_ADVANCE` or `SEGMENT_DECODER_OPEN` logged from the fill thread's call stack (i.e., from within `FillLoop` → `TryGetFrame`) indicates reactive advancement.

### Classification

**Fatal.** This is the root structural violation. If `TryGetFrame` can perform decoder lifecycle work, the reactive path exists, and all other invariants in this contract can be violated.

---

## INV-SEAM-SEG-003: Eager Arming on Segment Activation

### Statement

**When segment N becomes active, preparation for segment N+1 MUST be armed on the same tick, subject only to "N+1 exists within the block."**

"Armed" means: a prep request has been posted to the seam-prep thread's work queue specifying segment N+1's descriptor, before the tick thread advances to the next frame index. The seam-prep thread may not have started work yet (it processes requests asynchronously), but the request is in the queue.

The arming condition is:

```
current_segment_index_ + 1 < segment_count
```

If true: post prep request for segment N+1. If false (N is the last segment): no-op; the block-level prep handles the transition to the next block.

The trigger fires at exactly these points:

1. After block TAKE rotation makes segment 0 active.
2. After initial block load + fill thread start makes segment 0 active.
3. After PADDED_GAP exit + fill thread start makes segment 0 active.
4. After a segment seam swap makes segment N+1 active.

No other condition — segment duration, segment type, fence proximity, queue state — may delay arming. A 200ms pad segment and a 30-minute content segment both trigger immediate arming.

### Violation Evidence

**In logs:**
- Segment N becoming active (SEGMENT_SEAM_TAKE or BLOCK_START) without a corresponding `SEGMENT_PREP_ARMED` on the same tick (and N+1 exists) indicates delayed arming.

**In metrics:**
- `air_continuous_segment_prep_armed_count` not incrementing in lockstep with segment activations (minus the last segment per block) indicates missed arming.

### Classification

**Fatal.** Delayed arming reduces the overlap window. For short segments, delayed arming produces a zero-length overlap — the same structural deficiency as the reactive model. The invariant requires arming to be unconditional and immediate.

---

## INV-SEAM-SEG-004: Deterministic Seam Tick Computation

### Statement

**The segment seam tick MUST be computed deterministically from block activation frame, segment boundary content time, and rational frame rate. The formula is:**

```
segment_seam_frame = block_activation_frame
                   + ceil(boundary[N].end_ct_ms × fps_num / (fps_den × 1000))
```

**Integer ceil (same pattern as INV-BLOCK-WALLFENCE-001):**

```
segment_seam_frame = block_activation_frame
                   + (boundary[N].end_ct_ms × fps_num + fps_den × 1000 - 1)
                     / (fps_den × 1000)
```

All segment seam ticks for a block MUST be computed at block activation and cached. The computation uses the same `fps_num / fps_den` rational representation as the block fence tick. No floating-point frame-duration accumulation. No millisecond-quantized rounding.

The last segment of a block has no segment seam tick. Its transition is the block fence, owned by INV-BLOCK-WALLFENCE-001.

The unified tick-thread TAKE condition evaluates:

```
next_seam_frame = min(next_segment_seam_frame, block_fence_frame)
take = (session_frame_index >= next_seam_frame)
```

Segment seams always precede the block fence (they are intra-block). The block fence fires for the last segment's end.

### Violation Evidence

**In metrics / logs:**
- Segment seam firing at a frame index that differs from the pre-computed value indicates non-deterministic computation.
- Drift between `segment_seam_frame` and `block_activation_frame + exact_boundary_computation` indicates floating-point accumulation.

**In tests:**
- For a block with known segment boundaries and rational fps, the computed seam ticks must match expected values exactly. No tolerance.

### Classification

**Fatal.** Non-deterministic seam ticks make overlap window sizing unpredictable and make contract tests non-reproducible.

---

## INV-SEAM-SEG-005: Unified Swap Mechanism

### Statement

**Segment seams MUST use the same pointer-swap mechanism as block seams.**

Specifically, a segment seam swap and a block seam swap execute the same code path:

1. Evaluate `session_frame_index >= next_seam_frame_`.
2. Pop frame from incoming buffer (pre-filled by incoming fill thread).
3. Stop outgoing fill thread via `StopFillingAsync`.
4. Rotate incoming → current (move buffer pointers and producer ownership).
5. Update `next_seam_frame_` for the next seam.
6. Arm prep for the subsequent source (segment N+2, or next block).

The only difference between a segment seam and a block seam is post-swap dispatch:
- Segment seam: increment `current_segment_index_`, recompute `next_seam_frame_` from cached `planned_segment_seam_frames_[i]`, arm segment prep.
- Block seam: execute existing block rotation (finalize outgoing block, emit block completion, recompute segment seam frames for the new block), arm block prep.

The swap primitive itself — buffer pointer swap + fill thread lifecycle — is context-blind.

### Violation Evidence

**In code (structural):**
- A segment seam swap path that does not call `StopFillingAsync` on the outgoing buffers, or that performs synchronous decoder work, indicates a divergent mechanism.
- Two separate TAKE evaluation paths (one for segments, one for blocks) that do not share the pointer-swap implementation indicate mechanical divergence.

**In metrics:**
- Asymmetric `max_inter_frame_gap_us` between segment seams and block seams for the same content indicates different swap mechanisms.

### Classification

**Fatal.** INV-SEAM-004 (Mechanical Equivalence) requires one mechanism. This invariant enforces it at the segment level specifically.

---

## INV-SEAM-SEG-006: No Decoder Lifecycle on Fill Thread

### Statement

**The fill thread (`VideoLookaheadBuffer::FillLoop`) MUST NOT call any function that opens, closes, seeks, or probes a decoder.**

The fill thread's permitted operations are:
- `producer_->TryGetFrame()` — decode one frame from an already-open decoder.
- `audio_buffer_->Push()` — push decoded audio.
- Buffer management (wait for space, push to video deque, cadence repeat, hold-last).

The fill thread's forbidden operations are:
- `FFmpegDecoder::Open()`
- `FFmpegDecoder::SeekPreciseToMs()`
- `decoder_.reset()` (or any decoder destruction)
- `std::make_unique<FFmpegDecoder>(...)` (or any decoder construction)
- `AdvanceToNextSegment()` (or any segment transition logic)

When `TryGetFrame()` returns `std::nullopt` because the segment is exhausted, the fill thread enters hold-last mode (repeats last decoded frame, pushes silence to audio buffer). It does NOT open a new decoder. It continues in hold-last until the tick thread fires the seam swap and calls `StopFillingAsync` on the outgoing buffer.

The `content_gap` state in `FillLoop` remains valid for natural content exhaustion within a single segment (content shorter than boundary). It is no longer caused by decoder transitions — those are handled by the pointer swap at the seam tick, which occurs between two separately-filled buffer pairs.

### Violation Evidence

**In code (structural):**
- Any `FFmpegDecoder` method call reachable from `FillLoop` (other than through `TryGetFrame` → `DecodeFrameToBuffer` / `GetPendingAudioFrame`) is a violation.
- `FillLoop` holding a reference to or calling into `AdvanceToNextSegment` is a violation.

**In logs:**
- `SEGMENT_DECODER_OPEN` or `SEGMENT_ADVANCE` logged with a thread ID matching the fill thread indicates the fill thread performed decoder lifecycle work.

### Classification

**Fatal.** The fill thread operating on an already-open decoder is the architectural boundary that enables overlap. If the fill thread can open decoders, it will block on I/O, drain the video/audio buffers, and propagate stalls to the tick thread.

---

## Invariant Relationships

```
INV-SEAM-006 (Eager Preparation — SeamContinuityEngine.md)
     │
     │ enforced by
     ▼
INV-SEAM-SEG-002 (No Reactive Transitions in TryGetFrame)
     │
     ├── INV-SEAM-SEG-003 (Eager Arming) ─── "arm on activation, not exhaustion"
     │        │
     │        └── INV-SEAM-SEG-004 (Deterministic Seam Tick) ─── "when to swap"
     │
     ├── INV-SEAM-SEG-006 (No Decoder Lifecycle on Fill Thread) ─── "fill decodes only"
     │
     ├── INV-SEAM-SEG-005 (Unified Mechanism) ─── "same swap as blocks"
     │
     └── INV-SEAM-SEG-001 (Clock Isolation) ─── "tick thread zero-FFmpeg"
```

INV-SEAM-SEG-002 is the root. If `TryGetFrame` cannot advance segments, then:
- Segment advancement must happen elsewhere → INV-SEAM-SEG-003 (arming) + INV-SEAM-SEG-004 (when).
- The fill thread cannot do decoder work → INV-SEAM-SEG-006.
- The mechanism must be the pointer swap → INV-SEAM-SEG-005.
- The tick thread remains clean → INV-SEAM-SEG-001.

Violation of INV-SEAM-SEG-002 reintroduces the reactive path, cascading to all others.

---

## Summary Table

| ID | Statement | Violation | Classification |
|----|-----------|-----------|----------------|
| **INV-SEAM-SEG-001** | Tick thread does no FFmpeg work at any seam | Late ticks correlated with segment boundaries; inter-frame gap spikes at intra-block transitions | Fatal if systematic |
| **INV-SEAM-SEG-002** | TryGetFrame must not perform decoder lifecycle or segment advancement | AdvanceToNextSegment reachable from TryGetFrame; decoder open/close on fill thread call stack | Fatal |
| **INV-SEAM-SEG-003** | Prep for N+1 armed on same tick as N's activation | Segment activation without SEGMENT_PREP_ARMED on same tick; delayed arming gated on duration/type/fence proximity | Fatal |
| **INV-SEAM-SEG-004** | Seam tick computed from block_activation_frame + rational ceil of boundary.end_ct_ms | Seam tick differs from pre-computed value; floating-point drift between segment transitions | Fatal |
| **INV-SEAM-SEG-005** | Segment seams use same pointer-swap as block seams | Asymmetric swap mechanism; segment seam path missing StopFillingAsync or buffer rotation | Fatal |
| **INV-SEAM-SEG-006** | Fill thread cannot open/close/seek decoders | FFmpegDecoder lifecycle methods reachable from FillLoop; SEGMENT_DECODER_OPEN on fill thread | Fatal |

---

## Required Tests

Tests are in `pkg/air/tests/contracts/BlockPlan/SegmentSeamOverlapContractTests.cpp`.

- T-SEGSEAM-001: NoReactiveAdvancement — `TryGetFrame` returns nullopt at segment boundary; does not call `AdvanceToNextSegment` or modify `current_segment_index_`.
- T-SEGSEAM-002: EagerArmingAtActivation — When segment N becomes active, `SEGMENT_PREP_ARMED` fires on the same tick (or immediately after activation) for segment N+1, if N+1 exists.
- T-SEGSEAM-003: DeterministicSeamTick — For known segment boundaries and rational fps, the computed `segment_seam_frame` matches the expected value exactly. No tolerance. Integer ceil arithmetic verified.
- T-SEGSEAM-004: AudioContinuityAtSegmentSeam — For a multi-segment block with real media, the segment seam swap occurs without audio fallback (`audio_silence_injected == 0`).
- T-SEGSEAM-005: BlockPrepNotStarvedBySegmentPrep — For a multi-segment block followed by a second block, the block-level prep completes before the block fence tick despite concurrent segment prep activity.
- T-SEGSEAM-006: PadSegmentPreparedAndSwapped — A content→pad segment transition uses the same prep→swap mechanism as content→content. The pad segment gets a synthetic FedBlock, is prepared by the seam-prep thread, and is swapped at the seam tick.

---

## Notes

This contract defines structural constraints. It is more prescriptive than the SeamContinuityEngine contract (which defines outcomes only) because the constraints are architectural: they specify which thread may perform which operation. This is necessary because the current violation is architectural — the reactive path exists as code, and its removal requires structural enforcement.

The Segment Continuity Contract (OUT-SEG-001..006) remains in force. The INV-SEAM-SEG-* invariants define HOW those outcomes are achieved for intra-block seams. They are complementary, not competing.

The SeamContinuityEngine contract (INV-SEAM-001..006) remains in force. INV-SEAM-SEG-* is the enforcement layer for INV-SEAM-006 at intra-block segment granularity.
