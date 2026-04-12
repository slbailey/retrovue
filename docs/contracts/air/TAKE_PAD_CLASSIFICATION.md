# TAKE Pad Classification — AIR Behavioral Contract

Status: Contract
Authority Level: Runtime
Derived From: `LAW-LIVENESS`, `LAW-CLOCK`, `LAW-DECODABILITY`
Owner: AIR (PipelineManager TAKE cascade)

---

## Purpose

This contract defines how PipelineManager classifies each emitted frame as **content**, **pad**, or **degraded**. Classification drives metrics (`pad_frames_emitted_total`, `continuous_frames_emitted_total`), observability (FrameFingerprint `is_pad`, `commit_slot`), and contract compliance (tests that assert pad-only output for failed decoders).

The TAKE cascade is the single classification authority. No other component assigns these labels.

---

## Classification Sources

Five signals are available at the TAKE decision point:

| Signal | Source | What it reveals |
|--------|--------|-----------------|
| **Buffer pop result** | `video_buffer_->GetByIndex()` / `TryPopFrame()` | Whether a frame exists in the buffer for this tick |
| **Frame content** | `vbf.was_decoded`, `vbf.video` pixel data, `vbf.asset_uri` | Whether the frame is real decode output or a pad/hold-last substitute |
| **Producer health** | `AsTickProducer(live_)->HasDecoder()` | Whether the producer ever had a working decoder |
| **Slot assignment** | `video_buffer_` exists, block assigned | Whether a block is loaded into the live slot |
| **Pad producer** | `pad_producer_->VideoFrame()` | Always-available fallback (broadcast black) |

---

## Current Behavior (Defect)

Classification is determined **solely by `TakeDecision`**, which is set by the TAKE cascade based on buffer pop success:

- Buffer pop succeeds → `kContentA` / `kContentB` → `is_pad = false`
- Buffer pop fails + held frame → `kRepeat` / `kHold` → `is_pad = false`
- Buffer pop fails + no held frame → `kPad` → `is_pad = true`

This is incorrect when the buffer contains pad frames produced by the fill loop in response to `kError` or `kEof`. The TAKE cascade treats these buffer-resident pad frames as content because the pop succeeded.

