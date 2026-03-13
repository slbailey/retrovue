# Design: Wide-LRA Content Normalization (v0.2)

**Status:** DRAFT — design only, no implementation
**Scope:** Core loudness enrichment and normalization policy
**Date:** 2026-03-12
**Revised:** 2026-03-12 (contract separation, policy defaults, rollout safety)
**Depends on:** INV-LOUDNESS-NORMALIZED-001, INV-BROADCAST-DRC-001

---

## 1. Problem Statement

RetroVue's loudness normalization pipeline (INV-LOUDNESS-NORMALIZED-001) aligns all
content to -24 LUFS integrated (ATSC A/85) by applying a constant per-asset gain.
For content with a wide loudness range (LRA), this produces perceptually wrong
results: the integrated measurement is dominated by loud effects and music, so the
computed gain works against dialogue intelligibility.

**Measured examples (stereo downmix, full file):**

| Content | Integrated | LRA | True Peak | gain_db | Content Class |
|---------|-----------|-----|-----------|---------|---------------|
| Ghostbusters (1984) | -22.1 LUFS | 21.1 LU | -1.4 dBFS | -1.9 dB | theatrical 5.1 |
| Babylon 5 S05E13 | -25.8 LUFS | 16.0 LU | -1.6 dBFS | +1.8 dB | TV 5.1 |
| Cheers S01E05 | -24.5 LUFS | 9.0 LU | -7.1 dBFS | +0.5 dB | broadcast stereo |

Ghostbusters receives `gain_db = -1.9 dB` — a volume _reduction_. This is correct
by the integrated metric, but dialogue passages sit at **-38 to -40 LUFS** (LRA low
boundary). After normalization they are attenuated further to ~-41 to -43 LUFS —
inaudible on consumer equipment. Meanwhile, Cheers dialogue occupies -25 to -30 LUFS.

The v0.1 DRC (INV-BROADCAST-DRC-001, threshold -18 dBFS) cannot compensate. A
structured tuning pass (2026-03-12) confirmed that no single-band global DRC profile
solves wide-LRA dialogue without unacceptable pumping damage to broadcast-native
content.

**The root cause is in normalization policy, not in compression parameters.** When
integrated LUFS is dominated by loud effects, using it as the sole normalization
reference produces a gain_db that works against dialogue intelligibility.

## 2. Scope and Constraints

This design addresses only the Core-side normalization policy. It does not propose:
- Changes to AIR's DRC parameters or architecture
- New gRPC message fields or segment schema changes
- Multi-band processing or frequency-domain analysis
- Real-time adaptive normalization within AIR

All changes must fit within the existing data flow:

```
LoudnessEnricher.measure_loudness(file_path)
  → asset_probed.payload["loudness"]
    → CatalogResolver → AssetMetadata.loudness_gain_db
      → ScheduledSegment.gain_db
        → BlockPlan segment dict
          → gRPC BlockSegment.gain_db
            → AIR ApplyGainS16 (constant linear scalar)
              → AIR BroadcastAudioProcessor (DRC)
```

The output of this design is a potentially different `gain_db` value for wide-LRA
content. AIR applies it identically to any other gain_db — no AIR changes required.

## 3. Policy Boundary

Core decides normalization gain policy. AIR remains unchanged and applies `gain_db`
mechanically.

- **Core's authority:** Core measures loudness, evaluates content characteristics
  (integrated LUFS, LRA), and computes the single `gain_db` value that represents
  the normalization policy decision. The wide-LRA supplement is part of this policy
  decision — it is not a new processing stage, but a refinement of how Core computes
  the gain it has always been responsible for.

- **AIR's role:** AIR receives `gain_db` on each segment via gRPC and applies it as
  a constant linear scalar (`10^(gain_db/20)`). AIR does not know or care whether
  the value was derived from integrated LUFS alone, from an LRA-aware formula, or
  from any other future policy. The DRC then processes the normalized audio. Neither
  AIR component changes.

- **Boundary invariant:** `gain_db` is the sole normalization signal that crosses the
  Core/AIR boundary. Core may change how it computes `gain_db` without coordinating
  with AIR, provided the value remains a constant dB gain to be applied linearly to
  all samples in the segment.

