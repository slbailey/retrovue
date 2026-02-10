# INV-LOOKAHEAD-BUFFER-AUTHORITY: Lookahead Buffer Decode Authority

**Classification:** INVARIANT (Coordination — Broadcast-Grade)
**Owner:** PipelineManager, VideoLookaheadBuffer, AudioLookaheadBuffer
**Enforcement Phase:** Every output tick within a BlockPlan playout session
**Depends on:** INV-TICK-DEADLINE-DISCIPLINE-001, INV-BLOCK-WALLCLOCK-FENCE-001, INV-BLOCK-PRIME-002, INV-TICK-GUARANTEED-OUTPUT
**Created:** 2026-02-08
**Status:** Active

---

## Definition

AIR MUST decouple all decode operations (video and audio) from the tick emission
thread. Decode MUST run on dedicated background fill threads that write into
bounded lookahead buffers. The tick thread MUST only consume pre-decoded frames
from these buffers — never call decode APIs directly.

When a primed buffer cannot satisfy a pop request, the buffer MUST return failure
(false). It MUST NOT inject substitute data (silence, pad, hold-last, black frame).
The caller (PipelineManager) treats buffer underflow as a session-ending hard fault.

This invariant ensures that:

1. Tick emission latency is bounded and independent of decode cost.
2. Decode stalls are absorbed by buffer headroom without disrupting output.
3. Buffer underflow is a deterministic, observable failure — never masked.
4. Fence tick transitions deliver the new block's first frame at exactly the
   scheduled tick index, even under decode stall conditions.

---

## Scope

Applies to:

- **VideoLookaheadBuffer** (INV-VIDEO-LOOKAHEAD-001): background video decode fill thread,
  bounded frame buffer, cadence resolution, hold-last on content exhaustion.
- **AudioLookaheadBuffer** (INV-AUDIO-LOOKAHEAD-001): PCM sample ring buffer fed by the
  video fill thread (audio is a side-effect of video decode via TryGetFrame).
- **PipelineManager**: tick loop consumption of both buffers, fence transitions,
  session stop on underflow.

Does NOT apply to:

- Primed frame consumption in `StartFilling()`, which is synchronous by contract
  (INV-BLOCK-PRIME-002). This is the sole exception to the tick-thread-never-decodes rule.
- Offline rendering / non-realtime export modes (if any exist).

---

## Sub-Invariants

### INV-VIDEO-LOOKAHEAD-001 — Video Lookahead Buffer Authority

| Req | Statement |
|-----|-----------|
| R1 | The tick thread MUST NOT call `TryGetFrame()` or any video decode API after the fill thread is started. All video decode MUST occur on the fill thread. |
| R2 | The fill thread MUST maintain buffer depth at or near `target_depth_frames` (default: `max(1, fps * 0.5)`) by decoding ahead. When the buffer is full, the fill thread MUST wait on a condition variable — not busy-loop. |
| R3 | `TryPopFrame()` MUST return `false` when the buffer is empty and primed. It MUST NOT inject a substitute frame (black, pad, hold-last, or any other synthetic data). The output struct MUST be left unmodified on failure. |
| R4 | At a fence tick, `StopFilling(flush=true)` MUST drain the buffer and join the fill thread. `StartFilling()` with the new block's producer MUST synchronously consume the primed frame, making it immediately available for `TryPopFrame()`. The fence tick frame MUST be from the new block. |
| R5 | Decode stalls on the fill thread MUST NOT cause tick-thread underflow as long as the buffer has headroom. The buffer absorbs latency by design. |

### INV-AUDIO-LOOKAHEAD-001 — Audio Lookahead Buffer Authority

| Req | Statement |
|-----|-----------|
| R1 | Audio decode MUST NOT occur on the tick thread. Audio samples are pushed to the AudioLookaheadBuffer by the VideoLookaheadBuffer's fill thread as a side-effect of video decode (FrameData contains audio). |
| R2 | `TryPopSamples()` MUST return `false` when insufficient samples are available. The buffer itself MUST NOT inject silence, pad, or any substitute audio data into its ring.  The buffer MUST be left untouched on failure.  Note: the caller (PipelineManager) MAY synthesize silence for the audio output at fence ticks when the buffer is not yet primed for the incoming block (FENCE_AUDIO_PAD — see INV-PAD-PRODUCER-005).  This caller-side synthesis does not violate R2 because it occurs outside the buffer, after the buffer has returned failure. |
| R3 | Audio buffer depth MUST absorb decode stalls. When the fill thread is slower than consumption but the buffer has headroom, audio output MUST continue uninterrupted. |
| R4 | At fence transitions, the audio buffer is NOT flushed (preserving audio continuity across block cuts). New audio from the next block's primed frame is pushed during `StartFilling()`. |

---

## Forbidden Patterns

- **Tick-thread decode:** The tick thread calling `TryGetFrame()`, `DecodeFrameToBuffer()`,
  or any audio/video decode API (except primed frame retrieval in `StartFilling()`).
