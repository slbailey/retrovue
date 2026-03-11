# Design: Time-Based Frame Resampling

**Status:** DRAFT — design only, no implementation
**Scope:** AIR PipelineManager frame selection
**Date:** 2026-03-11

---

## 1. Current Behavior

### 1.1 Cadence Decision Authority

Frame selection (advance vs repeat) lives in a single location:

**`PipelineManager.cpp` lines 1716–1732** — the Bresenham accumulator in the tick loop.

```
Per output tick:
  budget_num += increment           // increment = input_fps.num × output_fps.den
  if budget_num >= budget_den:      // budget_den = output_fps.num × input_fps.den
    budget_num -= budget_den
    → ADVANCE (pop from VideoLookaheadBuffer)
  else:
    → REPEAT (re-encode last_good_video_frame_)
```

Four member variables own this state (`PipelineManager.hpp:458-461`):
- `frame_selection_cadence_enabled_`
- `frame_selection_cadence_budget_num_` (accumulator)
- `frame_selection_cadence_budget_den_` (threshold)
- `frame_selection_cadence_increment_` (per-tick add)

### 1.2 Initialization Points

| Function | File:Line | When |
|----------|-----------|------|
| `InitFrameSelectionCadenceForLiveBlock()` | PipelineManager.cpp:4150 | First block, post-rotation |
| `RefreshFrameSelectionCadenceFromLiveSource()` | PipelineManager.cpp:~4280 | Segment swap (new source FPS) |

Both read the live TickProducer's `GetInputRationalFps()`, snap to standard via `SnapToStandardRationalFps()`, then compute increment/threshold.

### 1.3 Three ResampleMode Paths (TickProducer)

`TickProducer.cpp` has a separate, older resample concept (`ResampleMode::OFF/DROP/CADENCE`) that controls *decoding* behavior — how many input frames to decode per output tick. This is **distinct** from the PipelineManager Bresenham:

| Mode | Decodes per tick | Frame selection |
|------|-----------------|-----------------|
| OFF | 1 | 1:1 |
| DROP | N (integer ratio) | First video, all audio |
| CADENCE | 1 | Defers to PipelineManager Bresenham |

In CADENCE mode, TickProducer decodes 1 frame per call. The PipelineManager controls whether to *call* TryPopFrame at all (advance) or re-use the previous frame (repeat).

### 1.4 Output PTS Computation

**Video PTS** (`PipelineManager.cpp:1333`):
```
video_pts_90k = clock->FrameIndexToPts90k(session_frame_index - pts_origin_frame_index)
```

**OutputClock** (`OutputClock.hpp`):
```
FrameIndexToPts90k(n) = n × frame_duration_90k
                       = n × round(90000 × fps_den / fps_num)
```

PTS is purely a function of the output frame index on the rational tick grid. It is **independent** of cadence decisions.

### 1.5 Frame Buffering

- `VideoLookaheadBuffer`: background FillLoop decodes ahead into a deque of `VideoBufferFrame`
- FillLoop is **condvar-driven** (wakes on consumer pop), not tick-driven
- `cadence_active` is **forced false** in FillLoop (INV-CADENCE-SINGLE-AUTHORITY)
- Consumer: PipelineManager calls `TryPopFrame()` on ADVANCE ticks only
- On REPEAT: `last_good_video_frame_` is re-encoded; no pop occurs (INV-CADENCE-POP-001)

### 1.6 Audio Model

- Audio is consumed every tick regardless of ADVANCE/REPEAT (audio is continuous)
- Per-tick sample count: `next_total = ((tick+1) × 48000 × fps_den) / fps_num`; `samples_this_tick = next_total - emitted_so_far` (rational, drift-free)
- Audio PTS: `(audio_samples_emitted × 90000) / 48000`

---

## 2. Proposed Behavior: Time-Based Resampling

### 2.1 Core Model

Replace the Bresenham accumulator with a direct time-domain mapping:

```
For output tick N (0-indexed within a cadence epoch):
  output_time_us(N) = floor(N × 1_000_000 × out_den / out_num)
  source_frame_index(N) = floor(output_time_us(N) × in_num / (1_000_000 × in_den))
```

Equivalently, using only integer arithmetic:

```
source_frame_index(N) = floor(N × in_num × out_den / (out_num × in_den))
```

The frame to display at output tick N is source frame `source_frame_index(N)`.

When `source_frame_index(N) == source_frame_index(N-1)`, the same source frame is displayed again — a "repeat" emerges naturally without any accumulator state.

### 2.2 Decision Per Tick

```
prev_source = source_frame_index(N - 1)    // or -1 for tick 0
curr_source = source_frame_index(N)

if curr_source > prev_source:
  → ADVANCE: pop one frame from VideoLookaheadBuffer
else:
  → REPEAT: re-encode last_good_video_frame_
```

### 2.3 State Required

Replace the four accumulator variables with:

| Variable | Type | Purpose |
|----------|------|---------|
| `resample_enabled_` | `bool` | Gate (replaces `frame_selection_cadence_enabled_`) |
| `resample_tick_` | `int64_t` | Tick counter within cadence epoch (0 at init/reset) |
| `resample_in_num_` | `int64_t` | Source FPS numerator |
| `resample_in_den_` | `int64_t` | Source FPS denominator |
| `resample_out_num_` | `int64_t` | Output FPS numerator |
| `resample_out_den_` | `int64_t` | Output FPS denominator |

Helper (pure function, no state mutation):

```cpp
static int64_t SourceFrameForTick(int64_t tick, int64_t in_num, int64_t in_den,
                                   int64_t out_num, int64_t out_den) {
  // 128-bit intermediate to prevent overflow
  using Wide = __int128;
  return static_cast<int64_t>(
      (static_cast<Wide>(tick) * in_num * out_den) / (out_num * in_den));
}
```

### 2.4 Equivalence to Bresenham (23.976 → 29.97)

For `in = 24000/1001`, `out = 30000/1001`:

```
source_frame_index(N) = floor(N × 24000 × 1001 / (30000 × 1001))
                       = floor(N × 24000 / 30000)
                       = floor(N × 4/5)
```

| Tick N | source_frame | advance? |
|--------|-------------|----------|
| 0 | 0 | advance |
| 1 | 0 | repeat  |
| 2 | 1 | advance |
| 3 | 2 | advance |
| 4 | 3 | advance |
| 5 | 4 | advance |
| 6 | 4 | repeat  |
| 7 | 5 | advance |
| 8 | 6 | advance |
| 9 | 7 | advance |

Pattern: ARRAAAARAA… — 4 advances per 5 ticks = 24/30 consumption ratio. Identical to Bresenham but stateless per-tick.

### 2.5 Key Properties

1. **Deterministic:** Given the same tick number and FPS pair, always the same source frame. No accumulated state → no drift, no reset bugs.
2. **Arbitrary FPS ratios:** Works for any rational in/out pair. No special-casing.
3. **Repeat emerges from time mapping:** No "repeat flag" logic needed.
4. **Epoch-resettable:** On segment swap, reset `resample_tick_ = 0`. No need to carefully manage accumulator carryover.

### 2.6 What This Replaces

| Current | Proposed | Status |
|---------|----------|--------|
| `frame_selection_cadence_budget_num_` | `resample_tick_` + `SourceFrameForTick()` | **Replace** |
| `frame_selection_cadence_budget_den_` | `resample_out_num_ × resample_in_den_` (implicit in formula) | **Remove** |
| `frame_selection_cadence_increment_` | `resample_in_num_ × resample_out_den_` (implicit in formula) | **Remove** |
| `frame_selection_cadence_enabled_` | `resample_enabled_` | **Rename** |
| `InitFrameSelectionCadenceForLiveBlock()` | `InitResampleForLiveBlock()` | **Rename + simplify** |
| `RefreshFrameSelectionCadenceFromLiveSource()` | `RefreshResampleFromLiveSource()` | **Rename + simplify** |
| Bresenham accumulator step (lines 1719-1729) | `SourceFrameForTick` comparison (same location) | **Rewrite** |

### 2.7 What Remains Unchanged