## 4. Candidate Approaches

### 4.1. Option A: LRA-Aware Supplemental Gain

**Concept:** Measure LRA alongside integrated LUFS. For assets whose LRA exceeds a
threshold, apply a bounded supplemental gain that shifts the normalization reference
toward the quiet end of the dynamic range.

**Measurement method:**

The existing ffmpeg ebur128 filter already reports LRA in its Summary output:

```
  Loudness range:
    LRA:        21.1 LU
    LRA low:   -38.4 LUFS
    LRA high:  -17.3 LUFS
```

No new measurement tool is needed. The enricher parses one additional regex from
the same ffmpeg run.

**Gain computation:**

```python
def compute_gain_db(integrated_lufs: float, *, lra_lu: float | None = None) -> float:
    base_gain = TARGET_LUFS - integrated_lufs

    if lra_lu is None or lra_lu <= LRA_THRESHOLD:
        return base_gain

    supplement = min((lra_lu - LRA_THRESHOLD) * SUPPLEMENT_SCALE, MAX_SUPPLEMENT_DB)
    return base_gain + supplement
```

**Example outcomes:**

| Content | Integrated | LRA | Base gain | Supplement | Final gain_db |
|---------|-----------|-----|-----------|------------|---------------|
| Ghostbusters | -22.1 | 21.1 | -1.9 | +3.1 | **+1.2** |
| Babylon 5 | -25.8 | 16.0 | +1.8 | +0.5 | **+2.3** |
| Cheers | -24.5 | 9.0 | +0.5 | 0.0 | **+0.5** |

Ghostbusters gain moves from -1.9 dB (base) to +1.2 dB — dialogue lifted by 3.1 dB.
Cheers is unchanged. Babylon 5 gets a minor 0.5 dB lift.

**Problem solved:** Partially. Narrows the gap between theatrical and broadcast
dialogue levels. Does NOT fully solve it — Ghostbusters dialogue is still ~8 dB
quieter than Cheers dialogue, down from ~12 dB. The improvement is meaningful but
not complete.

**Architectural fit:** Excellent. Changes only `compute_gain_db()` and the enricher's
measurement parsing. No new tables, no schema changes, no AIR changes.

**Data model impact:**
- `asset_probed.payload["loudness"]` gains one new optional field:
  `loudness_range_lu`
- Existing fields (`integrated_lufs`, `gain_db`, `target_lufs`) unchanged in
  meaning; `gain_db` value changes for qualifying assets
- The `gain_db` field remains the sole value propagated to segments and AIR

**Metadata needed:** LRA (already available from ebur128 output).

**gRPC / segment schema changes:** None. `gain_db` is the only field that crosses
the boundary, and its semantics are unchanged (constant linear gain to apply).

**Interaction with AIR DRC:**
- Assets with supplemental gain will have higher signal levels entering the DRC
- Ghostbusters peaks move from ~-23 dBFS to ~-20 dBFS — still below the -18 dBFS
  threshold in most scenes, but loud scenes will start engaging the compressor
- This is the intended interaction: normalization lifts the floor, DRC catches
  any peaks that exceed broadcast headroom

**Risks:**
1. **Peak pressure:** The supplement is part of the gain computation, not a
   separate processing stage. For Ghostbusters:
   - Current pipeline: `base_gain = -1.9`, peak = `-1.4 + (-1.9) = -3.3 dBFS`
   - With supplement: `base_gain = -1.9`, `supplement = +3.1`, `final_gain = +1.2`,
     peak = `-1.4 + 1.2 = -0.2 dBFS`
   The supplement partially offsets the attenuation but pushes the peak to
   -0.2 dBFS — **above the -2.0 dBFS broadcast safety ceiling** (Section 10.3).
   At -0.2 dBFS, encoder overs and codec reconstruction peaks will produce
   clipping artifacts. The Section 10.3 guardrail would flag Ghostbusters for
   review, and the policy constants (SUPPLEMENT_SCALE or MAX_SUPPLEMENT_DB) would
   need tightening before this asset's supplement is safe for playout. For content
   where `base_gain` is already positive (quiet + wide-LRA), the supplement adds
   to that positive gain and peak validation is required (see Section 10.3).