**Result:** A block with a dead decoder (all frames are broadcast black from the fill loop's kError path) is classified as "content" in metrics and fingerprints, violating observability contracts.

---

## Required Behavior

### Case A — Healthy decode (buffer contains real frame)

| Signal | Value |
|--------|-------|
| `TryGetFrame()` | returned `kFrame` at fill time |
| `vbf.was_decoded` | `true` |
| `vbf.asset_uri` | non-empty, real asset |

**Classification:** `kContentA` / `kContentB`. `is_pad = false`. `commit_slot = 'A'` / `'B'`.

### Case B — Transient underrun (buffer contains held frame)

| Signal | Value |
|--------|-------|
| `TryGetFrame()` | returned `kUnderrun` at fill time |
| `vbf.was_decoded` | `false` |
| `vbf.asset_uri` | last decoded asset (non-empty) |

**Classification:** `kContentA` (held). `is_pad = false`. This is correct: held frames maintain visual continuity during transient stalls.

### Case C — EOF (buffer contains pad frame from fill loop)

| Signal | Value |
|--------|-------|
| `TryGetFrame()` | returned `kEof` at fill time |
| `vbf.was_decoded` | `false` |
| `vbf.asset_uri` | empty string |
| `vbf.video` | broadcast black (Y=0x10) |

**Classification:** MUST be `kPad`. `is_pad = true`. `commit_slot = 'P'`.

The TAKE cascade MUST NOT classify this as content simply because the buffer pop succeeded.

### Case D — Error / dead decoder (buffer contains pad frame from fill loop)

| Signal | Value |
|--------|-------|
| `TryGetFrame()` | returned `kError` at fill time |
| `vbf.was_decoded` | `false` |
| `vbf.asset_uri` | empty string |
| `HasDecoder()` | `false` |

**Classification:** MUST be `kPad`. `is_pad = true`. `commit_slot = 'P'`.

Same as Case C. A dead decoder MUST NOT produce content classification.

### Case E — No buffer frame, no held frame (pure pad fallback)

| Signal | Value |
|--------|-------|
| Buffer pop | fails |
| `has_last_good_video_frame_` | `false` |

**Classification:** `kPad`. `is_pad = true`. `commit_slot = 'P'`. Frame from `pad_producer_->VideoFrame()`.

This is the existing behavior and is correct.

---

## Distinguishing Signal

The reliable distinguishing signal between content and pad frames in the buffer is:

```
vbf.was_decoded == false  &&  vbf.asset_uri.empty()
```

This combination is set by the fill loop only on kEof and kError paths. Hold-last frames (kUnderrun) have `was_decoded = false` but retain the last decoded `asset_uri`. Content frames have `was_decoded = true`.

| `was_decoded` | `asset_uri` | Source | Classification |
|---------------|-------------|--------|----------------|
| `true` | non-empty | kFrame | Content |
| `false` | non-empty | kUnderrun (hold-last) | Content (held) |
| `false` | empty | kEof or kError (pad) | **Pad** |

---

## Invariants

### INV-AIR-TAKE-PAD-CLASSIFICATION-EXPLICIT-001

Output frame classification MUST reflect the actual frame source, not the buffer slot assignment. A frame that originated from the fill loop's kEof or kError pad-construction path MUST be classified as pad (`TakeDecision::kPad`), regardless of whether it was popped from the live buffer.

**Behavioral Guarantee:** Metrics and fingerprints accurately report pad output. Tests that assert `pad_frames_emitted_total == continuous_frames_emitted_total` for dead-decoder blocks produce correct results.

**Authority Model:** PipelineManager TAKE cascade. After popping a frame from the buffer, the cascade inspects `vbf.was_decoded` and `vbf.asset_uri` to determine whether the frame is real content or a pad substitute.

**Boundary / Constraint:**
- After a successful buffer pop, if `vbf.was_decoded == false && vbf.asset_uri.empty()`, the TAKE decision MUST be `kPad`, the chosen video MUST be `pad_producer_->VideoFrame()` (or the buffer frame if pixel-identical), and `commit_slot` MUST be `'P'`.
- The frame's visual content (broadcast black) is NOT the classification signal — the `was_decoded` + `asset_uri` combination is authoritative.

**Violation:** A buffer-resident pad frame classified as `kContentA`. A dead-decoder block that reports `pad_frames_emitted_total = 0`.

#### Required Tests

- `runtime/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp` — `PadFramesForEntireBlock`, `NulloptBurstTolerance`, `PadProof_PadOnlyMicroBlock`, `PadProof_BudgetShortfall_ExactCount`

#### Enforcement Evidence

TODO

---

### INV-AIR-TAKE-DEAD-PRODUCER-IS-PAD-001

When a producer has `HasDecoder() == false` after `AssignBlock()`, ALL frames emitted during that block MUST be classified as pad. The TAKE cascade MUST NOT classify any frame from a dead-decoder block as content.

**Behavioral Guarantee:** Failed asset resolution produces observable pad output, not silent content classification that hides the failure.

**Authority Model:** PipelineManager TAKE cascade, informed by `AsTickProducer(live_)->HasDecoder()`.

**Boundary / Constraint:**
- If `HasDecoder() == false` on the live producer at the time of TAKE, the decision MUST be `kPad`.
- This applies for the entire duration of the block, not just the first tick.
- The fill loop's behavior (pushing pad frames on kError) is a precondition, not a substitute: the TAKE classification must independently verify.

**Violation:** A block where `HasDecoder() == false` that reports any `kContentA` or `kContentB` decisions. A non-zero content frame count for a dead-decoder block.

#### Required Tests

- `runtime/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp` — `PadFramesForEntireBlock`, `DegradedTakeCountTracked`

#### Enforcement Evidence

TODO

---

### INV-AIR-TAKE-PAD-METRICS-CONSISTENT-001

`pad_frames_emitted_total` MUST equal the count of frames where the TAKE decision was `kPad` or `kStandby`. This counter MUST be consistent with `FrameFingerprint::is_pad` for every emitted frame.

**Behavioral Guarantee:** Metrics and per-frame observability agree. No frames are classified differently by the metric counter vs the fingerprint.

**Authority Model:** PipelineManager metric increment (line ~4472) and fingerprint emission (line ~4206) use the same `TakeDecision` value.

**Boundary / Constraint:**
- The metric increment and the fingerprint's `is_pad` field MUST both derive from the same `TakeDecision` value, evaluated once per tick.
- No path may increment the metric without setting `is_pad = true` on the fingerprint, or vice versa.

**Violation:** `pad_frames_emitted_total` differs from the count of fingerprints where `is_pad == true`. A frame where `is_pad == true` in the fingerprint but the metric was not incremented.

#### Required Tests

- `runtime/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp` — `PadProof_BudgetShortfall_ExactCount`

#### Enforcement Evidence

TODO

---

## Interaction with Existing Contracts

### DECODE_RESULT_MODEL.md

The fill loop's kEof/kError → pad frame construction is governed by `INV-AIR-EOF-NON-REPEATABLE-001` and `INV-AIR-ERROR-FAILSAFE-001`. This contract governs the **downstream classification** of those pad frames by the TAKE cascade. The fill loop produces the frame; the TAKE classifies it.

### EOF_PAD_TRANSITION.md

`INV-AIR-EOF-PAD-TRANSITION-001` requires pad frames after EOF. This contract ensures those pad frames are **counted as pad** by the TAKE, not silently classified as content.

### PRODUCER_INTERFACE.md

`INV-AIR-PRODUCER-INTERFACE-001` ensures PipelineManager accesses producers through `ITickProducer`. `HasDecoder()` is available on the interface, enabling the TAKE cascade to detect dead producers without concrete-type downcasts.

---

## Non-Goals

- This contract does NOT redefine fill loop behavior. The fill loop's kEof/kError → pad frame construction is unchanged.
- This contract does NOT change `DecodeResult` or `DecodeStatus`.
- This contract does NOT introduce new producer types or new buffer frame types.
- This contract does NOT change how pad frames are constructed — only how they are classified after construction.
