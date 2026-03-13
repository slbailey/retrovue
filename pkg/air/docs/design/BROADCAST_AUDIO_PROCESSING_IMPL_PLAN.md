# Implementation Plan: Broadcast Audio Dynamic Range Processing v0.1

**Status:** PLAN — no production code yet
**Authority:** `pkg/air/docs/design/BROADCAST_AUDIO_PROCESSING.md` (revised 2026-03-12)
**Date:** 2026-03-12
**Revised:** 2026-03-12 (per-sample envelope, peak detection, return-value diagnostics, envelope stability test)

---

## 1. Repository Inspection Summary

### Audio path in the tick loop (PipelineManager.cpp)

The audio processing sequence occupies lines 3291–3332 of `PipelineManager.cpp`.
Three operations occur in strict order each tick:

| Step | Line | Operation |
|------|------|-----------|
| Pop | 3292 | `a_emit->TryPopSamples(samples_this_tick, audio_out)` |
| Gain | 3298–3303 | `blockplan::ApplyGainS16(audio_out, linear_gain)` (guarded by `gain_db != 0.0f`) |
| Encode | 3332 | `session_encoder->encodeAudioFrame(audio_out, audio_pts_90k, ...)` |

The new processor call will be inserted between Gain (line 3303) and the
PRE_ENCODE_DIAG block (line 3306), before Encode (line 3332).

### Segment boundary detection

`current_segment_index_` advances at line 5104 (`current_segment_index_++`)
inside the segment swap commit path. This is the single location where the
live segment identity changes. The processor must be reset here.

`ComputeSegmentSeamFrames()` resets `current_segment_index_ = 0` at line 4562
during block activation. The processor must also be reset at block activation.

### House audio format

Defined in `FrameRingBuffer.h:67–68`:
- `kHouseAudioSampleRate = 48000`
- `kHouseAudioChannels = 2`
- Sample format: S16 interleaved (implicit in `AudioFrame::data`)
- `AudioFrame` struct at line 72: `data` (vector<uint8_t>), `sample_rate`,
  `channels`, `pts_us`, `nb_samples`

### Existing audio utilities

| File | Role |
|------|------|
| `include/retrovue/blockplan/LoudnessGain.hpp` | Header-only. `GainDbToLinear()`, `ApplyGainS16()`. |
| `include/retrovue/blockplan/AudioLookaheadBuffer.hpp` | Thread-safe audio ring buffer. `TryPopSamples()`. |
| `include/retrovue/blockplan/PipelineManager.hpp` | Owns `audio_buffer_`, `current_segment_index_`, `live_parent_block_`. |
| `include/retrovue/playout_sinks/mpegts/EncoderPipeline.hpp` | `encodeAudioFrame()` accepts `AudioFrame` + `pts_90k`. |
| `include/retrovue/blockplan/BlockPlanTypes.hpp` | `Segment` struct with `gain_db` field. |
| `include/retrovue/buffer/FrameRingBuffer.h` | `AudioFrame` struct, house format constants. |

### Test conventions

All BlockPlan contract tests live in `tests/contracts/BlockPlan/`.
Naming convention: `*ContractTests.cpp`.
Tests are registered in `CMakeLists.txt` lines 452–497 under the
`blockplan_contract_tests` executable.
Tests use GTest, link against `retrovue_air_core`, and include the
`MakeFrame` / `ReadSample` helper pattern (see `LoudnessGainContractTests.cpp`).

---

## 2. Implementation Plan

### Phase 1: BroadcastAudioProcessor header

**New file:** `pkg/air/include/retrovue/blockplan/BroadcastAudioProcessor.hpp`

Header-only class. Rationale: follows the same pattern as `LoudnessGain.hpp`
(self-contained audio utility, no external dependencies beyond
`FrameRingBuffer.h` and `<cmath>`). If implementation complexity grows beyond
what is comfortable in a header, a `.cpp` can be extracted later.

**Class definition:**

```
class BroadcastAudioProcessor
```

**Public interface:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| Constructor | `BroadcastAudioProcessor()` | Initialize envelope state to unity. Precompute attack/release coefficients. |
| `Process` | `float Process(buffer::AudioFrame& frame)` | In-place DRC on S16 stereo frame. Mutates `frame.data` only. Returns the peak gain reduction in dB applied during this call (0.0 if no compression). |
| `Reset` | `void Reset()` | Reset envelope to unity. Called on segment/block boundaries. |

