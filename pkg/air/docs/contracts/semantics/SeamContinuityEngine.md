# Seam Continuity Engine — Invariant Contract

**Classification**: Semantic Contract (Layer 1)
**Owner**: Seam Continuity Engine (logical layer spanning `PipelineManager`, `ProducerPreloader`, `AudioLookaheadBuffer`, `VideoLookaheadBuffer`)
**Derives From**: INV-TICK-GUARANTEED-OUTPUT (Law, Layer 0), Switching Law (Layer 0), Output Liveness Law (Layer 0)
**Governs**: All decoder transitions — segment seams, program block seams, content→pad, pad→content
**Scope**: AIR runtime playout engine
**Adversarial Assumption**: Content is hostile. Assets may have no audio track, truncated containers, mismatched frame rates, broken timestamps, late first packets, or immediate EOF. The seam engine must produce correct output regardless.

---

## Preamble

The Seam Continuity Engine is the logical subsystem responsible for ensuring that decoder lifecycle events — open, probe, seek, first-frame decode, audio prime, close — are never observable from the channel clock's frame of reference.

It is not a component in the traditional sense. It is the *contract surface* that binds the overlap mechanism, the readiness gate, the swap primitive, and the fallback chain into a single set of guarantees. Any code that participates in transitioning from one decode source to another is governed by these invariants.

The term "seam" is used uniformly. There is no distinction between a segment seam (intra-block decoder transition) and a program block seam (inter-block decoder transition) at this layer. Editorial context is invisible. The only input is: a new decode source must become active at a specific tick.

---

## Definitions

- **Seam tick**: The output tick at which the channel clock expects frames from the incoming source. For program block seams, this is the fence tick. For segment seams within a block, this is the tick at which the outgoing segment's content timeline is exhausted.
- **Overlap window**: The interval between the moment the incoming decoder begins preparation and the seam tick. During this window, the outgoing decoder continues producing frames for the tick loop while the incoming decoder prepares in the background.
- **Readiness**: The incoming decoder has produced at least one video frame and accumulated audio samples meeting the prime threshold (configurable, default 500ms) in a buffer accessible to the tick thread without I/O. If the asset has no audio track, the audio buffer is explicitly marked as primed-empty.
- **Prepared swap**: The atomic transition from outgoing source to incoming source at the seam tick. Zero decode work occurs on the tick thread during the swap.
- **Fallback**: Silence injection, pad frame emission, or any output not derived from the intended incoming decode source. Fallback keeps the channel alive but represents a continuity failure.
- **Continuity**: The incoming source's decoded audio and video are emitted at the seam tick. No synthesized, held, or substituted frames are required.
- **Eager preparation**: Decoder preparation for segment N+1 begins when segment N becomes the active source. The overlap window spans the entirety of segment N's playback duration.
- **Reactive preparation**: Decoder preparation for segment N+1 begins when segment N signals exhaustion (EOF, boundary exceeded). The overlap window is zero. This is the failure mode that INV-SEAM-006 prohibits.

---

## Scope

These invariants apply to:

- **Every decoder transition** in a BlockPlan playout session: segment seams
  (intra-block), program block seams (inter-block), content→pad, pad→content.
- **The overlap window** between outgoing and incoming decode sources.
- **The readiness gate** that determines whether the incoming source is ready
  at the seam tick.
- **The prepared swap** that transitions buffer ownership at the seam tick.
- **Fallback selection** when the incoming source is not ready.

These invariants do NOT apply to:

- **Decoder internals** — how frames are decoded, what codec is used, container
  format handling. That is Content Engine responsibility (INV-LOOKAHEAD-BUFFER-AUTHORITY,
  FileProducerContract).
- **Fence tick computation** — when block seams occur. That is Program Block
  Authority (INV-BLOCK-WALLFENCE-001).
- **Segment-exhaustion detection** — when intra-block segment seams occur. That
  is media time authority (INV-AIR-MEDIA-TIME).
- **Tick cadence** — how fast the clock ticks. That is Channel Clock
  (INV-TICK-GUARANTEED-OUTPUT, INV-TICK-DEADLINE-DISCIPLINE-001).
