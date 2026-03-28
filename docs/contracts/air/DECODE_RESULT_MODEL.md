# Decode Result Model — AIR Behavioral Contract

Status: Contract
Authority Level: Runtime
Derived From: `LAW-LIVENESS`, `LAW-CLOCK`, `LAW-DECODABILITY`
Owner: AIR (ITickProducer / VideoLookaheadBuffer / PipelineManager)
Supersedes: `IsSegmentEof()` out-of-band signaling (deprecated)

---

## Purpose

This contract introduces an explicit, in-band decode result model that replaces `std::optional<FrameData>` as the return type for frame production. The current system collapses six distinct semantic outcomes into a binary signal ("frame" or "no frame"), making it impossible for consumers to distinguish EOF from underrun from error without querying producer-internal state.

This contract defines the canonical structure, behavioral rules, and invariants for the replacement model.

---

## Decode Result Structure

### DecodeStatus

```cpp
enum class DecodeStatus {
    kFrame,     // Normal decoded frame available
    kUnderrun,  // Temporary — no frame this tick, may recover
    kEof,       // Terminal — segment asset exhausted, no more frames
    kError      // Fatal — decoder failed, unrecoverable for this segment
};
```

### DecodeResult

```cpp
struct DecodeResult {
    DecodeStatus status;
    std::optional<FrameData> frame;  // present when status == kFrame
};
```

### Field Rules

| Status | `frame` field | Meaning |
|--------|--------------|---------|
| `kFrame` | MUST be present (has_value) | A valid decoded frame is available for consumption. |
| `kUnderrun` | MUST be empty (nullopt) | The decoder has not produced a frame for this tick. The condition is transient. The decoder may produce frames on subsequent calls. |
| `kEof` | MUST be empty (nullopt) | The decoder has consumed all media in the current segment's asset. No more frames will be produced from this source. This is terminal for the current segment. |
| `kError` | MUST be empty (nullopt) | The decoder has encountered an unrecoverable failure. No frames can be produced. Distinct from EOF: error is unexpected; EOF is expected at content boundary. |

### Metadata

No additional metadata fields are required. The status enum carries all necessary semantic information. Diagnostic data (which segment, which asset, error details) is logged at the production site (TickProducer), not carried in the result.

---

## Invariants

### INV-AIR-DECODE-RESULT-EXPLICIT-001

All decode attempts via `TryGetFrame()` MUST return an explicit `DecodeResult` with a defined `DecodeStatus`. Ambiguous "no frame" states (`std::nullopt` without semantic classification) are forbidden. Every return from `TryGetFrame` MUST carry one of: `kFrame`, `kUnderrun`, `kEof`, `kError`.

**Behavioral Guarantee:** Consumers of `TryGetFrame` can determine the exact reason for frame absence without querying producer-internal state.

**Authority Model:** `ITickProducer::TryGetFrame()` is the sole authority for decode status. No out-of-band queries (e.g., `IsSegmentEof()`, `HasDecoder()`, `decoder_ok_`) are required to interpret the result.

**Boundary / Constraint:** `TryGetFrame()` MUST return `DecodeResult`. It MUST NOT return `std::optional<FrameData>`. Consumers MUST switch on `DecodeStatus`, not on `frame.has_value()`.

**Violation:** A `TryGetFrame` call that returns a result interpretable only by querying producer state. A consumer that ignores `DecodeStatus` and checks only `frame.has_value()`.

### INV-AIR-EOF-NON-REPEATABLE-001

When `DecodeStatus` is `kEof`, the fill loop MUST NOT repeat the last decoded frame. The fill loop MUST emit pad frames (broadcast black + silence) for the remaining segment duration.

**Behavioral Guarantee:** After EOF, the viewer sees clean black — not a frozen last frame of the commercial.

**Authority Model:** VideoLookaheadBuffer fill loop enforces this. PipelineManager is not involved in the EOF→pad decision; it receives pad frames from the buffer.

**Boundary / Constraint:** On `kEof`, the fill loop MUST construct and push a pad frame (`VideoBufferFrame` with broadcast black video and silence audio). It MUST NOT copy `last_decoded` into the buffer. `content_gap` MUST be set to `true`.

**Violation:** Any frame pushed to the buffer after `kEof` that is not a pad frame. Any frame in the buffer after `kEof` that has `was_decoded = false` and contains the last commercial frame's pixel data.

### INV-AIR-UNDERRUN-REPEATABLE-001

When `DecodeStatus` is `kUnderrun`, the fill loop MAY repeat the last decoded frame. This is a transient condition; the decoder may produce frames on subsequent calls.

**Behavioral Guarantee:** During temporary decode stalls, the viewer sees a held frame (smooth, no black flash) rather than pad.

**Authority Model:** VideoLookaheadBuffer fill loop enforces this. The held frame is the last successfully decoded video frame cached in the fill loop's `last_decoded` local variable.

**Boundary / Constraint:** On `kUnderrun`, the fill loop MUST push a frame with `was_decoded = false` containing `last_decoded` video. `content_gap` MUST be set to `true`. Silence MUST be pushed to the audio buffer to prevent underflow.