`Process` returns `float` (peak gain reduction in dB) rather than `void`.
This keeps the processor a pure signal processor with no telemetry state.
PipelineManager uses the return value for diagnostics (see Section 5).

**Private state:**

| Member | Type | Purpose |
|--------|------|---------|
| `envelope_level_` | `float` | Current smoothed envelope level as a linear amplitude. Initialized to `0.0f` (silence — no gain reduction). |
| `attack_coeff_` | `float` | Precomputed attack smoothing coefficient. |
| `release_coeff_` | `float` | Precomputed release smoothing coefficient. |

No RMS accumulator or window counter is needed. The envelope follower
operates per-sample using peak detection — no windowed averaging.

**Compiled constants (private static constexpr):**

| Constant | Value | Design doc reference |
|----------|-------|---------------------|
| `kThresholdDbfs` | `-18.0f` | Section 8, threshold rationale |
| `kRatio` | `3.0f` | Section 8 |
| `kAttackMs` | `5.0f` | Section 8 |
| `kReleaseMs` | `100.0f` | Section 8 |
| `kMakeupGainDb` | `3.0f` | Section 8 |
| `kSampleRate` | `48000` | House format |
| `kChannels` | `2` | House format |

Note: `kRmsWindowMs` is removed. Peak detection does not require a window.

**Processing logic (Process method):**

The processor implements a per-sample envelope follower with linked stereo
peak detection. Gain is computed and applied per sample — not per window or
per block.

For each sample pair (L, R interleaved) in the frame:

1. **Detect level (linked stereo, INV-BROADCAST-DRC-004):**
   Compute `level = max(abs(L), abs(R))` as a linear amplitude.
   This is the instantaneous peak level of the louder channel.

2. **Update envelope:**
   Apply exponential smoothing to `envelope_level_`:
   - If `level > envelope_level_`: use `attack_coeff_` (envelope rises
     toward signal).
   - If `level <= envelope_level_`: use `release_coeff_` (envelope decays
     toward signal).

   Attack and release smoothing coefficients are computed from the time
   constants and sample rate using a standard exponential envelope follower.
   The exact smoothing equation is an implementation detail — the contract
   requires only that the envelope converges within the specified time
   constants and produces no discontinuities.

3. **Compute gain reduction:**
   Convert `envelope_level_` to dBFS.
   - If `envelope_dbfs > kThresholdDbfs`:
     `reduction_db = (envelope_dbfs - kThresholdDbfs) * (1.0 - 1.0/kRatio)`
   - Else: `reduction_db = 0.0`

4. **Compute total linear gain:**
   `linear_gain = 10^((kMakeupGainDb - reduction_db) / 20.0)`

5. **Apply gain to this sample pair:**
   Multiply both L and R by `linear_gain`. Clamp each to int16 range
   (same clamping logic as `ApplyGainS16`). Because the gain is derived
   from the linked envelope, L and R always receive identical gain —
   stereo image is preserved.

6. **Track peak reduction** for the return value (local variable, not
   member state).

This per-sample loop ensures:
- No block/window boundary artifacts (gain changes smoothly every sample).
- Transients at any position in the frame are caught immediately by the
  attack envelope.
- The gain applied to sample N reflects the envelope state at sample N,
  not an average over a surrounding window.

**Reset method:**

Set `envelope_level_` to `0.0f` (silence — below any threshold, so gain
reduction is zero). This ensures the attack envelope ramps smoothly from
unity per design doc Section 7. No accumulator or counter state to clear.

### Phase 2: PipelineManager integration

**Modified file:** `pkg/air/include/retrovue/blockplan/PipelineManager.hpp`

Add one new member and diagnostic accumulators:

| Member | Type | Location |
|--------|------|----------|
| `broadcast_audio_processor_` | `std::unique_ptr<BroadcastAudioProcessor>` | Near `audio_buffer_` (after line 358) |
| `drc_segment_peak_reduction_db_` | `float` | Diagnostic: max reduction in current segment |
| `drc_segment_sum_reduction_db_` | `float` | Diagnostic: running sum for average |
| `drc_segment_ticks_compressed_` | `int` | Diagnostic: ticks with nonzero reduction |
| `drc_segment_ticks_total_` | `int` | Diagnostic: total ticks in segment |