2. **Over-lifting quiet content:** An asset with high LRA due to long silent
   passages (not dynamic theatrical content) would receive unwarranted boost.
   The LRA threshold and max supplement cap provide a conservative bound.
3. **Tuning sensitivity:** The policy constants are heuristic and need empirical
   validation against the full library (see Section 5).

### 4.2. Option B: Dialogue-Gated Loudness Normalization (Deferred)

**Concept:** Measure dialogue-level loudness separately from integrated loudness.
For qualifying wide-LRA assets, compute `gain_db` from the dialogue measurement
rather than the integrated measurement.

**Measurement method:**

ITU-R BS.1770-4 defines dialogue-gated loudness, but FFmpeg's ebur128 filter does
not expose it. Practical approximation: use `LRA low` (10th percentile of short-term
loudness) as a dialogue proxy and blend the normalization reference between integrated
and LRA low proportionally to LRA excess.

**Example outcomes:**

| Content | Integrated | LRA low | Blend | Reference | gain_db |
|---------|-----------|---------|-------|-----------|---------|
| Ghostbusters | -22.1 | -38.4 | 0.31 | -27.1 | **+3.1** |
| Babylon 5 | -25.8 | -37.6 | 0.05 | -26.4 | **+2.4** |
| Cheers | -24.5 | -30.9 | 0.0 | -24.5 | **+0.5** |

Ghostbusters gain moves from -1.9 dB (base) to **+3.1 dB** — a 5.0 dB dialogue lift.
More effective than Option A, but creates peak pressure that requires a DRC limiter.

**Why deferred:** Option B produces gains that will clip without DRC peak limiting.
The DRC design doc defers a limiter to v0.2+. Option B should not ship until:
- A peak limiter exists in the AIR DRC chain
- The blend formula is validated across the full library
- The coupling between normalization gain and DRC peak control is accepted

Option B remains a valid future upgrade. Switching from A to B requires only
changing `compute_gain_db()` — no data model, schema, or AIR changes.

## 5. Policy Defaults

The following constants govern the v0.2 supplement behavior. They are **initial
defaults chosen for conservative rollout**, not permanent values. All three are
subject to empirical tuning based on library-wide LRA distribution analysis and
operator listening evaluation.

| Constant | Initial Default | Rationale |
|----------|----------------|-----------|
| `LRA_THRESHOLD` | 15.0 LU | Above this, content qualifies for supplement. Chosen to exclude broadcast-native content (Cheers: 9.0 LU) while catching theatrical (Ghostbusters: 21.1 LU) and TV-5.1 borderline (B5: 16.0 LU). |
| `SUPPLEMENT_SCALE` | 0.5 dB/LU | dB of supplement per LU of LRA above threshold. Conservative: produces +3.1 dB for Ghostbusters. A scale of 0.75 or 1.0 would be more aggressive. |
| `MAX_SUPPLEMENT_DB` | 6.0 dB | Hard cap. Prevents runaway boost on extreme-LRA content. At 0.5 dB/LU, the cap is reached at LRA = 27 LU. |

These defaults should be validated by:
1. Measuring LRA across the full enriched library and examining the distribution
2. Identifying the quietest wide-LRA assets and checking that `base_gain + supplement`
   does not create dangerous peak levels
3. A/B listening comparison on representative theatrical, TV-5.1, and broadcast content

The constants live as module-level values in `loudness_enricher.py`, not in a
configuration system. If future evidence warrants a change, the values are updated
in code and assets are re-enriched.

## 6. Comparison

