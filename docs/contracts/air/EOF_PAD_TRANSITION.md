# EOF → Pad Transition — AIR Behavioral Contract

Status: Contract
Authority Level: Runtime
Derived From: `LAW-LIVENESS`, `LAW-CLOCK`
Owner: AIR (TickProducer / PipelineManager)

---

## Problem

When a segment's media content is exhausted (decoder EOF) before the segment's scheduled duration is complete, the system must fill the remaining time with pad frames (black video + silence). Currently, the system cannot distinguish between decoder EOF (terminal — content is gone) and transient decode underrun (temporary — content is still arriving). Both return `std::nullopt` from `DecodeNextFrameRaw`. The PipelineManager tick loop treats all `nullopt` equally: it holds the last successfully decoded frame. This causes a visible freeze on the last frame of a commercial until the next segment boundary.

---

## Scope

This contract governs the behavior of frame production when a segment's decoder reaches EOF with scheduled time remaining. It applies to ALL segment types (content, commercial, filler) — any segment backed by a decoded asset.

This contract does NOT govern:
- Pad segments (which are already synthetic black/silence via `GeneratePadFrame`)
- Block fence transitions (governed by `INV-FENCE-TAKE-READY-001`)
- Preview/live switching (governed by Phase 8 contracts)

---

## Definitions

**Decoder EOF:** The decoder has consumed all media in the current segment's asset. No more frames can be produced from this source. This is a terminal condition for the current segment.

**Transient Underrun:** The decoder has not yet produced a frame for the current tick due to temporary conditions (buffer not yet primed, decode latency, I/O stall). The decoder may produce frames on subsequent ticks. This is a recoverable condition.

**Segment Remaining Duration:** The time between the decoder's EOF and the segment's scheduled end boundary. This is the time window where the system must emit pad frames instead of holding the last decoded frame.

---

## Invariants

### INV-AIR-EOF-PAD-TRANSITION-001

When a segment's decoder reaches EOF before the segment's scheduled duration is exhausted, all subsequent frames within that segment MUST be pad frames (black video + silence). The last decoded frame of the terminated asset MUST NOT be repeated or held.

**Pass:** From the tick immediately following decoder EOF until the segment boundary, every emitted frame is a pad frame (Y=0x10, UV=0x80 broadcast black; audio=silence).