- **Session boot** — the first frame of the first block (governed by
  INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT).
- **Session teardown** — StopChannel terminates; no seam applies.

---

## INV-SEAM-001: Clock Isolation

### Statement

**The channel clock MUST NOT observe, wait for, or be influenced by any decoder lifecycle event.**

Decoder open, probe, seek, first-frame decode, audio accumulation, resampler initialization, and decoder close are producer-side operations. They execute within the overlap window on background threads. The tick thread MUST NOT call, invoke, or block on any operation whose latency depends on decoder state, container format, codec negotiation, or I/O.

At the seam tick, the tick thread performs a prepared swap: it selects the incoming source's pre-filled buffer and pops a frame. If the incoming source is not ready, the tick thread selects fallback. In no case does it wait.

The channel clock's tick cadence is derived solely from the session epoch and rational frame rate. No content event — including decoder failure, EOF, corrupt container, or missing audio — may alter the tick schedule.

### Violation Evidence

**In logs:**
- `max_inter_frame_gap_us` exceeding one frame period (33,333µs at 30fps) at or near a seam tick indicates the tick thread blocked on decoder work.
- `AUDIO_UNDERFLOW_SILENCE` or `FENCE_AUDIO_PAD` appearing on tick N where tick N-1 showed healthy buffer depth suggests a synchronous decoder operation drained time from the tick budget.
- `late_ticks_total` incrementing in a burst coinciding with a `BLOCK_START` or `SEAM_PROOF_FENCE` event indicates decoder startup consumed the tick's time budget.

**In metrics:**
- `air_continuous_max_inter_frame_gap_us` spiking above 2× frame period at block boundaries.
- `air_continuous_late_ticks_total` increasing at a rate correlated with `source_swap_count`.

### Classification

**Fatal if systematic.** A single late tick at a seam is a scheduling jitter event (recoverable). A pattern of late ticks at every seam indicates the tick thread is performing synchronous decoder work — a structural violation that cannot be resolved by tuning. The overlap mechanism is absent or broken.

---

## INV-SEAM-002: Decoder Readiness Before Seam Tick

### Statement

**The incoming decoder MUST achieve readiness before the seam tick arrives.**

Readiness requires:
1. The decoder is open and has successfully probed the container format.
2. At least one video frame has been decoded into a buffer accessible to the tick thread without I/O.
3. Audio samples have been accumulated to at least the prime threshold (configurable, default 500ms) in a buffer accessible to the tick thread without I/O.
4. If the asset has no audio track, or audio decode fails, the audio buffer is explicitly marked as primed-empty so the tick thread can select pad audio without waiting.

The overlap window MUST be sized to accommodate worst-case decoder startup. "Worst case" includes: slow container probe (large moov atom, network seek), codec initialization, first-keyframe search, audio resampler startup, and initial audio accumulation.

If the incoming decoder cannot achieve readiness before the seam tick (unresolvable URI, corrupt container, asset with no decodable content), it MUST signal failure explicitly. The readiness gate MUST NOT hang. The tick thread observes "not ready" and selects fallback — it does not wait for resolution.

### Violation Evidence

**In logs:**
- `INV-PREROLL-READY-001: B NOT PRIMED at fence` indicates the incoming decoder did not achieve readiness before the seam tick.
- `DEGRADED_TAKE` with `prime_depth_ms` below threshold indicates audio priming was insufficient.
- `PADDED_GAP_ENTER` indicates no incoming source was available at all.

**In metrics:**
- `air_continuous_next_preload_failed_total` incrementing.
- `air_continuous_fence_preload_miss_count` incrementing.
- `air_continuous_degraded_take_count` incrementing.
- `air_continuous_padded_gap_count` incrementing.

### Classification

**Recoverable per-instance; fatal if systematic.** A single readiness miss on a corrupt asset is expected — the system falls back to pad and recovers when the next asset loads. Sustained readiness misses on well-formed local assets indicate the overlap window is undersized, the preload trigger is too late, or the prime mechanism is broken. This is a structural deficiency requiring architectural correction.