| Criterion | Option A: LRA-Aware Supplement | Option B: Dialogue-Gated Blend |
|-----------|-------------------------------|-------------------------------|
| **Dialogue lift for Ghostbusters** | +3.1 dB (moderate) | +6.2 dB (significant) |
| **Risk of peak clipping** | Moderate (net gain +1.2 dB for Ghostbusters; peak at -0.2 dBFS) | **High** (+3.1 dB on -1.4 dBFS peaks) |
| **Broadcast content impact** | None | None |
| **B5-class content impact** | +0.5 dB (gentle) | +1.3 dB (gentle) |
| **Computation complexity** | Simple (one threshold, one scale) | Moderate (blend function) |
| **New metadata fields** | 1 (LRA) | 3 (LRA, LRA low, LRA high) |
| **Tuning parameters** | 3 (threshold, scale, cap) | 3 (threshold, divisor, blend cap) |
| **Sensitivity to misclassification** | Low (bounded supplement) | Moderate (blend can over-lift) |
| **AIR changes required** | None | None |
| **Interaction with DRC** | Clean — rarely pushes signal into DRC range | Active — regularly engages DRC, relies on it for peak control |
| **Works without DRC** | Yes — conservative standalone improvement | **Partially** — needs DRC limiter to prevent clipping |

## 7. Recommendation: Option A (LRA-Aware Supplemental Gain)

Option A is recommended for v0.2 because:

1. **It is the least aggressive approach that produces measurable improvement.**
   Ghostbusters dialogue gains 3.1 dB of supplement, closing the gap with
   broadcast content. This is meaningful but conservative.

2. **Peak pressure is bounded and reviewable.** For content like Ghostbusters
   (integrated above target, wide LRA), the supplement partially offsets the
   base attenuation (net gain +1.2 dB, peak at -0.2 dBFS). The -2.0 dBFS
   guardrail in Section 10.3 flags assets that need policy constant adjustment
   before rollout.

3. **It does not depend on the DRC for most content.** Option B produces gains
   that will clip without DRC enforcement. Option A may exceed the -2.0 dBFS
   ceiling for hot+wide-LRA content (e.g., Ghostbusters), which requires either
   policy constant adjustment or DRC peak limiting before those assets are safe.

4. **It is simple and auditable.** One new metric (LRA), one threshold, one linear
   scale, one cap. The supplement is always positive and bounded.

5. **It is forward-compatible.** If Option B's more aggressive approach is later
   validated (with a limiter in the DRC chain), switching from A to B requires
   only changing `compute_gain_db()`. No data model, schema, or AIR changes.

## 8. Detailed Design: Option A Implementation

### 8.1. Enricher Changes

**File:** `pkg/core/src/retrovue/adapters/enrichers/loudness_enricher.py`

Add LRA parsing to `measure_loudness()`:

```python
_LRA_RE = re.compile(r"LRA:\s+([\d.]+)\s+LU")

def measure_loudness(self, file_path: str) -> dict[str, Any]:
    # ... existing ffmpeg ebur128 run (unchanged) ...
    # ... existing integrated_lufs parsing (unchanged) ...

    # Parse LRA from the same Summary block
    lra_match = _LRA_RE.search(search_text)
    lra_lu = float(lra_match.group(1)) if lra_match else None

    gain_db = compute_gain_db(integrated_lufs, lra_lu=lra_lu)

    result = {
        "integrated_lufs": integrated_lufs,
        "gain_db": gain_db,
        "target_lufs": TARGET_LUFS,
    }
    if lra_lu is not None:
        result["loudness_range_lu"] = lra_lu
    return result
```

Modify `compute_gain_db()`:

```python
LRA_THRESHOLD: float = 15.0
MAX_SUPPLEMENT_DB: float = 6.0
SUPPLEMENT_SCALE: float = 0.5

def compute_gain_db(integrated_lufs: float, *, lra_lu: float | None = None) -> float:
    base_gain = TARGET_LUFS - integrated_lufs

    if lra_lu is None or lra_lu <= LRA_THRESHOLD:
        return base_gain

    supplement = min((lra_lu - LRA_THRESHOLD) * SUPPLEMENT_SCALE, MAX_SUPPLEMENT_DB)
    return base_gain + supplement
```

### 8.2. Backward Compatibility

- Assets already measured (with only `integrated_lufs` and `gain_db`) continue to
  use their existing `gain_db` until re-enriched. No LRA data = no supplement.
- `get_gain_db_from_probed()` continues to read `gain_db` from the payload.
  It does not compute the supplement — that happens only at measurement time.
- `needs_loudness_measurement()` returns `True` when `loudness_range_lu` is
  missing, triggering re-measurement via the existing lazy mechanism.

