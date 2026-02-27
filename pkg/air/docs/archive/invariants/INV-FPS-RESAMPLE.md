# INV-FPS-RESAMPLE — FPS Resample Authority Contract

**Status:** Active  
**Owner:** FileProducer (output tick grid), TickProducer (block CT grid), OutputClock (session pacing)  
**Enforcement:** Code + regression tests (FR-001–FR-005, MediaTimeContractTests)  
**Related:** INV-AIR-MEDIA-TIME, INV-FPS-MAPPING, PTS-AND-FRAME-RATE-AUDIT.md

---

## Statement

Input media time, output session time, and the resample rule are three separate authorities. Output timing MUST use rational FPS (fps_num, fps_den) and index-based formulas. Rounded intervals and accumulated rounded steps are FORBIDDEN.

---

## Three Authorities

### 1. Input media time (INV-AIR-MEDIA-TIME)

- **Authority:** Decoded PTS (input stream).
- **Use:** Which source frame covers a given time; segment boundaries; block completion.
- **Representation:** Microseconds (PTS) or milliseconds where needed; never derived from `int(1000/fps)` or `round(1e6/fps)` for advancement.

### 2. Output session time (tick grid / block CT grid)

- **Authority:** Rational FPS `(fps_num, fps_den)`.
- **Formulas:**
  - **Output tick time (FileProducer):**  
    `tick_time_us(n) = floor(n * 1_000_000 * fps_den / fps_num)`  
    with integer math; 128-bit intermediate if needed.
  - **Block CT (TickProducer):**  
    `ct_ms(k) = floor(k * 1000 * fps_den / fps_num)`  
    with `frame_index_` k; no `+= frame_duration_ms_`.
  - **OutputClock:** whole + remainder (see MasterClockContract / OutputClock).
- **Use:** When to emit a frame; output PTS; fence and cadence.

### 3. Resample rule

- **Rule:** For each output tick index n, choose the source frame that covers `tick_time_us(n)`. Output PTS for that frame = tick time (grid time), not source PTS.
- **Effect:** Output PTS is always on the output grid; no source PTS leakage (FR-004).

---

## Explicitly Outlawed

The following patterns MUST NOT be used anywhere in the resample/tick/CT path:

| Pattern | Why forbidden |
|--------|----------------|
| **Tick grid from rounded interval and accumulation** | `interval_us = round(1e6 / fps)` then `next_tick_us += interval_us` creates unbounded drift (e.g. 60fps → 16667 µs instead of 16666.666…). |
| **Frame duration from int(1000/fps)** | `frame_duration_ms = int(1000/fps)` truncates (e.g. 60fps → 16 ms). Using it for advancement causes sawtooth and “every-other-frame” behavior at 60fps. |
| **Any accumulated time using rounded ms or µs steps** | `block_ct_ms += frame_duration_ms` or `next_tick_us += interval_us` accumulates error. CT and tick time MUST be computed from index: `ct_ms = CtMs(frame_index_)`, `next_tick_us = TickTimeUs(tick_index_)`. |

---

## Allowed Implementation

- **FileProducer:** Store `target_fps_num_`, `target_fps_den_`, `tick_index_`. Compute `next_output_tick_us_ = TickTimeUs(tick_index_)` with `TickTimeUs(n) = (n * 1'000'000 * fps_den) / fps_num`. Advance by incrementing `tick_index_`, never by adding a rounded interval.
- **TickProducer:** Constructor takes `(fps_num, fps_den)`. Store `fps_num_`, `fps_den_`, `frame_index_`. Compute `block_ct_ms_ = CtMs(frame_index_)` with `CtMs(k) = (k * 1000 * fps_den_) / fps_num_`. On every frame (success, pad, failure): set `block_ct_ms_ = CtMs(frame_index_); frame_index_++`. No `frame_duration_ms_` or `input_frame_duration_ms_` for advancement.
- **PipelineManager:** Construct TickProducer with `ctx_->fps_num`, `ctx_->fps_den`, not `ctx_->fps`.

---

## Test Enforcement

| ID | Purpose |
|----|--------|
| **FR-001** | 60→30 frame skip; output grid and duration |
| **FR-002** | 23.976→30 frame repeat; grid alignment |
| **FR-003** | 59.94→29.97 NTSC; no drift over 3 s |
| **FR-004** | Output PTS always tick-aligned (no source PTS leakage) |
| **FR-005** | 60fps rational grid over 36,000 ticks: strictly increasing, exact floor, error &lt; 1 µs (locks methodology, prevents reintroducing rounded-interval drift) |
| **MediaTimeContractTests** | 23.976 long-form drift, fence hold, etc. (INV-AIR-MEDIA-TIME) |
| **60→60 identity long-run** | (Recommended) Run 60fps content for a long simulated span; assert no periodic pad/underflow from CT drift (validates TickProducer failure/pad path). |

This contract is the rulebook; the tests above are the enforcement. New code MUST NOT reintroduce rounded-interval or int(1000/fps) advancement.

---

## Relationship to INV-FPS-MAPPING

**INV-FPS-MAPPING** defines *which* source frames are selected per output tick (OFF / DROP / CADENCE) using rational comparison only. INV-FPS-RESAMPLE defines *when* those ticks occur (rational grid) and how CT is advanced. Both share the same rational FPS representation; INV-FPS-MAPPING prevents mode misclassification (e.g. 60→30 as OFF) that would break timing and cause audio starvation.