---

## INV-SEAM-003: Audio Continuity Across Seam

### Statement

**At the seam tick, the tick thread MUST emit audio decoded from the incoming source's real content.**

Audio continuity means: the audio samples emitted at and immediately after the seam tick are decoded from the incoming asset's audio track, resampled to house format, and popped from the incoming source's audio lookahead buffer. They are not synthesized silence, not held-last-frame audio, and not pad.

This invariant is stronger than "audio is produced at every tick" (which is guaranteed by INV-TICK-GUARANTEED-OUTPUT via fallback). This invariant requires that the audio is *real decoded content* — that the overlap mechanism succeeded in priming the incoming audio buffer before the seam tick.

For assets with no audio track, or where the audio track is undecodable, the audio buffer is primed-empty. In this case, pad audio at the seam tick is the correct output (the asset has no audio to provide). This is not a violation — the invariant applies to the decode pipeline's ability to deliver what the asset contains, not to the asset's content.

### Violation Evidence

**In logs:**
- `AUDIO_UNDERFLOW_SILENCE` on the seam tick or within N ticks after it indicates the audio buffer was not primed with incoming content.
- `FENCE_AUDIO_PAD: audio not primed` indicates the incoming audio buffer was empty at the seam tick despite the asset having an audio track.
- `SEAM_PROOF_TICK` with `audio_source=fence_pad` or `audio_source=pad_frame` on ticks immediately following a `SEAM_PROOF_FENCE` where `swapped=1`.

**In metrics:**
- `air_continuous_audio_silence_injected` incrementing at seam boundaries.
- `air_continuous_max_consecutive_audio_fallback_ticks` > 0 for transitions between well-formed assets.

### Classification

**Recoverable.** Audio fallback (silence injection) prevents dead air. The viewer hears a brief gap rather than channel death. However, every fallback tick at a seam is a quality degradation event. A system that achieves audio continuity at zero seams is operating in degraded mode — the overlap mechanism is not delivering its core promise. The bounded fallback KPI (INV-SEAM-005) makes this measurable and actionable.

---

## INV-SEAM-004: Segment/Block Mechanical Equivalence

### Statement

**All decoder transitions MUST use the same prepared-swap primitive, regardless of editorial context.**

The mechanism that transitions from segment A to segment B within a program block MUST be identical to the mechanism that transitions from the last segment of block A to the first segment of block B. Specifically:

1. The incoming decoder is prepared on a background thread during an overlap window.
2. The incoming decoder achieves readiness (video frame + audio prime) before the seam tick.
3. At the seam tick, the tick thread swaps buffer pointers and pops from the incoming buffer.
4. The outgoing decoder is retired asynchronously after the swap.

No transition type may use a synchronous decoder open on the tick thread. No transition type may use a different readiness gate, a different prime threshold, or a different swap mechanism. The only difference between transition types is how the seam tick is determined:
- For program block seams: the wall-clock fence tick (INV-BLOCK-WALLFENCE-001).
- For segment seams within a block: the tick at which the outgoing segment's content timeline is exhausted (media time authority).

**The swap mechanism itself is context-blind.** It receives "swap at tick T from source X to source Y" and executes identically whether T is a fence tick or a segment-exhaustion tick.

### Violation Evidence

**In logs:**
- Any log showing synchronous decoder open/close on the tick thread at a segment seam but not at a block seam (or vice versa) indicates divergent mechanisms.
- `max_inter_frame_gap_us` spiking at segment seams but not at block seams (or vice versa) indicates one path has tick-thread decoder work that the other avoids.

**In metrics:**
- Asymmetric `late_ticks_total` correlation: if late ticks correlate with segment transitions but not block transitions (or vice versa), the two paths have different latency profiles.
- `max_consecutive_audio_fallback_ticks` differing systematically between segment seams and block seams for equivalent content indicates different audio prime mechanisms.

### Classification