- **Silent underflow masking:** Returning a default/zero/black frame or silence samples when
  the buffer is empty. Underflow MUST be visible as a `false` return and an incremented
  underflow counter.
- **Buffer-level pad injection on underflow:** The buffer injecting pad/hold-last/freeze
  frames or silence samples when content is unavailable.  Underflow MUST be reported
  as `false`, never masked.  PipelineManager may synthesize silence at fence ticks
  (FENCE_AUDIO_PAD) or select the PadProducer via the TAKE — both occur outside
  the buffer, after it has reported failure.
- **Blocking pop:** `TryPopFrame()` or `TryPopSamples()` blocking or waiting for the fill
  thread. These MUST be non-blocking.
- **Fence-tick stale data:** The fence tick consuming a frame from the previous block after
  `StopFilling(flush=true)` + `StartFilling()` with the new block's producer.

---

## Relationship to Other Contracts

- **INV-TICK-DEADLINE-DISCIPLINE-001:** Tick deadline discipline guarantees wall-clock
  anchored tick progression. Lookahead buffers ensure that content is pre-decoded so
  that tick emission can meet deadlines without blocking on decode.
- **INV-BLOCK-WALLCLOCK-FENCE-001:** Fence tick is the sole timing authority for block
  transitions. Lookahead buffer flush/restart at fence ensures clean block boundaries.
- **INV-BLOCK-PRIME-002:** Zero-deadline work at fence tick. The primed frame is consumed
  synchronously in `StartFilling()`, which is called on the tick thread at the fence tick.
  This is the documented exception to the tick-thread-never-decodes rule.
- **INV-BLOCK-PRIME-004:** Cadence independence of priming. The fill thread resolves cadence
  (decode vs. repeat) independently; priming does not alter the pattern.

---

## Required Tests

**File:** `pkg/air/tests/contracts/BlockPlan/LookaheadBufferContractTests.cpp`

### Section 1 — Tick Thread Never Decodes (R1)

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `TickThread_NeverCallsVideoDecodeAPIs` | VIDEO R1 | Fill + consume 60 frames; assert zero `TryGetFrame()` calls from tick thread; all from single fill thread. |
| `TickThread_NeverCallsAudioDecodeAPIs` | AUDIO R1 | Fill + consume 30 frames with audio; assert zero decode calls from tick thread; audio pushed/popped without tick-thread decode. |
| `TickThread_PrimedFrameIsOnlyException` | VIDEO R1, PRIME-002 | Arm primed frame; assert at most one tick-thread decode call (the primed frame); all subsequent from fill thread. |

### Section 2 — Decode Stalls Absorbed by Buffer Headroom (R5, R3)

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `VideoDecodeStall_BufferAbsorbsLatency` | VIDEO R5 | Inject 25ms decode delay; consume 60 frames at 30fps; assert zero underflows. |
| `AudioDecodeStall_BufferAbsorbsLatency` | AUDIO R3 | Inject 25ms decode delay; consume 30 ticks of audio; assert zero audio underflows. |
| `CombinedStall_BothBuffersSustainOutput` | VIDEO R5, AUDIO R3 | Phase 1: steady state. Phase 2: 30ms stall. Phase 3: stall cleared, buffer refills. Assert zero underflows throughout. |

### Section 3 — Underflow Is Hard Fault (R3, R2)

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `VideoUnderflow_ReturnsFalse_NoPadInjected` | VIDEO R3 | Exhaust video buffer; assert `TryPopFrame()` returns false; underflow count increments. |
| `AudioUnderflow_ReturnsFalse_NoSilenceInjected` | AUDIO R2 | Exhaust audio buffer; assert `TryPopSamples()` returns false; underflow count increments. |
| `VideoUnderflow_NeverReturnsSubstituteData` | VIDEO R3 | Pop from empty buffer; assert output struct is unmodified (sentinel values preserved). |
| `AudioUnderflow_NeverReturnsSubstituteData` | AUDIO R2 | Pop more samples than available; assert buffer untouched after underflow. |
| `UnderflowCount_Accumulates` | VIDEO R3, AUDIO R2 | Multiple underflows; assert counter accumulates correctly. |

### Section 4 — Fence Tick Precision (R4)

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `FenceTick_DeliversNextBlock_ExactIndex` | VIDEO R4, WALLFENCE-004 | Consume 30 ticks from block A; fence transition; assert fence tick frame is from block B with correct Y-plane fill. |
| `FenceTick_PrecisionPreservedUnderStall` | VIDEO R4 | Block A has 20ms decode stall; fence at tick 20; assert fence tick frame is from block B despite prior stall. |
| `FenceTick_AudioAvailableFromNewBlock` | AUDIO R4 | Fence transition; assert audio samples from block B's primed frame are pushed during `StartFilling()`. |
| `FenceTick_RapidTransitions_Stable` | VIDEO R4 | 5 rapid block transitions; assert each fence frame is from the correct block; zero underflows. |