**Violation:** Pad frames emitted on `kUnderrun` (would cause visible black flashes during normal decode latency).

### INV-AIR-ERROR-FAILSAFE-001

When `DecodeStatus` is `kError`, the fill loop MUST NOT emit corrupted or undefined frames. The fill loop MUST fall back to pad behavior (broadcast black + silence), identical to `kEof` handling.

**Behavioral Guarantee:** Decoder failure produces clean black, not visual artifacts.

**Authority Model:** VideoLookaheadBuffer fill loop enforces this. Error is treated as terminal, same as EOF, for the remainder of the segment.

**Boundary / Constraint:** On `kError`, behavior is identical to `kEof`: pad frames pushed, `content_gap = true`, no held frames. The distinction between `kError` and `kEof` exists for diagnostics and logging, not for frame emission behavior.

**Violation:** Any non-pad frame emitted after `kError`. Any undefined or zero-length video data in the buffer after `kError`.

### INV-AIR-DECODE-RESULT-SCOPE-001

`DecodeStatus` is scoped to a single `TryGetFrame()` call. It is derived from the decoder's immediate state on each call. No persistent producer-level flag (e.g., `decoder_ok_`, `segment_eof_`) is allowed to determine `DecodeStatus`. Each call to `TryGetFrame` produces a fresh, independent `DecodeResult`.

**Behavioral Guarantee:** No cross-segment state poisoning. EOF on segment N does not affect segment N+1's decode results. Subsequent calls after EOF return `kEof` because the decoder itself reports EOF on re-query — not because a producer flag remembers it.

**Authority Model:** TickProducer produces the status per-call by querying the decoder:
- `decoder_->DecodeFrameToBuffer()` fails → `decoder_->IsEOF()` → `kEof` or `kUnderrun`
- No persistent `decoder_ok_` flag drives the return value. The `decoder_ok_` flag exists only for initialization failures (probe fail, validation fail, etc.) and returns `kError`, never `kEof`.
- Logging gates (`eof_logged_`) are permitted to suppress repeated log output but MUST NOT affect control flow or the returned `DecodeStatus`.

**Boundary / Constraint:** `DecodeResult` is a value type, not a reference to persistent state. Consumers MUST NOT cache `DecodeStatus` across fill-loop iterations for decision-making (they may cache it for logging). Each iteration's behavior is determined by the current call's result. `kEof` MUST be produced by live decoder query, not by reading a stored flag from a prior call.

**Violation:** A fill loop that checks a cached status from a previous `TryGetFrame` call to decide current behavior. A producer-level flag (e.g., `decoder_ok_ = false` set on EOF) that causes subsequent calls to return `kEof` without re-querying the decoder. A logging gate that suppresses or alters the returned `DecodeStatus`.

---

## Behavioral Matrix (Authoritative)

| DecodeStatus | Fill Loop: Push to Buffer | Fill Loop: Audio | Tick Loop: Frame Selection | Tick Loop: Fallback |
|-------------|--------------------------|------------------|---------------------------|-------------------|
| **kFrame** | Push decoded frame (`was_decoded=true`) | Push decoded audio from `FrameData::audio` | Pop/GetByIndex → emit as kContentA/B | N/A (frame available) |
| **kUnderrun** | Push held frame (`was_decoded=false`, `last_decoded` video) | Push silence to prevent underflow | Normal pop succeeds (held frame in buffer) | kRepeat via `last_good_video_frame_` if buffer drains |
| **kEof** | Push pad frame (broadcast black, `was_decoded=false`, empty `asset_uri`) | Push silence | Normal pop succeeds (pad frame in buffer) | kPad via `pad_producer_` if buffer drains |
| **kError** | Push pad frame (identical to kEof) | Push silence | Normal pop succeeds (pad frame in buffer) | kPad via `pad_producer_` if buffer drains |

### Key Behavioral Distinction

The fill loop is the **policy decision point**. It transforms the decode status into the correct frame type in the buffer. The tick loop (PipelineManager) does NOT need to know about DecodeStatus — it pops frames from the buffer and emits them. The distinction between held-last-frame and pad-frame is made upstream by the fill loop, not downstream by the tick loop.

This is why the PipelineManager requires NO changes. The fix lives entirely in:
1. TickProducer (produce the signal)
2. VideoLookaheadBuffer fill loop (consume the signal, emit the correct frame type)

---

## Interaction with Existing Contracts

### INV-AIR-EOF-PAD-TRANSITION-001

Updated: "decoder reaches EOF" now means `TryGetFrame` returns `DecodeResult{kEof, nullopt}`. The behavioral requirement (pad frames for remaining segment duration) is unchanged. The signal mechanism changes from `nullopt` + out-of-band `IsSegmentEof()` to in-band `kEof`.

### INV-AIR-EOF-VS-UNDERRUN-001

Updated: The distinction table now references `DecodeStatus::kEof` and `DecodeStatus::kUnderrun` instead of "decoder reports end-of-stream" vs "decoder returns no frame but has NOT reported EOF." The behavioral requirements are unchanged.