- **Output PTS computation** — purely tick-grid-based, unaffected
- **Audio per-tick computation** — rational sample counting, unaffected
- **VideoLookaheadBuffer** — still condvar-driven, still `cadence_active = false`
- **TickProducer ResampleMode** (OFF/DROP/CADENCE) — decoding behavior unchanged
- **TakeDecision enum and cascade** — kRepeat/kContentA decisions still apply
- **Preview/live switching** — seam/take logic unchanged
- **Segment transition override** (line 1745-1748) — still needed, still suppresses repeat on seam tick
- **`last_good_video_frame_`** — still the repeat surface
- **Encoder, muxer, transport** — no change
- **All existing invariants** except cadence accumulator internals

---

## 3. File-by-File Refactor Plan

### 3.1 `PipelineManager.hpp`

**Changes:**
- Remove: `frame_selection_cadence_budget_num_`, `frame_selection_cadence_budget_den_`, `frame_selection_cadence_increment_`
- Add: `resample_enabled_`, `resample_tick_`, `resample_in_num_`, `resample_in_den_`, `resample_out_num_`, `resample_out_den_`
- Add: static `SourceFrameForTick()` declaration
- Rename: method declarations for init/refresh
- Rename: callback type `on_frame_selection_cadence_refresh` → `on_resample_refresh`

### 3.2 `PipelineManager.cpp`

**Tick loop (lines ~1716–1732):**
- Remove: Bresenham accumulator step
- Add: `SourceFrameForTick(resample_tick_, ...)` vs `SourceFrameForTick(resample_tick_ - 1, ...)`
- Increment `resample_tick_++` each tick when enabled
- `should_advance_video` and `is_cadence_repeat` semantics preserved

**Init/refresh functions (lines ~4150, ~4280):**
- Store in/out FPS into new member variables
- Reset `resample_tick_ = 0`
- Remove increment/threshold computation

**Segment swap budget reset (line ~4291, ~4338):**
- Reset `resample_tick_ = 0` (replaces `budget_num_ = 0`)

**Diagnostics (CADENCE_DIAG, lines ~1987-2011):**
- Update log fields to reflect new model (tick, source_frame_index)
- Preserve advance/repeat/bypass counters (still useful)

**Estimated lines changed:** ~80 lines modified, ~20 lines removed, ~30 lines added.

### 3.3 `BlockPlanSessionTypes.hpp`

- `ResampleMode` enum: unchanged (OFF/DROP/CADENCE still meaningful for TickProducer decode paths)

### 3.4 `TickProducer.cpp` / `TickProducer.hpp`

- **No changes.** TickProducer's ResampleMode governs *decoding*, not frame selection. It is unaffected.

### 3.5 `VideoLookaheadBuffer.cpp` / `.hpp`

- **No changes.** FillLoop is already cadence-free. `cadence_active = false` remains.

### 3.6 `OutputClock.hpp` / `.cpp`

- **No changes.** PTS computation is tick-grid-based.

### 3.7 Contract Documents

**Update:** `pkg/air/docs/contracts/frame_selection_cadence.md`
- Rename to `frame_selection_resampling.md` (or keep name, update content)
- INV-CADENCE-POP-001: Unchanged (repeat ticks must not pop)
- INV-CADENCE-POP-002: Unchanged (pops == advances)
- INV-CADENCE-POP-003: Unchanged (consumption ratio ≈ fps ratio)
- INV-CADENCE-POP-004: **Rewrite** — replace accumulator orientation with time-mapping formula
- Add: INV-RESAMPLE-DETERMINISM-001 — `SourceFrameForTick(N)` is a pure function of N and FPS pair

**Update:** `pkg/air/docs/contracts/semantics/TIMING-AUTHORITY-OVERVIEW.md` § B and § E
- Replace Bresenham description with time-mapping description
- Keep OFF/DROP/CADENCE mode selection (TickProducer concern, unchanged)

**Update:** `pkg/air/docs/contracts/INVARIANTS-INDEX.md`
- Add INV-RESAMPLE-DETERMINISM-001

### 3.8 Test Files

**Update:** `pkg/air/tests/contracts/BlockPlan/CadenceSourceSyncContractTests.cpp`
- Verify behavior unchanged (advance/repeat pattern identical)

**Update:** `pkg/air/tests/integration/FrameCadenceIntegrationTests.cpp`
- Verify behavior unchanged

