# Playout Timing Classification Integration — Domain Contract

Status: Contract
Authority Level: Runtime
Derived From: `LAW-CLOCK`, `LAW-LIVENESS`, `LAW-DECODABILITY`

---

## Purpose

Input timing classification determines whether a source asset delivers frames at a constant or variable rate. This classification governs whether cadence resampling is permitted for the segment. A wrong classification — or a missing classification — produces A/V drift that cannot be corrected downstream.

This contract defines when classification occurs in the playout lifecycle, which component is responsible, how the result flows through the system, and what guarantees hold for the duration of playback.

The companion contract `playout_cadence_input_stability.md` defines the classification logic itself. This contract defines its placement and enforcement within the runtime.

### Authority Boundary

This contract owns:
- The lifecycle stage at which classification executes
- The component ownership of classification, storage, and enforcement
- The data flow from decode to classification to mode selection to output
- The immutability of classification results within a segment
- The enforcement gate preventing output before classification completes

This contract does NOT own:
- The classification algorithm (owned by `playout_cadence_input_stability.md`)
- The cadence pattern computation
- Audio sample clock authority
- Output clock pacing (`LAW-CLOCK`)
- Segment scheduling or block construction

---

## Lifecycle Placement

### INV-TIMING-CLASSIFICATION-LIFECYCLE-001 — Classification occurs during segment prime

Classification MUST execute during the segment prime/prefill phase — the interval between decoder open and first output frame emission. This is the only stage at which decoded frames are available but output has not yet committed.

### INV-TIMING-CLASSIFICATION-LIFECYCLE-002 — Classification completes before output

Classification MUST complete and produce a definitive result (CFR, VFR, or INDETERMINATE) before the first output frame is emitted for the segment. No output frame may be committed while classification is pending.

### INV-TIMING-CLASSIFICATION-LIFECYCLE-003 — Classification does not occur mid-playback

Once output has begun for a segment, classification MUST NOT be re-executed. The classification result established during prime is authoritative for the segment's entire lifetime. Re-classification mid-segment would invalidate the mode selection that output frames have already been emitted under.

---

## Ownership

### Classification Caller

The component that opens the segment decoder and manages the prime phase is responsible for invoking classification. In the current architecture, this is the TickProducer (within AIR) during `AssignBlock` or segment prep. The TickProducer decodes frames into the lookahead buffer during prime; the PTS deltas from those frames are the classification input.

### Result Storage

The classification result MUST be stored on the segment's producer state (TickProducer or equivalent). It MUST remain accessible to any component that makes timing decisions for the segment — including the PipelineManager for mode selection and the output clock for frame selection strategy.

### Mode Enforcement

The PipelineManager (or equivalent orchestrator within AIR) MUST read the stored classification result and enforce mode selection before activating the output clock. The PipelineManager MUST NOT activate CADENCE mode without a CFR classification. The PipelineManager MUST NOT delegate this decision to downstream components.

---

## Data Flow

The classification pipeline follows a strict, linear sequence:

```
Segment Decoder Open
       │
       ▼
Prime Phase: Decode N frames into lookahead buffer
       │
       ▼
Collect PTS deltas from decoded frames
       │
       ▼
Classify: CFR / VFR / INDETERMINATE
       │
       ▼
Select resampling mode (CADENCE or CLOCK_DRIVEN)
       │
       ▼
Enforce eligibility (reject CADENCE if not CFR)
       │
       ▼
Store classification result on producer state
       │
       ▼
Activate output clock with selected mode
       │
       ▼
First output frame emitted
```

No step may be reordered. No step may be skipped. The classification result flows forward only — it is never fed back to alter the prime phase.

---

## State Requirements

### INV-TIMING-CLASSIFICATION-IMMUTABLE-001 — Classification is immutable within a segment

Once stored, the classification result for a segment MUST NOT be modified for the duration of that segment's playback. All timing decisions — frame selection, cadence pattern, output pacing — MUST reference the original classification.

### INV-TIMING-CLASSIFICATION-SCOPED-001 — Classification is segment-scoped

Each segment receives its own independent classification during its own prime phase. A classification from a prior segment MUST NOT carry forward to a subsequent segment. A new segment MUST be classified independently, even if it uses the same source asset, because seek position and decode conditions may differ.