The processor is constructed as `std::make_unique<BroadcastAudioProcessor>()`
during PipelineManager construction or at session start (same lifecycle as
`audio_buffer_`).

Diagnostic accumulators live on PipelineManager, not on the processor. The
processor is a pure signal processor; PipelineManager owns observability.

**Modified file:** `pkg/air/src/blockplan/PipelineManager.cpp`

Three insertion points:

**Insertion 1 — Tick loop audio path (after line 3303, before line 3305):**

After `ApplyGainS16` completes and before PRE_ENCODE_DIAG, call:
```
float reduction_db = broadcast_audio_processor_->Process(audio_out);
```

Then update the diagnostic accumulators:
```
drc_segment_ticks_total_++;
if (reduction_db > 0.0f) {
  drc_segment_ticks_compressed_++;
  drc_segment_sum_reduction_db_ += reduction_db;
  if (reduction_db > drc_segment_peak_reduction_db_)
    drc_segment_peak_reduction_db_ = reduction_db;
}
```

This satisfies INV-BROADCAST-DRC-001 (stage exists between normalization and
encoding) and INV-BROADCAST-DRC-002 (only `audio_out.data` is mutated).

No conditional guard is needed for v0.1 — the processor always runs. When
the signal is below threshold, gain reduction is zero and makeup gain is the
only effect. Future LRA-gated bypass would add a guard here.

**Insertion 2 — Segment advance (at line 5104, after `current_segment_index_++`):**

Before resetting, emit the diagnostic log for the completed segment:
```
[PipelineManager] BROADCAST_DRC_SEGMENT_SUMMARY
  segment_index=N
  peak_gain_reduction_db=X.X
  avg_gain_reduction_db=X.X
  ticks_compressed=N
  ticks_total=N
```

Then reset:
```
broadcast_audio_processor_->Reset();
drc_segment_peak_reduction_db_ = 0.0f;
drc_segment_sum_reduction_db_ = 0.0f;
drc_segment_ticks_compressed_ = 0;
drc_segment_ticks_total_ = 0;
```

This satisfies INV-BROADCAST-DRC-003 (envelope reset on every segment
boundary). The attack envelope provides the smooth ramp from unity — no
additional smoothing logic needed.

**Insertion 3 — Block activation (`ComputeSegmentSeamFrames`, near line 4562):**

```
broadcast_audio_processor_->Reset();
```

Plus reset the diagnostic accumulators. Block activation resets
`current_segment_index_ = 0`, which is a superset of segment transition.
The processor must also reset here to ensure no state carries from a prior
block.

### Phase 3: CMakeLists update

**Modified file:** `pkg/air/CMakeLists.txt`

No source file addition needed if `BroadcastAudioProcessor.hpp` remains
header-only (no `.cpp`). The header is included transitively through
`PipelineManager.hpp` → `BroadcastAudioProcessor.hpp`.

Add the new test file to the `blockplan_contract_tests` executable (after
line 489, following `LoudnessGainContractTests.cpp`):
```
tests/contracts/BlockPlan/BroadcastAudioProcessorContractTests.cpp
```

---

## 3. File Modification List

### New files

| File | Type | Purpose |
|------|------|---------|
| `pkg/air/include/retrovue/blockplan/BroadcastAudioProcessor.hpp` | Header | Processor class definition and implementation |
| `pkg/air/tests/contracts/BlockPlan/BroadcastAudioProcessorContractTests.cpp` | Test | Contract tests for INV-BROADCAST-DRC-001 through 004 |

### Modified files

| File | Change |
|------|--------|
| `pkg/air/include/retrovue/blockplan/PipelineManager.hpp` | Add `#include`, `broadcast_audio_processor_` member, diagnostic accumulators |
| `pkg/air/src/blockplan/PipelineManager.cpp` | Three insertions: tick loop Process call + diagnostics, segment advance log + Reset, block activation Reset |
| `pkg/air/CMakeLists.txt` | Add test file to `blockplan_contract_tests` sources |

### Unchanged files

| File | Reason |
|------|--------|
| `LoudnessGain.hpp` | Existing gain logic is untouched. ApplyGainS16 continues to run first. |
| `AudioLookaheadBuffer.hpp` | Buffer pop logic unchanged. |
| `EncoderPipeline.hpp/.cpp` | Encoder receives AudioFrame as before. No signature change. |
| `BlockPlanTypes.hpp` | No new segment fields. |
| `FrameRingBuffer.h` | House format unchanged. |
| All Core files | No Core changes. |
| `protos/playout.proto` | No proto changes. |

