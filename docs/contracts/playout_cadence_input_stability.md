# Playout Cadence Input Stability — Domain Contract

Status: Contract
Authority Level: Runtime
Derived From: `LAW-CLOCK`, `LAW-LIVENESS`, `LAW-DECODABILITY`

---

## Purpose

Cadence resampling converts a source frame rate to the channel output frame rate by selectively repeating or dropping frames according to a deterministic pattern. This conversion assumes the source delivers frames at a constant, predictable interval. When the source exhibits variable frame timing, the cadence pattern and the actual decoded frames diverge — audio advances at wall-clock rate while video content-time accumulates error proportional to the timing variance. Over minutes to hours, this produces audible and visible A/V desync.

This contract defines the conditions under which cadence resampling is permitted, how input frame timing stability is classified, and what behavior is required when stability cannot be confirmed.

### Authority Boundary

This contract owns:
- The definition of frame timing stability for cadence eligibility
- The classification of inputs as constant frame rate (CFR) or variable frame rate (VFR)
- The rules governing when cadence resampling is permitted or forbidden
- The fallback behavior when cadence resampling is not applicable

This contract does NOT own:
- The cadence pattern itself (frame repeat/drop sequence)
- Output clock pacing (`LAW-CLOCK`)
- Audio sample clock authority
- Encoder or mux timing

---

## Definitions

### Frame Interval

The PTS delta between consecutive decoded video frames from the same segment, expressed in source timebase units. Frame interval is measured from decoded output, not from container metadata.

### Constant Frame Rate (CFR)

An input where observed frame intervals are statistically uniform — every consecutive PTS delta falls within a narrow tolerance of the nominal frame period. CFR sources include properly authored Blu-ray, broadcast captures, and compliant progressive encodes.

### Variable Frame Rate (VFR)

An input where observed frame intervals vary beyond the tolerance threshold. VFR sources include screen recordings, mobile device captures, HEVC encodes with variable GOP timing, and container-level frame rate conversions that preserve original timestamps.

### Timing Stability

The degree to which observed frame intervals conform to the nominal frame period. Stability is a measured property of the decoded stream, not a declared property of the container.

### Cadence Resampling

The process of mapping N source frames per second to M output frames per second by repeating or dropping frames in a fixed pattern (e.g., 3:2 pulldown for 24→29.97). Requires that source frames arrive at predictable intervals so the pattern remains aligned with content time.

### Micro-jitter

Per-frame timing deviations smaller than one frame period that individually appear harmless but accumulate over time. Micro-jitter is the primary mechanism by which VFR inputs cause A/V drift under cadence resampling.

### Discontinuity

A frame interval deviation exceeding one frame period. Discontinuities are handled by the PTS correction mechanism (`INV-PTS-DISCONTINUITY-ABSORB-001`) and are distinct from the micro-jitter problem addressed here.

---

## Invariants

### INV-CADENCE-INPUT-CFR-REQUIRED-001

CADENCE resampling mode MUST only be activated when the input frame intervals have been classified as CFR based on observed PTS deltas. Container-reported frame rate metadata MUST NOT be the sole basis for classification.

### INV-CADENCE-INPUT-VFR-FORBIDDEN-001

Inputs classified as VFR MUST NOT use CADENCE resampling mode. The system MUST select an alternative resampling strategy that does not assume constant frame intervals.

### INV-CADENCE-STABILITY-OBSERVED-001

Frame timing stability classification MUST be derived from measured PTS deltas of decoded frames within an observation window. The container-reported `r_frame_rate`, `avg_frame_rate`, or codec-level timing metadata MUST NOT override observed instability.

### INV-CADENCE-JITTER-ACCUMULATION-001

Per-frame timing deviations that individually fall below the discontinuity threshold MUST still be evaluated for cumulative drift. If the accumulated deviation across the observation window exceeds the tolerance threshold, the input MUST be classified as VFR.

### INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001

The system MUST complete input classification (CFR or VFR) before selecting the resampling mode. The classification window MUST be bounded and MUST complete during the segment prime/prefill phase, not after output has begun.

---

## Stability Criteria

### Observation Window