### INV-TIMING-CLASSIFICATION-AVAILABLE-001 — Classification is accessible to all timing consumers

The stored classification result MUST be readable by any component involved in timing decisions for the segment. This includes the output clock (for frame selection strategy), the cadence engine (if CFR), and diagnostic/telemetry systems. No timing consumer may operate without access to the classification.

---

## Enforcement

### INV-TIMING-CLASSIFICATION-GATE-001 — No output without classification

The output path MUST NOT emit frames for a segment that has not been classified. If classification has not completed — due to insufficient frames, decoder failure, or any other reason — the output gate MUST remain closed until a classification result (including INDETERMINATE) is stored.

### INV-TIMING-CLASSIFICATION-GATE-002 — No bypass

There MUST be no code path that activates CADENCE mode without passing through the classification gate. This includes fast paths, fallback paths, test paths, and operator overrides. The classification gate is unconditional.

---

## Failure Handling

### Insufficient Frames

If the prime phase produces fewer frames than the minimum observation window, classification returns INDETERMINATE. INDETERMINATE MUST select CLOCK_DRIVEN mode. Output may proceed — INDETERMINATE is not an error, it is a valid classification that defaults to the safe strategy.

### Decoder Failure

If the decoder fails during prime and no frames are produced, classification returns INDETERMINATE with zero observation frames. The same CLOCK_DRIVEN fallback applies. The segment may still attempt output using pad or silence frames as governed by liveness contracts.

### Classification Logic Failure

If the classification function itself raises an exception, the caller MUST catch it, store INDETERMINATE as the result, and proceed with CLOCK_DRIVEN mode. Classification failures MUST NOT propagate as unhandled exceptions that crash the playout session.

---

## Invariant Summary

| ID | Title |
|----|-------|
| INV-TIMING-CLASSIFICATION-LIFECYCLE-001 | Classification occurs during segment prime |
| INV-TIMING-CLASSIFICATION-LIFECYCLE-002 | Classification completes before output |
| INV-TIMING-CLASSIFICATION-LIFECYCLE-003 | No mid-playback reclassification |
| INV-TIMING-CLASSIFICATION-IMMUTABLE-001 | Classification immutable within segment |
| INV-TIMING-CLASSIFICATION-SCOPED-001 | Classification is segment-scoped |
| INV-TIMING-CLASSIFICATION-AVAILABLE-001 | Classification accessible to timing consumers |
| INV-TIMING-CLASSIFICATION-GATE-001 | No output without classification |
| INV-TIMING-CLASSIFICATION-GATE-002 | No bypass of classification gate |

---

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/TimingClassificationIntegrationTests.cpp`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `ClassificationDuringPrime` | INV-TIMING-CLASSIFICATION-LIFECYCLE-001 | Classification result is available after prime phase completes |
| `NoOutputBeforeClassification` | INV-TIMING-CLASSIFICATION-LIFECYCLE-002 | Output gate blocks until classification result is stored |
| `NoReclassificationMidSegment` | INV-TIMING-CLASSIFICATION-LIFECYCLE-003 | Classification result unchanged after output begins |
| `ClassificationImmutableDuringPlayback` | INV-TIMING-CLASSIFICATION-IMMUTABLE-001 | Stored result cannot be overwritten while segment is active |
| `ClassificationPerSegment` | INV-TIMING-CLASSIFICATION-SCOPED-001 | New segment gets fresh classification, not inherited from prior |
| `AllTimingConsumersAccessResult` | INV-TIMING-CLASSIFICATION-AVAILABLE-001 | Output clock, cadence engine, and diagnostics all read same result |
| `OutputGateBlocksWithoutClassification` | INV-TIMING-CLASSIFICATION-GATE-001 | Segment with no classification cannot emit frames |
| `NoCadenceWithoutClassification` | INV-TIMING-CLASSIFICATION-GATE-002 | CADENCE activation without classification raises or rejects |
| `InsufficientFramesDefaultsClock` | Failure handling | Few prime frames → INDETERMINATE → CLOCK_DRIVEN |
| `DecoderFailureDefaultsClock` | Failure handling | Zero frames from decoder → INDETERMINATE → CLOCK_DRIVEN |
| `ClassificationExceptionDefaultsClock` | Failure handling | Exception in classifier → INDETERMINATE → CLOCK_DRIVEN |

---

## Enforcement Evidence

TODO
