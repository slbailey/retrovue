# Segment prep headroom — scheduling and lead time

## 1) Where SeamPreparer segment requests are scheduled relative to next_seam_frame_

**Scheduling code**

- **ArmSegmentPrep** submits the segment prep request: `pkg/air/src/blockplan/PipelineManager.cpp` **2804–2884**.
- **req.seam_frame** is set at **2853–2861**:  
  `seam_frame_val = segment_seam_frames_[seam_boundary_idx]` (session frame when the target segment activates).
- **Submit** is at **2867**: `seam_preparer_->Submit(std::move(req));`.
- **Call sites** (when we call ArmSegmentPrep, and thus what “now” is):

| Call site | File:line | When | session_frame_index | Lead time (frames) |
|-----------|-----------|------|---------------------|--------------------|
| Block activation (JIP/cold start) | PipelineManager.cpp **878** | Right after ComputeSegmentSeamFrames() on first block | block_activation_frame_ | seam_frame_val - block_activation_frame_ = **duration of segment 0** (frames) |
| Block activation (after fence swap) | PipelineManager.cpp **1771** | After rotating B→A at block fence | session_frame_index = fence tick | Same: **duration of segment 0** of new block |
| Block activation (fallback sync) | PipelineManager.cpp **2498** | After sync load of next block at fence | session_frame_index | Same: **duration of segment 0** |
| After segment swap (PAD inline) | PipelineManager.cpp **3029** | Right after PAD inline swap, before return | session_frame_index = seam tick | **Duration of segment we just entered** (e.g. segment 1 duration for next seam = segment 2) |
| After segment swap (normal) | PipelineManager.cpp **3164** | After PerformSegmentSwap, Advance segment, UpdateNextSeamFrame | session_frame_index = seam tick | **Duration of segment we just entered** |

So **lead time in frames** = `seam_frame_val - session_frame_index` at the tick when we call ArmSegmentPrep. That equals the **duration of the current segment** (the one we’re playing until the seam): at block start it’s segment 0’s length; after a segment swap it’s the new current segment’s length.

**Relevant code**

- **2850–2861**: `seam_frame_val` = segment boundary frame for target segment.
- **2871–2876**: SEGMENT_PREP_ARMED log has `tick=` (session_frame_index) and `seam_frame=`, so headroom can be computed as `seam_frame - tick`.
- **SeamPreparer::Submit** (SeamPreparer.cpp **45–56**): request is inserted in queue by `seam_frame` ascending; worker processes in that order. The request does **not** carry “current tick”; lead time is implicit (time from submit to seam = caller’s responsibility).

---

## 2) Required lead time to reach target buffer depth

**Target (example):** 250 ms audio, 8 frames video before next_seam_frame_.

- **Frames equivalent for 250 ms:**  
  `required_frames = ceil(250 * fps_num / (1000 * fps_den))`  
  e.g. 30 fps → 7.5 → 8 frames; 24 fps → 6 frames.
- **Video:** 8 frames.
- So we need **at least** `max(8, ceil(250 * fps_num / (1000 * fps_den)))` frames of lead time so that the worker can finish PrimeFirstTick (and any B-chain fill) before the seam.

So we should:

- Compute **required_headroom_frames** from target depth (e.g. 250 ms and 8 frames) and fps.
- Ensure segment prep is **scheduled** (ArmSegmentPrep called) when `(seam_frame_val - session_frame_index) >= required_headroom_frames`.
- If we call ArmSegmentPrep only at block start and after each segment swap, then current lead time = **current segment duration**. So we ensure that either:
  - that duration is always ≥ required_headroom_frames, or
  - we arm earlier (e.g. when next_seam_frame_ is first known and headroom is sufficient, or by arming more than one segment ahead).

---

## 3) Is lead time currently too small?