**Fail:** Any frame after decoder EOF within the same segment that is NOT a pad frame (e.g., a repeated copy of the commercial's last frame).

### INV-AIR-EOF-VS-UNDERRUN-001

The system MUST distinguish between decoder EOF (terminal) and transient underrun (recoverable). These are different conditions requiring different responses:

| Condition | Signal | Response |
|-----------|--------|----------|
| **EOF** | Decoder reports end-of-stream for current segment | Emit pad frames for remaining segment duration. MUST NOT hold last frame. |
| **Transient underrun** | Decoder returns no frame but has NOT reported EOF | Hold last good frame (repeat). MAY recover on subsequent ticks. |

**Pass:** EOF produces pad frames; underrun produces repeat frames; the two are never confused.

**Fail:** EOF produces repeat frames (the current bug), or underrun produces pad frames (would cause black flashes during normal decode).

### INV-AIR-EOF-IMMEDIATE-001

The transition from decoded content to pad frames on EOF MUST occur on the first tick after EOF is detected. There MUST NOT be a delay of N ticks where the last decoded frame continues to display before pad begins.

**Pass:** The tick immediately following EOF detection emits a pad frame.

**Fail:** One or more ticks after EOF detection emit the last decoded frame before pad begins.

### INV-AIR-PAD-FRAME-AVAILABILITY-001

Pad frame generation MUST NOT depend on prior successful decode of content frames. A pad frame (broadcast black + silence) MUST be available for emission at any point during the fill loop, including before the first content frame has been decoded. This protects against edge cases where EOF occurs on the first decode attempt (undecodable asset, very short commercial, join-in-progress during a failing segment).

**Pass:** Pad frame is available and emittable even if zero content frames have been successfully decoded.

**Fail:** Pad frame construction depends on having decoded at least one content frame. System cannot emit pad when EOF occurs before first decode.

---

## Current Violation

### Location

**TickProducer::DecodeNextFrameRaw** (TickProducer.cpp:891-941):
- Line 911: Decoder reports EOF via `decoder_->IsEOF()`
- Line 937: `decoder_ok_` set to `false`
- Line 941: Returns `std::nullopt`

**PipelineManager::Run tick loop** (PipelineManager.cpp:2252-2263):
- Line 2256: `has_last_good_video_frame_` is `true` (from the commercial's last frame)
- Line 2257: `chosen_video = &last_good_video_frame_` — holds the commercial's last frame
- Line 2258: `decision = TakeDecision::kRepeat`

### Signal Path

```
DecodeNextFrameRaw()
  → decoder EOF detected
  → decoder_ok_ = false
  → returns std::nullopt           ← SAME signal as transient underrun

FillLoop
  → receives nullopt
  → stops filling buffer           ← correct

Tick loop
  → TryPopFrame / GetByIndex fails (buffer drained)
  → falls back to last_good_video_frame_  ← INCORRECT for EOF
  → decision = kRepeat             ← should be kPad
```

### Root Cause

`std::nullopt` from `DecodeNextFrameRaw` is ambiguous. It means both "EOF, no more frames ever" and "underrun, try again later." The tick loop cannot distinguish the two and defaults to the safe-for-underrun behavior (repeat last frame), which is incorrect for EOF.

---

## Required Tests

- `runtime/tests/contracts/BlockPlan/EofPadTransitionContractTests.cpp`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `TEST_INV_EOF_PAD_TRANSITION_001_PadAfterEof` | INV-AIR-EOF-PAD-TRANSITION-001 | Commercial shorter than allocated duration. After decoder EOF, all remaining frames in the segment are pad (black). No repeated frames. |
| `TEST_INV_EOF_VS_UNDERRUN_001_UnderrunStillRepeats` | INV-AIR-EOF-VS-UNDERRUN-001 | Transient decode stall (not EOF). System repeats last good frame. Does NOT emit pad. |
| `TEST_INV_EOF_IMMEDIATE_001_NoBridgeFrames` | INV-AIR-EOF-IMMEDIATE-001 | EOF detected at tick T. Tick T+1 emits pad. No intermediate ticks emit the last decoded frame. |
| `TEST_INV_EOF_PAD_TRANSITION_CommercialToPad` | INV-AIR-EOF-PAD-TRANSITION-001 | Full scenario: commercial segment (60s) followed by pad segment (2s). Commercial's asset is 59s. After 59s, remaining 1s of commercial segment + 2s of pad segment are all pad frames. No freeze frame at the boundary. |

---

## Enforcement Evidence

**Status: ENFORCED.**

The initial `IsSegmentEof()` out-of-band approach was reverted due to cross-segment state poisoning. The current enforcement uses the in-band `DecodeResult` model (`docs/contracts/air/DECODE_RESULT_MODEL.md`):

- `TryGetFrame()` returns `DecodeResult{kEof, nullopt}` when the decoder reports EOF
- EOF is derived per-call from `decoder_->IsEOF()` — no persistent producer-level flag
- The fill loop (VideoLookaheadBuffer) switches on `DecodeStatus`: kEof → pad frame, kUnderrun → hold-last
- EOF-aware parking prevents pad frames from evicting earlier content in the buffer

The deprecated `IsSegmentEof()` and `segment_eof_` flag have been removed. `decoder_ok_` no longer participates in EOF signaling (it returns `kError` for init failures only).

---

## Implementation Path — In-Band Decode Result Model

This contract is enforced by the Decode Result Model defined in:

**`docs/contracts/air/DECODE_RESULT_MODEL.md`**

The out-of-band `IsSegmentEof()` approach is deprecated. The correct implementation uses `DecodeResult` with explicit `DecodeStatus` (kFrame, kUnderrun, kEof, kError). The status is per-call, not per-producer, eliminating cross-segment poisoning.

### Why Out-of-Band Failed

`IsSegmentEof()` was a persistent flag on the TickProducer. When the cold open's chapter-marker EOF set the flag, it persisted into the next segment's fill loop iteration. The commercial's VideoLookaheadBuffer read `IsSegmentEof() == true` from the same producer and emitted pad instead of decoding the commercial. The fix is structural: the EOF signal must be in-band (per-call return value), not out-of-band (persistent producer flag).

### Removed Interfaces

- `ITickProducer::IsSegmentEof()` — REMOVED. Replaced by in-band `DecodeResult{kEof}`.
- `TickProducer::segment_eof_` — REMOVED. EOF is stateless per-call via `decoder_->IsEOF()`.
- `decoder_ok_ = false` on EOF — REMOVED. `decoder_ok_` now only reflects initialization failures (returns `kError`, not `kEof`). See INV-AIR-DECODE-RESULT-SCOPE-001.
- `HasDecoder()` for frame-emission decisions — NOT USED for this purpose. Retained for initialization diagnostics only.