**New:** `pkg/air/tests/contracts/BlockPlan/TimeBasedResamplingContractTests.cpp`
- Unit tests for `SourceFrameForTick()` pure function
- Verify equivalence to Bresenham for all standard FPS pairs
- Edge cases (tick 0, very large tick values, non-standard FPS)

---

## 4. Edge Cases

### 4.1 23.976 → 29.97

`source_frame(N) = floor(N × 4/5)`. Pattern: 4 advances per 5 ticks. 1 repeat per 5 ticks. Classic 3:2 pulldown rhythm. **No special-casing needed.**

### 4.2 29.97 → 29.97

`resample_enabled_ = false` (exact match detected by rational comparison). Every tick pops one frame. **Passthrough, no resampling.**

### 4.3 25 → 29.97

`source_frame(N) = floor(N × 25000 × 1001 / (30000 × 1000))` = `floor(N × 25025 / 30000)`. Approximately 0.834 source frames per tick. Pattern: ~5 advances per 6 ticks with non-uniform repeat placement. **Emerges naturally from the formula.**

### 4.4 29.97 → 23.976 (Downconversion)

`source_frame(N) = floor(N × 5/4)`. Each output tick consumes 1.25 source frames on average. Pattern: 5 advances per 4 ticks → every 4th tick would need to pop 2 frames, or equivalently: 3 single-advance ticks then 1 double-advance tick.

**Risk:** Current infrastructure (TryPopFrame returns one frame) assumes at most 1 pop per tick. For down-conversion, the time-mapping model would need to pop `curr_source - prev_source` frames (possibly > 1) and discard intermediates — similar to DROP mode but non-integer.

**Mitigation:** This case doesn't exist in production today (all output is 29.97). If needed later, add a multi-pop path or delegate to TickProducer's DROP mode for integer sub-cases and a new "DECIMATE" mode for non-integer. **Flag as future work, not blocking.**

### 4.5 Segment Boundaries / Block Transitions

**Segment swap:** `resample_tick_ = 0` on segment change. The new source FPS is read from the new segment's decoder. `SourceFrameForTick(0)` = 0 → first tick is always ADVANCE. No carryover from previous segment's accumulator state.

**Block transition (TAKE):** Post-rotation resets cadence for the new live block via `InitResampleForLiveBlock()` which resets `resample_tick_ = 0`.

**Seam tick override (line 1745):** When `take_segment && is_cadence_repeat && v_src == segment_b_buffer`, suppress repeat and force advance. **Unchanged.** The `is_cadence_repeat` flag is still computed (from `SourceFrameForTick` comparison), and the override still applies.

### 4.6 Primed Frame / `last_good_video_frame_`

- `primed_frame_` is consumed before cadence runs (earlier in the cascade)
- `last_good_video_frame_` is set on every ADVANCE tick; used on REPEAT ticks
- **No change** — the resampling model only affects *which ticks are advance vs repeat*, not what happens on each type.

### 4.7 Audio Authority

Audio is consumed every tick regardless of advance/repeat. Per-tick sample count is purely a function of the output tick grid and accumulated samples. **Completely unaffected** by the cadence→resampling change.

---

## 5. Risks and Invariant Preservation

### 5.1 Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Bresenham and time-mapping produce different patterns | Low | Mathematically equivalent for rational FPS (proven in §2.4). Verify with exhaustive test over 10,000 ticks. |
| 128-bit overflow for extreme tick values | Very Low | `tick × in_num × out_den` with tick < 2^40 (~12 days at 30fps), in_num < 2^17, out_den < 2^17 → fits in 74 bits. Safe in __int128. |
| Segment swap: `resample_tick_ = 0` vs Bresenham `budget = 0` | Low | Both reset to "start fresh." Bresenham: budget=0 → first tick always advances (increment < threshold initially but increment is added first). Time-mapping: source_frame(0)=0, source_frame(-1)=-1 → advance. Same. |
| Down-conversion (out_fps < in_fps) | N/A today | Not supported in production. Documented as future work. |

### 5.2 Invariant Checklist