- **Current behavior:** We arm at the **earliest** moment we know the seam: block activation and right after the previous segment swap. So lead time = **full current segment duration**.
- **Short segments:** If the current segment is shorter than required headroom (e.g. &lt; 8 frames or &lt; 250 ms worth of frames), we never have enough lead time with the current “arm once per segment” strategy.
- **Proposal:**
  1. **Define minimum headroom** and log/warn when below (see patch below).
  2. **Option A – Arm when headroom is sufficient:** In the tick loop, when `next_seam_frame_ != INT64_MAX` and we have not yet armed for the next segment and `(next_seam_frame_ - session_frame_index) >= required_headroom_frames`, call ArmSegmentPrep. That doesn’t increase headroom; it only defers the arm until “just enough” headroom remains (and fails when segment is shorter than required).
  3. **Option B – Arm earlier by arming two segments ahead:** At block activation, in addition to arming for the first content segment (target_seg), also arm for the *next* content segment (target_seg+1, etc.) so that the second segment’s lead time = segment_0 + segment_1 duration. That gives more headroom for segment 2. (Requires SeamPreparer to accept multiple segment requests and process by seam_frame order, which it already does.)
  4. **Recommended:** (1) Add required headroom constants and compute headroom at arm time; (2) log headroom_frames and headroom_ms in SEGMENT_PREP_ARMED; (3) if headroom &lt; required, log SEAM_PREP_HEADROOM_LOW and still submit; (4) optionally, only call ArmSegmentPrep when headroom >= required (and call from tick loop until armed) so we never submit with insufficient headroom—then short segments would get no prep and would hit MISS/defer.

---

## 4) Concrete patch: headroom computation and logging

**Constants (PipelineManager.cpp, near 71):**

```cpp
// Minimum lead time for segment prep so B-chain can reach target depth before seam.
static constexpr int kMinSegmentPrepHeadroomMs = 250;
static constexpr int kMinSegmentPrepHeadroomFrames = 8;
```

**In ArmSegmentPrep (after seam_frame_val is set, before Submit):**

- Compute `headroom_frames = seam_frame_val - session_frame_index` (clamp to 0 if negative).
- Compute headroom_ms: `headroom_ms = (headroom_frames * 1000 * ctx_->fps_den) / ctx_->fps_num` (integer).
- Compute required_frames from ms: `required_frames_from_ms = (kMinSegmentPrepHeadroomMs * ctx_->fps_num + 1000 * ctx_->fps_den - 1) / (1000 * ctx_->fps_den)`.
- Required: `required_headroom_frames = std::max(kMinSegmentPrepHeadroomFrames, required_frames_from_ms)`.
- In SEGMENT_PREP_ARMED log add: `headroom_frames=... headroom_ms=... required_frames=...`.
- If `headroom_frames < required_headroom_frames`: log once `[PipelineManager] SEAM_PREP_HEADROOM_LOW ... headroom_frames=... required_frames=...`.

**Where to request earlier (if we want to enforce minimum headroom):**

- **Option 1:** In the tick loop (e.g. where we already have `next_seam_frame_` and session_frame_index), each tick: if we have not yet armed for the next segment and `(next_seam_frame_ - session_frame_index) >= required_headroom_frames`, call ArmSegmentPrep(session_frame_index). That “requests” prep at the first tick when there is enough lead time. We’d need a guard so we only arm once per “next segment” (e.g. track last_armed_for_seam_frame_ or similar).
- **Option 2:** Keep current call sites; only add headroom computation, logging, and SEAM_PREP_HEADROOM_LOW when below threshold. No change to when we request.

---

## 5) Code reference and patch location list

| Change | File | Line (anchor) |
|--------|------|----------------|
| Add kMinSegmentPrepHeadroomMs, kMinSegmentPrepHeadroomFrames | PipelineManager.cpp | ~71 (after kMinSegmentSwapVideoFrames) |
| Compute headroom_frames, headroom_ms, required_headroom_frames in ArmSegmentPrep | PipelineManager.cpp | After 2856, before 2859 (before building req) |
| Add headroom_frames, headroom_ms, required_frames to SEGMENT_PREP_ARMED log | PipelineManager.cpp | 2869–2878 |
| If headroom_frames < required_headroom_frames, log SEAM_PREP_HEADROOM_LOW | PipelineManager.cpp | After headroom computation, before Submit |
| (Optional) Tick-loop arm when headroom sufficient: ensure ArmSegmentPrep called when (next_seam_frame_ - session_frame_index) >= required | PipelineManager.cpp | Tick loop where next_seam_frame_ is used; requires “armed for this seam” guard to avoid double-submit |

Frame duration for headroom_ms: use `(headroom_frames * 1000 * ctx_->fps_den) / ctx_->fps_num` so that headroom_ms is consistent with session frame timing.