**Fatal.** Two mechanisms for the same clock-level event is a structural defect. It creates a testing surface that grows multiplicatively (every content variation × every transition type), makes reasoning about worst-case behavior impossible, and guarantees that one path will be less exercised and therefore less reliable. There is one swap primitive. All transitions use it.

---

## INV-SEAM-005: Bounded Fallback Observability

### Statement

**The system MUST track and expose the distinction between continuity (real decoded audio emitted at seam) and fallback (synthesized audio emitted at seam) as an observable, bounded metric.**

Specifically:

1. `max_consecutive_audio_fallback_ticks` MUST be maintained as a session-lifetime high-water mark of the longest consecutive run of ticks where the audio emitted was not decoded from a real asset. This includes pad silence, underflow silence, and fence-pad silence. It resets to zero on any tick where real decoded audio is successfully popped from the audio buffer.

2. For well-formed local assets with audio tracks, the bounded fallback threshold is N consecutive ticks (configurable, default 5). Exceeding this threshold on a transition between healthy assets is a quality violation — the overlap window or prime mechanism is insufficient.

3. The metric MUST be exposed via the Prometheus text endpoint so that external monitoring can alert on degradation.

4. The metric MUST NOT influence execution. It is a passive observation. The tick loop does not consult the metric, gate on it, or change behavior based on its value. It is purely diagnostic.

5. Fallback at every seam is distinguishable from fallback at no seam. A system where `max_consecutive_audio_fallback_ticks == 0` has achieved perfect audio continuity across all transitions. A system where the metric exceeds the threshold has a measurable, bounded quality deficiency. There is no ambiguous middle ground.

### Violation Evidence

**In logs:**
- No explicit violation log for this invariant. The metric itself IS the observability mechanism. Its absence (metric not tracked, not exposed, or always zero despite known fallback events) is the violation.

**In metrics:**
- `air_continuous_max_consecutive_audio_fallback_ticks` not present in Prometheus output → invariant violated (metric not tracked).
- `air_continuous_audio_silence_injected > 0` but `air_continuous_max_consecutive_audio_fallback_ticks == 0` → counter logic is broken; silence was injected but fallback ticks were not counted.
- `air_continuous_max_consecutive_audio_fallback_ticks` consistently above threshold for transitions between well-formed local assets → overlap mechanism is structurally insufficient.

### Classification

**Recoverable (metric absence is fatal).** The metric being high is a quality signal, not a runtime failure. But the metric not existing, or being disconnected from reality, is fatal to the contract — it eliminates the system's ability to distinguish continuity from fallback, which is the entire purpose of this invariant. Without it, the system cannot know whether it is achieving broadcast-grade transitions or papering over failures with silence.

---

## INV-SEAM-006: Eager Decoder Preparation

### Statement

**Decoder preparation for segment N+1 MUST begin no later than the tick where segment N becomes active. Segment duration, segment type (content, filler, pad), and block boundaries MUST NOT delay preparation. Overlap is eager, not reactive.**

The overlap window for a seam begins at the moment the preceding segment becomes the active decode source — not when that segment approaches exhaustion, not when EOF is detected, and not when the fill thread runs out of frames. The entire duration of segment N is available as overlap window for segment N+1's preparation. The system MUST use this window.

This applies uniformly to all transition types:

1. **Intra-block segment seams**: When segment 0 of a block becomes the active source, preparation for segment 1 MUST begin immediately. When segment 1 becomes active, preparation for segment 2 begins. The segment's content type (content, filler, pad) does not affect when preparation starts.

2. **Inter-block program seams**: When block A's first segment becomes active, preparation for block B MUST begin no later than the moment the block queue provides B's descriptor. (This is the existing `ProducerPreloader` behavior — it is already eager for blocks.)

3. **Cross-boundary seams**: The last segment of block A triggers preparation for the first segment of block B. This is a combination of (1) and (2) — block B's preloader arms eagerly, and within block B the segment pipeline arms eagerly.

The distinction between "eager" and "reactive" is critical:

- **Eager**: Preparation starts when the predecessor becomes active. The overlap window equals the predecessor's entire playback duration. A 30-second predecessor gives 30 seconds of overlap. A 500ms predecessor gives 500ms. The window is maximized by construction.