| Invariant | Impact |
|-----------|--------|
| INV-CADENCE-POP-001 (repeat must not pop) | Preserved — repeat detection changes method but `is_cadence_repeat` flag still gates pop |
| INV-CADENCE-POP-002 (pops == advances) | Preserved — advance count still equals pop count |
| INV-CADENCE-POP-003 (consumption ratio) | Preserved — same ratio emerges from time-mapping |
| INV-CADENCE-POP-004 (accumulator orientation) | **Replaced** by INV-RESAMPLE-DETERMINISM-001 |
| INV-CADENCE-SINGLE-AUTHORITY | Preserved — decision still only in PipelineManager tick loop |
| INV-CADENCE-SOURCE-SYNC-002 | Preserved — init/refresh still reads live source FPS |
| INV-TICK-AUTHORITY-001 | Unaffected — output PTS/duration unchanged |
| INV-FENCE-PTS-DECOUPLE | Unaffected |
| INV-AUDIO-PRIME-* | Unaffected |
| INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 | Unaffected — seam override still applies |

---

## 6. Testing Strategy

### 6.1 Unit Tests (New)

**File:** `pkg/air/tests/contracts/BlockPlan/TimeBasedResamplingContractTests.cpp`

| Test | Validates |
|------|-----------|
| `SourceFrameForTick_23_976_to_29_97` | 4 advances per 5 ticks over 10,000 ticks |
| `SourceFrameForTick_25_to_29_97` | Correct ratio over 10,000 ticks |
| `SourceFrameForTick_29_97_to_29_97` | Identity: source_frame(N) == N |
| `SourceFrameForTick_Tick0_Always_Advance` | source_frame(0) != source_frame(-1) for all FPS pairs |
| `SourceFrameForTick_Monotonic` | source_frame(N) >= source_frame(N-1) for all N |
| `SourceFrameForTick_Equivalence_To_Bresenham` | Run both models in parallel over 100,000 ticks; advance/repeat decisions identical |
| `SourceFrameForTick_NoOverflow_LargeN` | N = 2^36 (~25 hours at 30fps) computes without overflow |
| `SourceFrameForTick_NonStandard_FPS` | e.g. 15/1 → 30000/1001, 50/1 → 30000/1001 |

### 6.2 Contract Tests (Update Existing)

- `CadenceSourceSyncContractTests.cpp` — verify init/refresh with new variable names
- `CadenceSeamAdvanceContractTests.cpp` — verify seam override behavior unchanged

### 6.3 Integration Tests (Update Existing)

- `FrameCadenceIntegrationTests.cpp` — verify end-to-end playback speed unchanged
- Run parity verification (`verify_blockplan_execution.py`) before/after

### 6.4 Runtime Diagnostics

Update `CADENCE_DIAG` (every 300 ticks) to emit:
```
resample_tick=<N> source_frame=<S> prev_source_frame=<S-1>
advance_count=<A> repeat_count=<R> ratio=<A/(A+R)>
```

Preserve advance/repeat/bypass counters for operational observability.

---

## 7. Proposed Contract Text

### INV-RESAMPLE-DETERMINISM-001

**Layer:** CONTRACT
**Owner:** AIR (PipelineManager)
**Enforcement:** Runtime (tick loop)

For any output tick N with source FPS `in_num/in_den` and output FPS `out_num/out_den`:

```
source_frame_index(N) = floor(N × in_num × out_den / (out_num × in_den))
```

This mapping is:
1. **Pure** — depends only on N and the two FPS values; no accumulated state.
2. **Monotonically non-decreasing** — `source_frame_index(N) >= source_frame_index(N-1)`.
3. **Integer-arithmetic only** — 128-bit intermediates, no floating-point.

The advance-vs-repeat decision is:
- **ADVANCE** when `source_frame_index(N) > source_frame_index(N-1)`
- **REPEAT** when `source_frame_index(N) == source_frame_index(N-1)`

This replaces the Bresenham accumulator (INV-CADENCE-POP-004). All other cadence invariants (INV-CADENCE-POP-001 through 003, INV-CADENCE-SINGLE-AUTHORITY) remain in force.

---

## 8. Implementation Order

1. Write and merge the contract (INV-RESAMPLE-DETERMINISM-001)
2. Write `SourceFrameForTick()` as a static pure function
3. Write unit tests proving equivalence to Bresenham
4. Swap PipelineManager tick loop to use time-mapping
5. Update init/refresh functions
6. Update diagnostics
7. Run full integration suite + parity verification
8. Rename contract document and update INVARIANTS-INDEX