### 8.3. Data Model

No new tables. No schema migration. The `asset_probed` JSONB payload gains:

```json
{
  "loudness": {
    "integrated_lufs": -22.1,
    "gain_db": 0.0,
    "target_lufs": -24.0,
    "loudness_range_lu": 21.1
  }
}
```

The supplement amount is not stored separately — it is implied by the difference
between `gain_db` and `(target_lufs - integrated_lufs)`. This avoids redundant data.

### 8.4. No AIR Changes

AIR receives `gain_db` on each segment via gRPC. It applies `10^(gain_db/20)` as
a constant linear scalar. The DRC then processes the normalized audio. Neither AIR
component is aware of how `gain_db` was computed. This is by design — Core owns
normalization policy, AIR enforces it mechanically. See Section 3 (Policy Boundary).

## 9. Contracts and Invariants

### 9.1. INV-LOUDNESS-NORMALIZED-001 (Unchanged)

INV-LOUDNESS-NORMALIZED-001 remains a behavioral normalization contract. It defines:

- All broadcast audio MUST be loudness-normalized before playout.
- The normalization target is -24 LUFS integrated (ATSC A/85).
- Normalization is expressed as a constant per-segment `gain_db` value.
- Unmeasured assets receive `gain_db = 0.0`.
- AIR applies `gain_db` as a constant linear scalar to all samples in the segment.
- `gain_db` is the sole normalization signal that crosses the Core/AIR boundary.

This contract defines the _outcome_ (content is normalized to target) and the
_mechanism_ (constant linear gain per segment). It does not prescribe how Core
computes the `gain_db` value — that is normalization policy, owned by Core.

The wide-LRA supplement is a refinement of Core's normalization policy. It does not
change INV-LOUDNESS-NORMALIZED-001 because the contract already permits Core to
compute `gain_db` by any method that achieves the normalization outcome.

### 9.2. New: INV-WIDE-LRA-SUPPLEMENT-001

**Wide-LRA content MAY receive a bounded supplemental normalization gain
when the normalization policy determines it improves dialogue intelligibility.**

This invariant governs the wide-LRA supplement policy within Core's normalization
computation. It is a policy contract, not a behavioral contract for AIR.

1. When the supplement policy is active and LRA data is available and exceeds
   the qualifying threshold, Core adds a non-negative supplement to the base
   normalization gain.
2. The supplement MUST be bounded: `0 <= supplement_db <= MAX_SUPPLEMENT_DB`.
3. The supplement MUST be zero when LRA is absent or below the qualifying threshold.
4. The supplement MUST be monotonically non-decreasing with LRA.
5. Content with narrow LRA (broadcast-native) MUST NOT be affected.
6. The supplement is computed at enrichment time and baked into `gain_db`. AIR
   is not aware of the supplement — it sees only `gain_db`.

### 9.3. New: INV-LOUDNESS-LRA-PERSISTENCE-001

**Loudness enrichment MUST persist LRA when available.**

1. `loudness_range_lu` MUST be stored in `asset_probed.payload["loudness"]` when
   the ebur128 Summary reports LRA.
2. Assets with loudness data but without `loudness_range_lu` MUST be eligible for
   re-enrichment via the existing lazy mechanism.
3. `loudness_range_lu` is informational metadata within Core. It does not cross
   the Core/AIR boundary. Only `gain_db` reaches AIR.

## 10. Rollout Safety

### 10.1. Lazy Re-enrichment

The existing background measurement mechanism in `dsl_schedule_service.py` triggers
re-measurement when `needs_loudness_measurement()` returns `True`. Updating this
function to also check for missing `loudness_range_lu` enables lazy re-enrichment
with no new infrastructure. Assets are re-measured when their next schedule block
is compiled.

This is the default rollout path. It requires no operator action and poses no risk
to assets that are not actively scheduled. Assets with existing loudness data but
missing LRA will automatically be re-enriched over time via this mechanism — all
966 currently-enriched assets will gradually be re-probed as they are scheduled.

### 10.2. Batch Re-enrichment