---

## 4. Test Strategy

### Contract tests (BroadcastAudioProcessorContractTests.cpp)

All tests operate on the processor in isolation using synthetic `AudioFrame`
objects constructed with the same `MakeFrame` helper pattern as
`LoudnessGainContractTests.cpp`.

**INV-BROADCAST-DRC-001 — Stage presence and positioning:**

| Test | Description |
|------|-------------|
| `ProcessExists_AcceptsHouseFormat` | Construct processor, call `Process()` on a valid S16 stereo 48kHz frame. No crash, no exception. Returns a float. |
| `ProcessOutput_IsHouseFormat` | After `Process()`, verify `frame.sample_rate`, `frame.channels`, `frame.nb_samples` are unchanged. |

**INV-BROADCAST-DRC-002 — Metadata preservation:**

| Test | Description |
|------|-------------|
| `SampleCount_Unchanged` | Create frame with known `nb_samples`. Process. Assert `nb_samples` identical. |
| `ChannelCount_Unchanged` | Create stereo frame. Process. Assert `channels == 2`. |
| `PTS_Unchanged` | Create frame with known `pts_us`. Process. Assert `pts_us` identical. |
| `DataSize_Unchanged` | Create frame. Process. Assert `data.size()` identical. |
| `SilenceInput_SilenceOutput` | Create zero-valued frame. Process. All output samples are zero (makeup gain applied to zero is still zero). |

**INV-BROADCAST-DRC-003 — Segment boundary reset:**

| Test | Description |
|------|-------------|
| `Reset_ClearsEnvelope` | Feed loud frames to build up gain reduction. Call `Reset()`. Feed identical loud frame. Verify first samples of output after reset have less gain reduction than steady-state (attack ramp from unity). |
| `Reset_NoDiscontinuity` | Feed loud frames. Call `Reset()`. Feed loud frame. Verify no sample in the post-reset frame exceeds the pre-reset peak by more than the makeup gain ceiling (no step-change artifact). |
| `ConsecutiveResets_Idempotent` | Call `Reset()` twice. Feed frame. Verify output identical to single-reset case. |

**INV-BROADCAST-DRC-004 — Linked stereo:**

| Test | Description |
|------|-------------|
| `LinkedStereo_LoudLeftReducesBoth` | Create frame with loud L, quiet R. Process. Verify both L and R are reduced (L drives the envelope, gain applied to both). |
| `LinkedStereo_LoudRightReducesBoth` | Create frame with quiet L, loud R. Process. Verify both L and R are reduced. |
| `LinkedStereo_SymmetricInput_SymmetricOutput` | Create frame with identical L and R. Process. Verify L and R outputs are identical. |
| `LinkedStereo_GainReductionEqual` | Create frame with different L and R levels, both above threshold. Process. Compute the effective gain ratio for L and R independently. Verify they are equal (same linear gain applied to both channels). |

**Compression behavior (functional correctness):**

| Test | Description |
|------|-------------|
| `BelowThreshold_MinimalChange` | Create frame at -30 dBFS (well below -18 threshold). Process. Output level equals input × makeup gain (no compression, only makeup). |
| `AboveThreshold_Reduced` | Create frame at -6 dBFS (12 dB above threshold). Process until steady state. Output peak is lower than input peak (compression active). |
| `MakeupGain_Applied` | Create frame below threshold. Process. Verify output is louder than input by approximately `kMakeupGainDb`. |
| `Clamp_NoWraparound` | Create frame at +0 dBFS (max S16). Process. All output samples are within [-32768, +32767]. |
| `ReturnsGainReduction` | Process frame above threshold. Verify return value > 0.0. Process frame below threshold at steady state. Verify return value == 0.0. |
| `ConstantTone_NoPumping` | Generate a constant-amplitude sine wave at -12 dBFS (above threshold) lasting ~5 seconds of samples. Feed through the processor in sequential frame-sized chunks. After the initial attack period, verify that the gain reduction stabilizes: the per-frame return values converge and the sample-to-sample gain variation falls below a tight tolerance. This catches envelope instability, oscillation, and coefficient errors. |

### Integration-level verification

These are not new test files but verification steps during implementation to
confirm the processor integrates correctly with the tick loop:

| Verification | Method |
|--------------|--------|
| Existing `LoudnessGainContractTests` still pass | `ctest --test-dir pkg/air/build -R LoudnessGain` |
| Existing `AudioLookaheadBufferTests` still pass | `ctest --test-dir pkg/air/build -R AudioLookahead` |
| Full `blockplan_contract_tests` suite green | `ctest --test-dir pkg/air/build -R BlockPlanContracts` |
| PRE_ENCODE_DIAG output shows amplitude change | Manual run with theatrical content; compare s16_min/s16_max before/after processor integration |

---

## 5. Diagnostics / Observability

### Architecture: processor returns, PipelineManager aggregates

The processor is a pure signal processor. It carries no telemetry state.
`Process()` returns the peak gain reduction (dB) applied during that call.
PipelineManager accumulates per-segment statistics from the return values:

| Accumulator (on PipelineManager) | Type | Purpose |
|----------------------------------|------|---------|
| `drc_segment_peak_reduction_db_` | `float` | Maximum reduction returned across ticks in segment |
| `drc_segment_sum_reduction_db_` | `float` | Sum of nonzero reductions (for computing average) |
| `drc_segment_ticks_compressed_` | `int` | Count of ticks where return value > 0.0 |
| `drc_segment_ticks_total_` | `int` | Total ticks processed in segment |

This separation keeps the processor deterministic and reusable. Telemetry
is exclusively PipelineManager's concern.

### Per-segment log

At the segment-advance Reset point (line 5104 area), emit a single log line
summarizing the processor's activity during the completed segment:

```
[PipelineManager] BROADCAST_DRC_SEGMENT_SUMMARY
  segment_index=N
  peak_gain_reduction_db=X.X
  avg_gain_reduction_db=X.X
  ticks_compressed=N
  ticks_total=N
```

The log is `Logger::Info` level — one line per segment, not per tick. This
adds negligible log volume (typically 1–10 lines per block).

### No per-tick logging in v0.1

Per-tick DRC logging would produce one line per 33ms (~30 lines/second) and
is not justified for v0.1. The per-segment summary provides sufficient
tuning and incident data. Per-tick logging can be added behind a `TRACE`
guard if needed during debugging.

### Interaction with existing PRE_ENCODE_DIAG

The existing `PRE_ENCODE_DIAG` block (lines 3306–3330) logs `s16_min`/`s16_max`
of `audio_out` before encoding. Because the processor runs before this
diagnostic, PRE_ENCODE_DIAG will now report post-DRC amplitudes. This is
the correct behavior — the diagnostic shows what actually reaches the encoder.
No change to PRE_ENCODE_DIAG is needed.

---

## 6. Validation Checklist

| Check | Status |
|-------|--------|
| Plan grounded in exact file paths and line numbers | PASS |
| No Core files modified | PASS |
| No proto or schema changes | PASS |
| No new top-level directories | PASS |
| New header in existing `include/retrovue/blockplan/` | PASS |
| New test in existing `tests/contracts/BlockPlan/` | PASS |
| House format unchanged (S16 stereo 48 kHz) | PASS |
| ApplyGainS16 logic unchanged and called before processor | PASS |
| Processor owned by PipelineManager (same lifecycle as audio_buffer_) | PASS |
| Reset on segment boundary (line 5104) | PASS |
| Reset on block activation (line 4562) | PASS |
| Process call in tick loop between gain and encode | PASS |
| Linked stereo detection is a design requirement, not optional | PASS |
| Segment boundary ramp via attack envelope, no step discontinuity | PASS |
| INV-BROADCAST-DRC-001: stage presence tested | PASS |
| INV-BROADCAST-DRC-002: metadata preservation tested | PASS |
| INV-BROADCAST-DRC-003: reset + smooth ramp tested | PASS |
| INV-BROADCAST-DRC-004: linked stereo tested | PASS |
| Diagnostics: per-segment summary log, no per-tick spam | PASS |
| All existing tests expected to remain green | PASS |
| No production code included in this plan | PASS |
| **Rev1: Per-sample envelope follower, not windowed block processing** | PASS |
| **Rev1: Peak detection `max(abs(L),abs(R))`, no RMS accumulator** | PASS |
| **Rev1: Coefficient formula not locked — standard exponential follower** | PASS |
| **Rev1: Diagnostics via return value, not processor-internal state** | PASS |
| **Rev1: ConstantTone_NoPumping envelope stability test added** | PASS |