- **Reactive**: Preparation starts when the predecessor signals exhaustion (EOF, boundary check, asset duration exceeded). The overlap window is zero. The incoming decoder must open, probe, seek, and prime audio with no time budget. This is a synchronous stall on whatever thread detects exhaustion.

A system that uses reactive preparation for any transition type cannot satisfy INV-SEAM-002 (Decoder Readiness) or INV-SEAM-003 (Audio Continuity) for segments shorter than decoder startup latency. A 200ms filler segment with a 300ms decoder startup will always produce a gap under reactive preparation. Under eager preparation, the filler's decoder was ready before the filler became active — it was prepared during the predecessor's playback.

### Violation Evidence

**In logs:**
- `SEGMENT_ADVANCE` followed immediately by `SEGMENT_DECODER_OPEN` on the fill thread indicates reactive preparation — the decoder was opened at the moment of transition, not in advance.
- `SEGMENT_EOF: ADVANCE_TO_NEXT_SEGMENT` triggering synchronous `FFmpegDecoder::Open()` + `SeekPreciseToMs()` indicates zero overlap window — the fill thread stalled on decoder I/O at the exhaustion point.
- `AUDIO_UNDERFLOW_SILENCE` at or immediately after a segment boundary within a block indicates the audio buffer drained during synchronous segment-to-segment decoder transition. Under eager preparation, the incoming segment's audio would be primed before the seam tick.
- `content_gap` state in `VideoLookaheadBuffer::FillLoop()` with hold-last frames emitted at segment transitions indicates the fill thread had no frames from the incoming segment — because the incoming decoder was not open yet.

**In metrics:**
- `air_continuous_max_inter_frame_gap_us` spiking at intra-block segment boundaries but not at inter-block boundaries indicates divergent preparation strategies: eager for blocks, reactive for segments.
- `air_continuous_audio_silence_injected` incrementing at segment seams within blocks where both segments have audio tracks indicates audio continuity failure caused by reactive segment preparation.
- `air_continuous_max_consecutive_audio_fallback_ticks` elevated for intra-block transitions but zero for inter-block transitions indicates asymmetric overlap windows.

**In code (structural):**
- Any call to `FFmpegDecoder::Open()`, `FFmpegDecoder::SeekPreciseToMs()`, or `decoder_.reset()` from within `TryGetFrame()` or the `FillLoop()` call chain is a structural violation. These are decoder lifecycle operations that MUST occur on a preparation thread during the overlap window, not on the fill thread at the moment of segment exhaustion.
- Any segment transition path that does not have a corresponding pre-positioned, ready-to-swap incoming source is structurally violating this invariant.

### Classification

**Fatal.** Reactive segment preparation is not a tuning problem. No amount of buffer sizing, audio target adjustment, or cadence configuration can compensate for a zero-length overlap window. The deficiency is structural: the code path that handles intra-block segment transitions does not use the overlap primitive. It performs synchronous decoder I/O on the fill thread. This directly causes INV-SEAM-001 violations (fill thread stall propagates to tick thread via buffer underflow), INV-SEAM-003 violations (audio buffer drains during stall), and INV-SEAM-004 violations (segment seams use a different mechanism than block seams). The invariant is either satisfied by architecture or it is not.

---

## Invariant Relationships

```
Layer 0 (Law)
  INV-TICK-GUARANTEED-OUTPUT ──── "every tick emits something"
  Output Liveness Law ─────────── "no dead air, ever"
  Switching Law ───────────────── "no gaps, no PTS regression"
       │
       │ refines
       ▼
Layer 1 (Seam Continuity Engine)
  INV-SEAM-006 (Eager Preparation) ─── "overlap starts NOW, not at exhaustion"
       │
       │ enables
       ▼
  INV-SEAM-001 (Clock Isolation)
       │
       ├── INV-SEAM-002 (Decoder Readiness) ─── "ready BEFORE seam tick"
       │        │
       │        └── INV-SEAM-003 (Audio Continuity) ─── "real audio AT seam tick"
       │
       ├── INV-SEAM-004 (Equivalence) ─── "one mechanism, all seams"
       │
       └── INV-SEAM-005 (Observability) ─── "measure the gap"
```

