# PTS and Frame Rate Representation — Audit

**Purpose:** Document how input_pts → output_tick (the "resample bridge") and related timing use double, integer milliseconds, or rational math. **Using `int frame_duration_ms = 1000 / fps` (or equivalent) violates the model and shows first at 60fps.**

---

## Summary: Where the model is violated

| Component | What it uses | Violation? |
|-----------|--------------|------------|
| **TickProducer** (constructor) | `frame_duration_ms_ = static_cast<int64_t>(1000.0 / fps)` | **YES** — truncation to int ms. At 60fps → 16 ms (true 16.666…). |
| **TickProducer** (segment open) | `input_frame_duration_ms_ = static_cast<int64_t>(std::round(1000.0 / input_fps_))` | **YES** — rounded int ms. |
| **TickProducer** (CT advance) | PTS-anchored: `block_ct_ms_ = ct_before + input_frame_duration_ms_` (one-step, not accumulated) | Anchor is correct; the **increment** is still int ms. Failure paths use `block_ct_ms_ += input_frame_duration_ms_` (accumulated int ms). |
| **FileProducer** (resample) | `output_tick_interval_us_ = round(1000000.0 / config_.target_fps)` then `next_output_tick_us_ += output_tick_interval_us_` | **YES** — output grid is rounded int µs, not rational. At 60fps: 16667 µs/tick (true 16666.666…); cumulative error. |
| **OutputClock** | `fps_num_`, `fps_den_`; `DeadlineOffsetNs()` = rational (whole + remainder); `frame_duration_90k_` = round(90000*fps_den/fps_num) | **No** — pacing is rational; 90k is rounded but exact for standard rates. |
| **PipelineManager** (fence, seam) | `ceil(delta_ms * fps_num / (fps_den * 1000))` with integer math | **No** — rational. |
| **PadProducer** | `(sr * fps_den + fps_num - 1) / fps_num` for samples per frame | **No** — rational. |

---

## 1. TickProducer (BlockPlan path)

**File:** `pkg/air/src/blockplan/TickProducer.cpp`

- **Constructor (lines 21–26):** Takes `double fps`.
  - `frame_duration_ms_ = static_cast<int64_t>(1000.0 / fps)` → **truncation**. 60fps → 16 ms.
  - `input_frame_duration_ms_ = static_cast<int64_t>(1000.0 / fps)` (same).
- **AssignBlock / OpenDecoder (lines 183–186):** When segment opens, `input_frame_duration_ms_ = static_cast<int64_t>(std::round(1000.0 / input_fps_))` → **rounded int ms** (e.g. 60fps → 17 ms).
- **frames_per_block_ (lines 46–48):** Uses `ceil(duration_ms * output_fps_ / 1000.0)` → correct (no int frame_duration division).
- **TryGetFrame success path (254–255, 506–507):** CT is PTS-anchored: `block_ct_ms_ = ct_before + input_frame_duration_ms_`, `next_frame_offset_ms_ = decoded_pts_ms + input_frame_duration_ms_`. So position is reset from decoded PTS each time; the **one-step** add is still int ms.
- **TryGetFrame failure / pad paths (466, 482, 603):** `block_ct_ms_ += input_frame_duration_ms_` or `+= frame_duration_ms_` → **accumulated integer ms** → drift.

**Created with:** `ctx_->fps` (double) in PipelineManager — not `ctx_->fps_num` / `ctx_->fps_den`.

---

## 2. FileProducer (resample bridge: input_pts → output_tick)

**File:** `pkg/air/src/producers/file/FileProducer.cpp`

- **Output tick grid:**
  - Stub (584–585): `output_tick_interval_us_ = static_cast<int64_t>(std::round(1000000.0 / config_.target_fps))`.
  - Real decoder (838–839): same.
  - Advance (3466, 3517): `next_output_tick_us_ += output_tick_interval_us_`.
- So the **output tick timeline** is N × (rounded int µs). At 60fps: interval = 16667 µs; true period = 16666.666… µs. Error ≈ 0.333 µs per tick → cumulative drift.
- **Input** side uses decoder PTS (µs) and comparisons to `next_output_tick_us_`; no int-ms frame duration in the gate itself, but the **grid** is wrong.

---

## 3. OutputClock (session output pacing)

**File:** `pkg/air/src/blockplan/OutputClock.cpp`

- Constructor takes **rational** `fps_num`, `fps_den`.
- **DeadlineOffsetNs:** `N * ns_per_frame_whole_ + (N * ns_per_frame_rem_) / fps_num_` → integer rational, no float. Correct.
- **frame_duration_ms_** and **frame_duration_90k_:** `round(1000.0 * fps_den / fps_num)` and `round(90000.0 * fps_den / fps_num)`. For 60/1 and 30000/1001 these are exact; for arbitrary rationals they are rounded once (not accumulated). So pacing is rational; stored durations are for reporting / PTS and are exact for standard rates.

---

## 4. Why 60fps shows first

- **Integer ms:** `1000 / 60` in C++ integer division = 16. So any `int frame_duration_ms = 1000 / fps` gives 16 ms at 60fps. True period 16.666… ms. Per frame you are 0.666 ms short; per second 40 ms.
- **Truncated double:** `static_cast<int64_t>(1000.0 / 60.0)` = 16. Same effect.
- **Rounded µs:** `round(1000000/60)` = 16667. Grid advances 16667 µs per tick; true 16666.666… So +0.333 µs per tick; over long runs the output grid drifts from the rational timeline.

---

## 5. Recommended direction (no code changes in this file)

- **TickProducer:** Take `fps_num`, `fps_den` (rational) and stop storing a single `frame_duration_ms_` / `input_frame_duration_ms_` for advancement. Use PTS for position (already done on success path); for look-ahead and failure paths use rational step or at least `(1000 * fps_den + fps_num - 1) / fps_num` (or equivalent) so 60fps is exact.
- **FileProducer:** Drive the output grid from rational target FPS: e.g. tick N at `N * 1_000_000 * fps_den / fps_num` µs (integer math), or maintain `fps_num`/`fps_den` and compute each `next_output_tick_us_` from a frame index. Do not use `next_output_tick_us_ += output_tick_interval_us_` with a rounded int.
- **PipelineManager:** Pass `ctx_->fps_num`, `ctx_->fps_den` into TickProducer (and any similar consumers) instead of `ctx_->fps`.

---

## References

- INV-AIR-MEDIA-TIME: PTS-anchored CT, no cumulative drift.
- INV-BLOCK-WALLCLOCK-FENCE-001: fence from rational `fps_num`/`fps_den`.
- FpsResampleTests (FR-001–FR-004): 60→30, 23.976→30, 59.94→29.97, output PTS tick-aligned.