### INV-CONTINUOUS-FRAME-AUTHORITY-001

Unaffected. Frame authority is managed at the tick-loop level. The fill loop produces frames (real, held, or pad) into the buffer. The tick loop pops and emits. Authority transfer is orthogonal to decode status.

### INV-SEAM-CONTINUITY-GUARANTEED-001

Unaffected. Seam preparation uses separate producer instances (segment B has its own TickProducer). Each producer's `TryGetFrame` returns independent `DecodeResult` values. No cross-producer state.

### INV-BLOCK-WALLFENCE-003

Updated: `content_gap` tracking changes from "TryGetFrame returned nullopt" to "TryGetFrame returned kUnderrun, kEof, or kError." Behavior: `content_gap = true` on any non-kFrame status. `content_gap = false` on kFrame. Identical semantic, explicit signal.

---

## Pad Segment Behavior (Unchanged)

Pad segments (`SegmentType::kPad`) continue to use `GeneratePadFrame()` inside `DecodeNextFrameRaw`. The returned `DecodeResult` for a pad segment is `{kFrame, pad_frame}` — it IS a frame, just a synthetic one. Pad segments are not governed by the EOF/underrun distinction because they have no decoder and cannot EOF.

---

## Non-Goals

This contract does NOT require:

- Immediate refactor of all producers. Migration may be incremental (adapter pattern for legacy producers).
- New segment types. The decode result model is orthogonal to segment classification.
- Changes to pad segment behavior. `GeneratePadFrame()` continues to produce `kFrame` results.
- Changes to scheduling, block planning, seam logic, or PipelineManager tick loop. The fix is contained within TickProducer and VideoLookaheadBuffer.
- Changes to the gRPC interface or proto definitions. DecodeResult is internal to AIR.

---

## Migration Path

### Phase 1: Interface Change

Replace `ITickProducer::TryGetFrame()` return type:

```
Before: virtual std::optional<FrameData> TryGetFrame() = 0;
After:  virtual DecodeResult TryGetFrame() = 0;
```

All implementations of `ITickProducer` must be updated. All mocks and test producers must be updated.

### Phase 2: Producer Implementation

`TickProducer::TryGetFrame()` and `DecodeNextFrameRaw()` return `DecodeResult` with explicit status for each nullopt origin:

| Current nullopt origin | New DecodeStatus |
|-----------------------|-----------------|
| `state_ != kReady` | `kError` |
| `!decoder_ok_` (not EOF) | `kError` |
| `decoder_->IsEOF()` | `kEof` |
| Decode failure (not EOF) | `kUnderrun` |
| DROP mode first decode fails | `kUnderrun` or `kEof` (depending on `IsEOF()`) |

### Phase 3: Fill Loop Update

VideoLookaheadBuffer fill loop switches on `DecodeResult::status`:

```
kFrame    → existing "fd has value" path (push decoded frame)
kUnderrun → existing "hold last frame" path (push held frame)
kEof      → push pad frame (NEW behavior)
kError    → push pad frame (NEW behavior)
```

### Phase 4: Cleanup

Remove deprecated out-of-band signaling:
- `ITickProducer::IsSegmentEof()` — removed from interface
- `TickProducer::segment_eof_` — removed from implementation
- `HasDecoder()` — retained for diagnostic use only, not for frame-emission decisions

### Atomicity

The interface change (Phase 1) and consumer update (Phase 3) MUST be deployed atomically. There MUST NOT be a state where the interface returns `DecodeResult` but consumers still check `has_value()`. The migration is a single commit touching: `ITickProducer.hpp`, `TickProducer.hpp`, `TickProducer.cpp`, `VideoLookaheadBuffer.cpp`, and all mock/test producers.

---

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/EofPadTransitionContractTests.cpp` (update mocks to use DecodeResult)

| Test | Invariant | Scenario |
|------|-----------|----------|
| `TEST_INV_DECODE_RESULT_EXPLICIT_001` | INV-AIR-DECODE-RESULT-EXPLICIT-001 | TryGetFrame never returns ambiguous result. All returns have explicit status. |
| `TEST_INV_EOF_NON_REPEATABLE_001` | INV-AIR-EOF-NON-REPEATABLE-001 | After kEof, fill loop pushes pad frames. No held frames in buffer. |
| `TEST_INV_UNDERRUN_REPEATABLE_001` | INV-AIR-UNDERRUN-REPEATABLE-001 | On kUnderrun, fill loop pushes held frame. No pad frames. |
| `TEST_INV_ERROR_FAILSAFE_001` | INV-AIR-ERROR-FAILSAFE-001 | On kError, fill loop pushes pad frames. No corrupted frames. |
| `TEST_INV_DECODE_RESULT_SCOPE_001` | INV-AIR-DECODE-RESULT-SCOPE-001 | EOF on segment N does not affect segment N+1's results. Status is per-call. |
| `TEST_INV_EOF_PAD_TRANSITION_CommercialToPad` | INV-AIR-EOF-PAD-TRANSITION-001 | Commercial shorter than slot → remaining time is pad. No freeze frame. |

---

## Enforcement Evidence

TODO — pending implementation.