INV-SEAM-006 is the precondition for the entire invariant tree. Without eager preparation, the overlap window is zero, and no amount of buffer tuning can satisfy INV-SEAM-002 for short segments. INV-SEAM-006 guarantees the overlap window exists; INV-SEAM-001 through INV-SEAM-005 define what the system must achieve within that window.

INV-SEAM-001 is the root of the runtime invariants. If the clock is isolated from decoders, then readiness must be achieved before the clock arrives at the seam (INV-SEAM-002). If readiness is achieved, audio continuity follows (INV-SEAM-003). If the mechanism is uniform (INV-SEAM-004), all seams inherit the same guarantees. If the distinction between success and failure is observable (INV-SEAM-005), the system can be monitored and improved.

Violation of INV-SEAM-006 cascades to INV-SEAM-001 through INV-SEAM-004 for any segment shorter than decoder startup latency. Violation of INV-SEAM-001 cascades to all runtime invariants. Violation of INV-SEAM-002 cascades to INV-SEAM-003. Violation of INV-SEAM-004 means guarantees are partial. Violation of INV-SEAM-005 means violations of the others are invisible.

---

## Summary Table

| ID | Statement | Violation | Classification |
|----|-----------|-----------|----------------|
| **INV-SEAM-001** | Channel clock must not observe decoder lifecycle events | Late ticks correlated with seam events; inter-frame gap spikes at boundaries | Fatal if systematic |
| **INV-SEAM-002** | Incoming decoder must achieve readiness before seam tick | Preload miss at fence; degraded TAKE; PADDED_GAP entry | Recoverable per-instance; fatal if systematic |
| **INV-SEAM-003** | Real decoded audio must be emitted at seam tick | Silence injection at seam; fallback ticks > 0 on well-formed assets | Recoverable |
| **INV-SEAM-004** | All decoder transitions use identical prepared-swap primitive | Asymmetric latency profiles between segment seams and block seams | Fatal |
| **INV-SEAM-005** | Fallback vs. continuity distinction must be observable and bounded | Metric absent, disconnected from reality, or consistently above threshold | Recoverable (absence is fatal) |
| **INV-SEAM-006** | Decoder preparation begins when predecessor becomes active, not at exhaustion | Synchronous decoder open on fill thread at segment boundary; `AdvanceToNextSegment` calling `FFmpegDecoder::Open()` reactively | Fatal |

---

## Required Tests

- T-SEAM-001: ClockIsolation — Inter-frame gap must not spike at seam tick with adversarial content (slow-probe asset)
- T-SEAM-002: DecoderReadiness — Incoming decoder achieves readiness before fence tick for well-formed local assets
- T-SEAM-003: AudioContinuity — Real decoded audio emitted at seam tick (not silence) for assets with audio tracks
- T-SEAM-004: MechanicalEquivalence — Segment seams and block seams produce identical latency profiles
- T-SEAM-005: BoundedFallbackObservability — `max_consecutive_audio_fallback_ticks` is tracked, exposed, and bounded for healthy transitions
- T-SEAM-006: EagerPreparation — For a multi-segment block, segment N+1's decoder must be ready before segment N exhausts; no `FFmpegDecoder::Open()` on the fill thread at segment boundaries

---

## Notes

This contract defines outcomes only. Implementation strategy is intentionally unspecified.

The Seam Continuity Engine is a Layer 1 semantic contract. It refines the Layer 0 laws (INV-TICK-GUARANTEED-OUTPUT, Switching, Output Liveness) by defining what "correct" means specifically at decoder transitions. It does not override them — INV-TICK-GUARANTEED-OUTPUT still guarantees something goes out even when all seam invariants are violated.

The OUT-SEG-* outcomes in the Segment Continuity Contract remain in force. The INV-SEAM-* invariants formalize the decoder-overlap model that the OUT-SEG-* outcomes require. They are complementary, not competing.
