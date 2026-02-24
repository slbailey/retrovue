# RetroVue AIR System Invariants

**Status:** Active Consolidated Reference  
**Date:** 2026-02-23  
**Purpose:** Single authoritative document for all system invariants

This document consolidates all INV-* invariant files from the RetroVue AIR codebase.
Individual INV-* files have been archived; this is the canonical reference.

---

## Table of Contents

1. [Coordination Layer Invariants](#coordination-layer-invariants)
2. [Semantic Layer Invariants](#semantic-layer-invariants)
3. [Execution Layer Invariants](#execution-layer-invariants)
4. [Broadcast-Grade Guarantees](#broadcast-grade-guarantees)

---

## Coordination Layer Invariants

### INV-BLOCK-WALLCLOCK-FENCE-001: Deterministic Block Fence from Rational Timebase

**Owner:** PipelineManager  
**Phase:** Every block boundary in a BlockPlan session  
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, LAW-OUTPUT-LIVENESS

Block transitions in a BlockPlan session MUST be driven by a precomputed fence tick derived from the block's UTC schedule and the session's rational output frame rate. The fence tick is an absolute session frame index, computed once at block-load time and immutable thereafter.

**Canonical Fence Formula:**
```
delta_ms   = end_utc_ms - session_epoch_utc_ms
fence_tick = (delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)
```

**Key Rules:**
- Fence tick is the first tick of the NEXT block
- TAKE selects B's buffers when `session_frame_index >= fence_tick`
- Content time, decoder state, and runtime clocks are never timing authority
- BlockCompleted is a consequence, not a gate

---

### INV-BLOCK-FRAME-BUDGET-AUTHORITY: Frame Budget as Counting Authority

**Owner:** PipelineManager / TickProducer  
**Depends on:** INV-BLOCK-WALLFENCE-001

The block frame budget MUST be computed as:
```
remaining_block_frames = fence_tick - block_start_tick
```

**Key Rules:**
- Budget is counting authority, NOT timing authority
- One frame = one decrement (includes freeze/pad frames)
- Budget reaching 0 is verification, NOT the swap trigger
- Segments must consult remaining budget before emitting

---

### INV-BLOCK-LOOKAHEAD-PRIMING: Look-Ahead Priming at Block Boundaries

**Owner:** ProducerPreloader / TickProducer / PipelineManager  
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT

The first video frame and its audio MUST be decoded before the producer signals readiness. Priming ensures zero decode latency on the fence tick.

**Key Rules:**
- Decoder ready before fence tick
- Zero deadline work at fence tick (frame from memory)
- No duplicate decoding (consume primed frame exactly once)
- Priming failure degrades safely (fall through to live decode or pad)

---

### INV-LOOKAHEAD-BUFFER-AUTHORITY: Lookahead Buffer Decode Authority

**Owner:** PipelineManager, VideoLookaheadBuffer, AudioLookaheadBuffer  
**Phase:** Every output tick

AIR MUST decouple all decode operations from the tick emission thread. Decode runs on dedicated background fill threads.

**Video Lookahead Rules:**
- Tick thread MUST NOT call decode APIs after fill thread starts
- Fill thread maintains target depth; waits on condition variable when full
- `TryPopFrame()` returns false on underflow; NEVER injects substitute data
- Fence transitions: StopFilling(flush), StartFilling(consume primed frame)

**Audio Lookahead Rules:**
- Audio decode is side-effect of video decode (FrameData contains audio)
- `TryPopSamples()` returns false on insufficient samples
- No silence injection by the buffer itself
- Audio buffer NOT flushed at fence (preserves continuity)

---

### INV-FENCE-FALLBACK-SYNC-001: Mandatory Synchronous Queue Drain at Fence

**Owner:** PipelineManager  
**Phase:** Every fence tick  
**Depends on:** OUT-BLOCK-005, INV-BLOCK-WALLFENCE-001, INV-RUNWAY-MIN-001

When fence fires and preview block NOT ready, AND queue non-empty:
1. Pop block from queue
2. Emit BlockStarted (credit to Core)
3. Synchronously load via AssignBlock()
4. Install as live producer
5. Start buffer filling

This path is unconditional (no feature flag).

---

### INV-FENCE-TAKE-READY-001: Fence Take Readiness and DEGRADED_TAKE_MODE

**Owner:** PipelineManager  
**Layer:** Coordination / Broadcast-grade take

At fence tick, if next block's first segment is CONTENT, system must satisfy:
1. Preview buffer primed to threshold, OR
2. DEGRADED_TAKE_MODE active (hold last committed A frame + silence)

**DEGRADED_TAKE_MODE:**
- Video: hold last committed A frame
- Audio: silence
- Ticks continue normally (no skip)
- Exit when B primed and pop succeeds
- After HOLD_MAX_MS (5s), escalate to standby (pad/slate)

---

### INV-PREROLL-OWNERSHIP-AUTHORITY: Preroll Arming and Fence Swap Coherence

**Owner:** PipelineManager  
**Phase:** Every block boundary  
**Depends on:** INV-BLOCK-WALLFENCE-001, INV-BLOCK-LOOKAHEAD-PRIMING

Preroll arming authority MUST align with "next block" authority that fence swap uses. The committed successor block is the block in the B slot at TAKE time.

**Key Rules:**
- Committed successor = single source of truth for "which block is next"
- Set when preloaded result taken into preview slot (TakeBlockResult)
- NOT set when block popped from queue and submitted to preloader
- Fail closed on mismatch: log violation, continue with correct session block

---

### INV-DETERMINISTIC-UNDERFLOW-AND-TICK-OBSERVABILITY: Underflow Policy and Tick Lateness

**Owner:** PipelineManager, VideoLookaheadBuffer  
**Phase:** Every output tick  
**Depends on:** INV-LOOKAHEAD-BUFFER-AUTHORITY, INV-TICK-DEADLINE-DISCIPLINE-001

When lookahead buffer cannot supply a frame, system MUST behave deterministically: emit freeze/pad using deterministic policy. Underflow is controlled state transition with enriched observability.

**Key Rules:**
- Deterministic underflow behavior (freeze or PADDED_GAP, no random stall spiral)
- Enriched underflow log includes: low_water, target, depth_at_event, lateness_ms
- Tick lateness observable (per-tick deadline/start/end, lateness_ms, p95/p99 metrics)
- No nondeterministic sleeps in underflow path

---

### INV-P10-PIPELINE-FLOW-CONTROL: Phase 10 Flow Control Invariants

**Owner:** All Producers, PipelineManager, VideoLookaheadBuffer, AudioLookaheadBuffer  
**Status:** IMPLEMENTED

**Cardinal Rule (DOCTRINE):**
> "Slot-based flow control eliminates sawtooth stuttering.  
> Hysteresis with low-water drain is the pattern that causes bursty delivery."

**Core Requirements:**
1. **Realtime throughput:** Output matches target FPS ± 1%; no cumulative drift
2. **Symmetric backpressure:** Audio and video throttled together
3. **Slot-based decode gate:** Block at capacity, unblock when one slot frees (no hysteresis)
4. **Producer throttle:** Decode rate governed by consumer capacity
5. **Frame drop policy:** Drops forbidden unless explicit conditions met
6. **Buffer equilibrium:** Depth oscillates around target, not unbounded growth

**Producer Contract:**
- Flow control gate BEFORE packet read/frame generation
- Backpressure symmetric in time-equivalent units
- No hidden queues between decode and push
- Video through TimelineController; audio uses sample clock
- Muxer uses producer-provided CT (no local CT counters)
- PCR-paced mux (time-driven, not availability-driven)
- No silence injection once PCR pacing starts
- Frame-indexed execution (not time-based)

---

## Semantic Layer Invariants

### INV-AIR-MEDIA-TIME: Media Time Authority Contract

**Owner:** TickProducer  
**Phase:** Runtime

Block execution and segment transitions MUST be governed by decoded media time, not by output cadence, guessed frame durations, or rounded FPS math.

**Core Rules:**
1. **Media Time Authority:** `decoded_media_time >= block_end_time` triggers completion
2. **No Cumulative Drift:** `|T_decoded(n) - T_expected(n)| <= epsilon` (bounded to one frame period)
3. **Fence Alignment:** Decoder EOF, fence, and transition converge within one tick window
4. **Cadence Independence:** Output cadence affects frame repetition, never media time advancement
5. **Pad Never Primary:** Padding only when `decoded_media_time >= block_end_time`

---

### INV-FPS-RATIONAL-001: Rational FPS as Single Authoritative Timebase

**Status:** Broadcast-grade invariant

RationalFps is the ONLY authoritative representation of frame rate in the playout pipeline. Floating-point arithmetic is FORBIDDEN in any timing or scheduling path.

**Hard Rules:**
1. **Canonical Rational:** All FPS stored as irreducible `(num, den)` pairs
2. **No Floating-Point Timing:** No float/double in: DROP detection, cadence, frame duration, fence, budget, tick scheduling
3. **Integer Arithmetic:** Use 64-bit minimum; `__int128` for cross-multiplication
4. **Output FPS Rational:** Channel output FPS stored/transported as rational end-to-end
5. **Cadence Integer-Based:** No floating accumulators
6. **Tick Grid Authority:** Session tick grid derives from RationalFps only

**Forbidden Patterns:**
- `double fps`, `float fps`
- `1.0 / fps`
- `ceil(delta_ms / FrameDurationMs())` (use canonical helpers)
- Tolerance comparisons (`abs(a - b) < 0.001`)
- `ToDouble()` in hot paths
- Any floating literal in hot-path code (`1.0`, `1e6`, `1000.0`)

---

### INV-FPS-MAPPING: Source→Output Frame Authority

**Owner:** TickProducer, VideoLookaheadBuffer  
**Related:** INV-FPS-RESAMPLE, INV-FPS-TICK-PTS

For any segment where `input_fps ≠ output_fps`, engine MUST select source frames using exactly one of: OFF, DROP, or CADENCE. Mode MUST be determined by rational comparison only.

**Required Mappings:**
- 30→30: OFF (equality)
- 60→30: DROP (step=2)
- 120→30: DROP (step=4)
- 23.976→30: CADENCE (non-integer ratio)

**DROP Duration Invariant:** Returned output frame duration = output tick duration (1/output_fps), NOT input frame duration.

**DROP Audio:** All `step` input frames must contribute decoded audio. Audio production MUST NOT be reduced in DROP mode.

**Rational Detection:**
```
if (in_num * out_den == out_num * in_den) → OFF
else if ((in_num * out_den) % (out_num * in_den) == 0) → DROP
else → CADENCE
```

---

### INV-FPS-RESAMPLE: FPS Resample Authority Contract

**Owner:** FileProducer, TickProducer, OutputClock

Input media time, output session time, and resample rule are THREE SEPARATE AUTHORITIES.

**Output Timing Formulas:**
- Output tick time: `tick_time_us(n) = floor(n * 1_000_000 * fps_den / fps_num)`
- Block CT: `ct_ms(k) = floor(k * 1000 * fps_den / fps_num)`
- Use integer math, 128-bit intermediates if needed

**Outlawed Patterns:**
- Tick grid from rounded interval + accumulation
- Frame duration from `int(1000/fps)`
- Any accumulated time using rounded steps
- `+= frame_duration_ms` or `+= interval_us`

**Resample Rule:** For output tick n, choose source frame covering `tick_time_us(n)`. Output PTS = tick time (grid), NOT source PTS.

---

### INV-FPS-TICK-PTS: Output PTS Owned by Tick Grid

**Owner:** TickProducer, PipelineManager

In all modes (OFF, DROP, CADENCE), output video PTS MUST advance by exactly one output tick per returned frame.

**Key Rules:**
- Each returned frame has video.metadata.pts = output tick PTS for that frame index
- PTS delta = tick duration (NOT input frame duration in DROP)
- Muxer uses OutputClock::FrameIndexToPts90k (not returned frame metadata.pts for pacing)
- In DROP: TickProducer overwrites decoder PTS with output tick PTS before return

---

### INV-AUDIO-PTS-HOUSE-CLOCK-001: Audio PTS Owned by House Sample Clock

**Owner:** PipelineManager, MpegTSOutputSink, EncoderPipeline  
**Phase:** Every audio frame encoded / muxed  
**Depends on:** Clock Law (Layer 0), LAW-OUTPUT-LIVENESS, INV-FPS-TICK-PTS  
**Status:** Active

Audio PTS used for encoding and transport MUST be derived from the session's **house sample clock**, not from decoder/content PTS.

**Core Rule:**
- Audio encode PTS is a pure function of **samples emitted**, anchored to an origin:

  `audio_pts_90k = floor((audio_samples_emitted - origin_audio_samples) * 90000 / house_sample_rate)`

- `house_sample_rate` is the channel house audio sample rate (e.g., 48 kHz).

**Hard Rules:**
1. **Single authority:** No output path may use `AudioFrame.pts_us` (or any decoder/container PTS) as the transport PTS.
2. **Monotonicity:** Audio PTS MUST be strictly increasing for successive encoded audio frames that contain samples. Zero-sample frames MUST NOT be encoded.
3. **Alignment:** The audio sample-clock origin MUST be aligned to the session epoch used by video PTS derivation. Audio and video PTS MUST converge to the same transport timeline.
4. **Resample-safe:** DROP/CADENCE and segment seams MUST NOT change audio PTS authority or pacing.
5. **Diagnostic-only content PTS:** Decoder/content PTS may be retained for observability only; it MUST NOT affect mux timing.

**Why:** Decoder/content PTS is not stable under resample, truncation, pad insertion, fence swaps, and segment seams. Using it as transport timing creates dual-clock drift, PCR instability, stutter, and perceived slow-motion under mixed-FPS content.

**What this invariant forces:** MpegTSOutputSink MUST NOT use `audio_frame.pts_us` as encode PTS. Both output paths (PipelineManager and MpegTSOutputSink) MUST use the same house sample-clock timing model. This invariant ensures deterministic audio timing across all output paths and resample modes.

---

### INV-AIR-SEGMENT-IDENTITY-AUTHORITY: UUID-Based Segment Identity

**Owner:** PipelineManager / EvidenceEmitter / AsRunReconciler  
**Phase:** Every AIR event emission

Segment identity MUST be carried by UUID assigned at block feed time. `segment_index` is display-order only and MUST NOT be used as identity key.

**Key Rules:**
1. Segment UUID is execution identity (assigned at block feed, immutable)
2. Asset UUID explicit for CONTENT/FILLER; null for PAD
3. Reporting is UUID-driven (no positional lookup fallback)
4. JIP does not change identity (UUID/asset unchanged; index may change)
5. Event completeness (every SEG_START/AIRED has block_id, segment_uuid, segment_type, asset_uuid)

**Forbidden:** `segments[segment_index]` as identity, DB index lookup, adjacency inference.

---

### INV-AUDIO-LIVENESS: Audio Servicing Decoupled From Video Backpressure

**Owner:** FileProducer, VideoLookaheadBuffer, AudioLookaheadBuffer

**INV-AUDIO-LIVENESS-001:**  
During CONTENT playback with audio enabled, video queue backpressure MUST NOT prevent ongoing audio servicing.

Video saturation may block video enqueues but MUST NOT halt:
- Demux servicing for audio packets
- Audio decoder draining
- Audio frame production

**INV-AUDIO-LIVENESS-002:**  
AUDIO_UNDERFLOW_SILENCE is transitional, NOT steady-state. Continuous silence injection across sustained CONTENT playback indicates liveness violation.

---

### INV-AUDIO-PRIME-002: Prime Frame Must Carry Audio

**Owner:** TickProducer, VideoLookaheadBuffer

If asset has audio stream, after PrimeFirstTick completes, the first frame (primed frame) MUST include at least one audio packet, or system must not treat buffer as ready until audio present.

Prevents "primed video but audio_count=0" false-ready condition that causes AUDIO_UNDERFLOW_SILENCE at cold start.

---

### INV-SEAM-AUDIO-GATE: Segment Seam Audio Gating

**Scope:** Segment seam transition when `take_segment=true` before `SEGMENT_TAKE_COMMIT`

**INV-SEAM-AUDIO-001:**  
Tick loop MUST NOT consume from Segment-B audio buffer until `SEGMENT_TAKE_COMMIT` succeeds.

**INV-SEAM-GATE-001:**  
Gate measurements taken on buffer not being drained by live consumer unless commit occurred.

---

## Execution Layer Invariants

### INV-TICK-GUARANTEED-OUTPUT: Every Tick Emits Exactly One Frame

**Owner:** MpegTSOutputSink / MuxLoop  
**Phase:** All phases after first frame  
**Priority:** ABOVE all other invariants

**Fallback Chain:**
1. Real frame (dequeue from video queue)
2. Freeze (re-emit last frame)
3. Black (pre-allocated black frame)

No conditional, timing check, or diagnostic can prevent emission.

**Philosophy:** CONTINUITY > CORRECTNESS. Dead air is regulatory violation. Wrong frame is production issue.

---

### INV-TICK-DEADLINE-DISCIPLINE-001: Hard Deadline Discipline for Output Ticks

**Owner:** PipelineManager  
**Phase:** Every output tick  
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, LAW-OUTPUT-LIVENESS

Each output tick N is a hard scheduled deadline:
```
spt(N) = session_epoch_utc + N * fps_den / fps_num
```

**Requirements:**
1. One tick per frame period (no slip)
2. Late ticks MUST still emit (fallback allowed)
3. No catch-up bursts
4. Fence checks remain tick-index authoritative even when late
5. Drift-proof anchoring (slow tick does NOT shift future tick deadlines)

---

### INV-TICK-MONOTONIC-UTC-ANCHOR-001: Monotonic Deadline Enforcement

**Owner:** PipelineManager  
**Phase:** Every output tick  
**Depends on:** Clock Law, INV-TICK-DEADLINE-DISCIPLINE-001

Tick deadlines anchored to session UTC epoch, but implemented using monotonic clock to avoid NTP step breakage.

At session start, capture:
- `session_epoch_utc_ms` (UTC wall-clock authority)
- `session_epoch_mono_ns` (monotonic anchor)

Monotonic deadline:
```
deadline_mono_ns(N) = session_epoch_mono_ns + round_rational(N * 1e9 * fps_den / fps_num)
```

Late if: `now_mono_ns >= deadline_mono_ns(N)`

---

### INV-EXECUTION-CONTINUOUS-OUTPUT-001: Continuous Output Execution Model

**Owner:** PipelineManager  
**Phase:** Session lifetime (continuous_output mode)

When execution_model=continuous_output, the session MUST satisfy:

1. Session runs in continuous_output
2. Tick deadlines anchored to session epoch + rational output FPS
3. No segment/block/decoder lifecycle event may shift tick schedule
4. Underflow handling may repeat/black; tick schedule remains fixed
5. Tick cadence (grid) fixed by session RationalFps; frame-selection cadence may refresh

---

### INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT: Decodable Output Within 500ms

**Owner:** MpegTSOutputSink / ProgramOutput  
**Phase:** From AttachStream success

After `AttachStream` succeeds, AIR MUST emit decodable MPEG-TS within 500ms, using fallback video/audio if real content not yet available.

**Layers:**
1. **ProgramOutput:** Wait up to 500ms for first real content; emit pad if expires
2. **MuxLoop:** Wait up to 500ms for first frame to initialize timing; initialize synthetically if expires

---

### INV-SINK-NO-IMPLICIT-EOF: Continuous Output Until Explicit Stop

**Owner:** MpegTSOutputSink / MuxLoop

After `AttachStream` succeeds, sink MUST continue emitting TS packets until:
1. StopChannel RPC
2. DetachStream RPC
3. Slow-consumer detach
4. Fatal socket error

**Forbidden Termination Causes:**
- Producer EOF
- Empty queues
- Decode errors
- Segment boundaries
- Content deficit

---

### INV-PAD-PRODUCER: Pad as First-Class TAKE-Selectable Source

**Owner:** PipelineManager  
**Phase:** Every output tick  
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, INV-BLOCK-WALLFENCE-001

PadProducer is first-class source participating in TAKE source selection. Produces black video (ITU-R BT.601: Y=16, Cb=Cr=128) and silent audio in session program format, unconditionally.

**Key Rules:**
1. **Unconditional availability:** Always ready, no exhaustion, zero latency
2. **Session-format conformance:** Matches program format exactly
3. **Deterministic content:** Fixed black+silence (ITU-R BT.601)
4. **Timestamp from session frame index:** `pts = session_frame_index * frame_duration`
5. **TAKE-selectable with recorded identity:** commit_slot='P', is_pad=true, asset_uri sentinel
6. **TAKE priority:** Content first, then freeze, then PadProducer
7. **Content-before-pad gate:** No pad until first real frame committed
8. **Session lifetime:** Not block-affiliated, exists session-lifetime
9. **Zero-cost transition:** Select/deselect within single tick

**Audio-only exception (FENCE_AUDIO_PAD):** At fence tick, if incoming audio buffer not primed, PipelineManager MAY inject silence for that tick's audio only. Does not affect video source selection.

---

### INV-NO-FLOAT-FPS-TIMEBASE-001: No Floating FPS Timebase in Runtime

**Owner:** All runtime code under pkg/air/src and pkg/air/include

Output timing math MUST use RationalFps (fps_num / fps_den). Runtime code MUST NOT compute frame/tick durations via float-derived formulas.

**Forbidden in runtime:**
- `1'000'000.0 / fps`, `1'000'000 / fps`, `1e6 / fps` for duration
- `round(1e6 / fps)`, `round(1'000'000 / fps)` for duration
- Any expression computing duration by dividing million by floating FPS

**Allowed:**
- `RationalFps::FrameDurationUs()`, `FrameDurationNs()`, `FrameDurationMs()`
- Integer formulas: `(n * 1'000'000 * fps_den) / fps_num`
- `DeriveRationalFPS(double_fps)` then `fps.FrameDurationUs()`

---

## Broadcast-Grade Guarantees

### LAW-OUTPUT-LIVENESS

TS packets must flow continuously. Stalls >500ms indicate failure.

**Source:** `PlayoutInvariants-BroadcastGradeGuarantees.md` (laws/)

---

### Clock Law (Layer 0)

MasterClock is sole time authority. Content clock is not MasterClock and must not be source of "now" for transition decisions.

PTS correctness measured against MasterClock, not wall clock.

---

## Cross-References and Dependencies

### Dependency Graph (Key Relationships)

```
LAW-OUTPUT-LIVENESS
    ├─→ INV-TICK-GUARANTEED-OUTPUT (parent)
    │       ├─→ INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT
    │       ├─→ INV-SINK-NO-IMPLICIT-EOF
    │       └─→ INV-PAD-PRODUCER (mechanism)
    ├─→ INV-TICK-DEADLINE-DISCIPLINE-001
    │       ├─→ INV-TICK-MONOTONIC-UTC-ANCHOR-001
    │       └─→ INV-EXECUTION-CONTINUOUS-OUTPUT-001
    └─→ INV-BLOCK-WALLFENCE-001 (timing authority)
            ├─→ INV-BLOCK-FRAME-BUDGET-AUTHORITY (counting)
            ├─→ INV-BLOCK-LOOKAHEAD-PRIMING (latency)
            ├─→ INV-FENCE-FALLBACK-SYNC-001
            ├─→ INV-FENCE-TAKE-READY-001
            └─→ INV-PREROLL-OWNERSHIP-AUTHORITY

Clock Law
    ├─→ INV-AIR-MEDIA-TIME (media time semantics)
    ├─→ INV-FPS-RATIONAL-001 (timebase authority)
    │       ├─→ INV-NO-FLOAT-FPS-TIMEBASE-001
    │       ├─→ INV-FPS-RESAMPLE
    │       ├─→ INV-FPS-MAPPING
    │       ├─→ INV-FPS-TICK-PTS
    │       └─→ INV-AUDIO-PTS-HOUSE-CLOCK-001
    └─→ INV-TICK-MONOTONIC-UTC-ANCHOR-001

INV-LOOKAHEAD-BUFFER-AUTHORITY
    ├─→ INV-DETERMINISTIC-UNDERFLOW-AND-TICK-OBSERVABILITY
    └─→ INV-P10-PIPELINE-FLOW-CONTROL
            ├─→ INV-AUDIO-LIVENESS
            ├─→ INV-AUDIO-PRIME-002
            └─→ INV-SEAM-AUDIO-GATE
```

---

## Document History

- **2026-02-23:** Initial consolidation of all INV-* files
- Individual INV-* files archived to `/pkg/air/docs/archive/invariants/`
- Source files consolidated from:
  - `/pkg/air/docs/contracts/` (root level invariants)
  - `/pkg/air/docs/contracts/coordination/` (coordination layer)
  - `/pkg/air/docs/contracts/semantics/` (semantic layer)