Classification MUST be based on a bounded number of consecutive decoded frames observed during the segment prime phase. The window MUST be large enough to distinguish true VFR from transient startup jitter, but small enough to complete before the first output frame is committed.

### Interval Variance

For each frame in the observation window, the deviation from the nominal frame period MUST be computed. The input is classified as CFR only if the variance of observed intervals falls below a defined threshold.

### Cumulative Drift Check

In addition to per-frame variance, the cumulative sum of deviations across the observation window MUST be bounded. An input with low per-frame variance but systematic bias (e.g., consistently 0.5ms fast) MUST be classified as VFR if the projected cumulative error over the segment duration exceeds the tolerance.

### Nominal Frame Period

The nominal frame period is derived from the detected source frame rate (e.g., 1001/24000 seconds for 23.976fps). Detection uses the median of observed intervals in the first N frames, not container metadata.

---

## Mode Selection Rules

### CFR Input

When the input is classified as CFR:
- CADENCE resampling is permitted.
- The cadence pattern is computed from the ratio of source to output frame rate.
- Audio and video content-time advance in lockstep at the source frame rate.

### VFR Input

When the input is classified as VFR:
- CADENCE resampling MUST NOT be used.
- The system MUST fall back to a clock-driven resampling strategy where video frame selection is governed by the output clock, not by a predetermined cadence pattern.
- Under clock-driven resampling, each output tick selects the most recent decoded frame whose content-time does not exceed the current output time. Audio is emitted at its decoded rate.

### Indeterminate Input

When the observation window is insufficient to classify (e.g., too few frames decoded during prime), the system MUST default to the clock-driven strategy. Cadence resampling MUST NOT be used speculatively.

---

## Failure Modes

### A/V Drift

When CADENCE mode is applied to VFR input, the cadence pattern assumes uniform source timing. Each source frame's content-time deviates from the expected position. Audio, driven by a monotonic sample counter, advances at the correct rate. Video content-time accumulates error equal to the sum of per-frame deviations. Over a typical movie (90-120 minutes), even 0.5ms average per-frame error produces 1-2 seconds of audible A/V drift.

### Non-deterministic Frame Selection

VFR inputs under CADENCE mode produce a frame repeat/drop pattern that does not correspond to the actual content timing. Frames that should be held for display are dropped; frames that should be dropped are repeated. The visual result is uneven motion cadence and occasional frame judder.

### Cascade to Downstream Systems

A/V drift in the playout output propagates through MPEG-TS muxing, HLS segmentation, and client-side decoding. The drift cannot be corrected downstream because the muxed PTS values reflect the incorrect cadence timing. Client players that rely on PTS for A/V sync will reproduce the drift faithfully.

---

## Required Tests

- `runtime/tests/contracts/BlockPlan/CadenceInputStabilityTests.cpp`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `CFR_ClassifiedCorrectly` | INV-CADENCE-INPUT-CFR-REQUIRED-001 | 24fps source with uniform PTS deltas classified as CFR |
| `VFR_ClassifiedCorrectly` | INV-CADENCE-INPUT-VFR-FORBIDDEN-001 | Source with irregular PTS deltas classified as VFR |
| `VFR_CadenceForbidden` | INV-CADENCE-INPUT-VFR-FORBIDDEN-001 | VFR classification prevents CADENCE mode selection |
| `CFR_CadenceAllowed` | INV-CADENCE-INPUT-CFR-REQUIRED-001 | CFR classification permits CADENCE mode selection |
| `ContainerFpsNotTrusted` | INV-CADENCE-STABILITY-OBSERVED-001 | Source with r_frame_rate=120 but avg 24fps PTS detected as VFR |
| `MicroJitterAccumulates` | INV-CADENCE-JITTER-ACCUMULATION-001 | Per-frame 0.5ms bias within single-frame threshold but cumulative drift exceeds tolerance |
| `ClassificationBeforeOutput` | INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001 | Mode selection occurs during prime phase, not after first output tick |
| `IndeterminateDefaultsClock` | INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001 | Insufficient frames in prime window defaults to clock-driven mode |

---

## Enforcement Evidence

TODO