For faster adoption, an optional batch re-enrichment path:
- A CLI command (or script) that queries all assets with loudness data but missing
  `loudness_range_lu`, and re-runs `measure_loudness()` for each.
- This accelerates LRA population for the 966 currently-enriched assets.
- Not required for correctness — lazy re-enrichment reaches the same end state.

### 10.3. Peak Validation Before Broad Rollout

Before enabling the supplement for all content, validate peak behavior on the
most sensitive class: **quiet content with wide LRA**. These assets receive both
a positive base gain (because they are below -24 LUFS) and a positive supplement
(because they have wide LRA). The combined gain may push peaks into dangerous
territory.

Validation procedure:
1. Query the library for assets with `integrated_lufs < -26` and
   `audio.channels > 2` (proxy for wide-LRA until LRA is measured).
2. Measure LRA for the 10 quietest multichannel assets.
3. Compute `base_gain + supplement` for each.
4. Check that `true_peak_dbfs + total_gain <= -2.0 dBFS` — if any asset
   violates this, the supplement scale or cap may need tightening before rollout.
   The -2.0 dBFS guardrail provides headroom for encoder reconstruction overs
   and downstream codec peak overshoot (standard broadcast safety margin).

This validation should be completed before the supplement is enabled in production.
If any asset produces a combined gain that would clip, the policy defaults should
be adjusted first.

## 11. Implementation Impact Summary

| Component | File | Change |
|-----------|------|--------|
| Enricher | `loudness_enricher.py` | Add `_LRA_RE`, add policy constants, modify `compute_gain_db()`, modify `measure_loudness()`, modify `needs_loudness_measurement()` |
| Contract tests | `test_inv_loudness_normalized_001.py` | Add tests for supplement behavior (new test class) |
| Contract tests | (new file) `test_inv_wide_lra_supplement_001.py` | Supplement bound, monotonicity, zero-below-threshold tests |
| Design doc | `BROADCAST_AUDIO_PROCESSING.md` | Update Section 2 to reference v0.2 normalization enhancement |

**Not changed:**
- `catalog_resolver.py` — reads `gain_db` from probed, unchanged
- `schedule_items_reader.py` — passes `gain_db` to segments, unchanged
- `dsl_schedule_service.py` — serializes/deserializes `gain_db`, unchanged
- `playout_session.py` — sends `gain_db` via gRPC, unchanged
- `playout.proto` — `BlockSegment.gain_db` field unchanged
- `PipelineManager.cpp` — applies `gain_db` as linear scalar, unchanged
- `BroadcastAudioProcessor.hpp` — DRC parameters unchanged

**Total production files changed: 1** (`loudness_enricher.py`)

## 12. Open Questions Requiring Validation

1. **LRA threshold value (15 LU).** Based on three test assets. Should be validated
   against the full measured library. Run batch LRA measurement on the 966
   already-measured assets and examine the distribution. If the 15 LU cutoff
   catches more than ~20% of content, it may be too aggressive.

2. **Supplement scale factor (0.5 dB/LU).** Conservative by design. Ghostbusters
   (LRA 21.1) gets only +3.1 dB of supplement, which leaves a ~9 dB gap with
   broadcast dialogue. A scale of 0.75 or 1.0 would be more aggressive but
   increases peak pressure risk. Should be A/B tested with real playback.

3. **Peak headroom for quiet+wide-LRA content.** For content that is both quiet
   (integrated below target) and wide-LRA, the supplement adds to an
   already-positive base gain: e.g., `base_gain = +6.0, supplement = +3.0,
   total = +9.0 dB`. Should be validated per the procedure in Section 10.3.

4. **Re-enrichment latency.** Lazy re-enrichment triggers at schedule compilation.
   For the 966 already-measured assets, they will only get LRA data when their
   next block is compiled. This could take days for infrequently-scheduled content.
   Batch re-enrichment (Section 10.2) mitigates this.

5. **Interaction with future limiter.** The DRC design doc defers a limiter to
   v0.2+. If the limiter is implemented, Option B (dialogue-gated blend) becomes
   viable because the limiter would catch the peak pressure that Option B creates.
   Should the limiter be prioritized alongside or after normalization enhancement?
