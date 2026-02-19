# Edge-case audit: 1–2 frame PAD segments

Code+line citations only. Verdict: **PASS** for “1–2 frame PAD is safe”.

---

## 1) PAD segments in `segment_seam_frames_` / seam schedule

- **Seam schedule source:** `segment_seam_frames_` is filled from `live_boundaries_` (one entry per segment). Each boundary has `end_ct_ms`; the corresponding seam frame is `block_activation_frame_ + (ct_ms * fps_num + denom - 1) / denom`.

```2776:2790:pkg/air/src/blockplan/PipelineManager.cpp
void PipelineManager::ComputeSegmentSeamFrames() {
  segment_seam_frames_.clear();
  current_segment_index_ = 0;
  const int64_t fps_num = ctx_->fps_num;
  const int64_t fps_den = ctx_->fps_den;
  int64_t denom = fps_den * 1000;
  for (const auto& boundary : live_boundaries_) {
    int64_t ct_ms = boundary.end_ct_ms;
    int64_t seam = (ct_ms > 0)
        ? block_activation_frame_ + (ct_ms * fps_num + denom - 1) / denom
        : block_activation_frame_;
    segment_seam_frames_.push_back(seam);
  }
  UpdateNextSeamFrame();
}
```

- **Representation:** PAD segments are not special in the vector. Every segment (CONTENT or PAD) has one boundary in `live_boundaries_` and thus one entry in `segment_seam_frames_`. `segment_seam_frames_[i]` = session frame at which segment `i` ends (seam into segment `i+1`). Segment type is from `live_parent_block_.segments[i].segment_type` (e.g. `SegmentType::kPad`).

```269:269:pkg/air/include/retrovue/blockplan/PipelineManager.hpp
  std::vector<int64_t> segment_seam_frames_;  // One per segment boundary
```

```2936:2937:pkg/air/src/blockplan/PipelineManager.cpp
  const SegmentType seg_type = live_parent_block_.segments[to_seg].segment_type;
  const bool is_pad = (seg_type == SegmentType::kPad);
```

- **Next seam frame:** `next_seam_frame_` for the current segment is taken from `segment_seam_frames_[current_segment_index_]` (frame at which current segment ends).

```2796:2802:pkg/air/src/blockplan/PipelineManager.cpp
void PipelineManager::UpdateNextSeamFrame() {
  int64_t next_seg = INT64_MAX;
  // Current segment's end is the next segment seam — UNLESS it's the last segment.
  if (current_segment_index_ + 1 <
      static_cast<int32_t>(segment_seam_frames_.size())) {
    next_seg = segment_seam_frames_[current_segment_index_];
  }
```

---

## 2) When PAD is the incoming segment

### 2a) Gate returns eligible immediately (no depth dependency)

- **State for PAD:** For `to_seg` with `SegmentType::kPad`, `GetIncomingSegmentState` always returns a state: either from `pad_b_*` depths or a synthetic state with `incoming_audio_ms = 0`, `incoming_video_frames = 1` (“PadProducer on demand; infinite”). It does not return `std::nullopt` for PAD.

```3010:3024:pkg/air/src/blockplan/PipelineManager.cpp
  // PAD: report state from persistent pad_b_* when present; else synthetic (always eligible).
  if (is_pad) {
    IncomingState s;
    s.is_pad = true;
    s.segment_type = SegmentType::kPad;
    if (pad_b_video_buffer_ && pad_b_audio_buffer_) {
      s.incoming_audio_ms = pad_b_audio_buffer_->DepthMs();
      s.incoming_video_frames = pad_b_video_buffer_->DepthFrames();
    } else {
      s.incoming_audio_ms = 0;
      s.incoming_video_frames = 1;  // PadProducer on demand; infinite
    }
    return s;
  }
```

- **Eligibility:** For PAD, `IsIncomingSegmentEligibleForSwap` returns `true` unconditionally; no depth check.

```3029:3039:pkg/air/src/blockplan/PipelineManager.cpp
bool PipelineManager::IsIncomingSegmentEligibleForSwap(const IncomingState& incoming) const {
  if (incoming.is_pad) {
    // PAD: minimal prebuffer. PadProducer is session-lifetime, loopable (same
    // frame/silence every tick), no buffered content; sustains continuous output.
    return true;
  }
  // CONTENT: require minimum audio depth and video frames to avoid underflow.
  return incoming.incoming_audio_ms >= kMinSegmentSwapAudioMs &&
         incoming.incoming_video_frames >= kMinSegmentSwapVideoFrames;
}
```

So when the incoming segment is PAD, the gate always has an incoming state and marks it eligible; no depth dependency.

### 2b) PerformSegmentSwap uses persistent `pad_b_*` without allocating A

- **PAD branch:** When `incoming_is_pad` and both `pad_b_video_buffer_` and `pad_b_audio_buffer_` exist, the swap only moves `pad_b_*` into the live A slots. No allocation of A; no use of `segment_b_*` for PAD.

```3085:3094:pkg/air/src/blockplan/PipelineManager.cpp
  if (incoming_is_pad && pad_b_video_buffer_ && pad_b_audio_buffer_) {
    // PAD seam: swap A with persistent pad B only. No A allocation.
    video_buffer_ = std::move(pad_b_video_buffer_);
    audio_buffer_ = std::move(pad_b_audio_buffer_);
    live_ = std::move(pad_b_producer_);
    video_buffer_->SetBufferLabel("LIVE_AUDIO_BUFFER");
    prep_mode = "INSTANT";
    swap_branch = "PAD_SWAP";
    pad_swap_used_pad_b = true;
```

- **A is only moved out then replaced:** Step 2 moves existing A out into `outgoing_*` for reaping; A slots are then filled only by move from `pad_b_*` or `segment_b_*` or (MISS) from newly created `segment_b_*`. No allocation of A anywhere in the function.

```3075:3099:pkg/air/src/blockplan/PipelineManager.cpp
  // Step 2: Move outgoing A out FIRST so we can stop fill and hand off.
  // ReapJob holds owners until join. No allocation of A in this function.
  auto outgoing_video_buffer = std::move(video_buffer_);
  ...
  if (incoming_is_pad && pad_b_video_buffer_ && pad_b_audio_buffer_) {
    // PAD seam: swap A with persistent pad B only. No A allocation.
    video_buffer_ = std::move(pad_b_video_buffer_);
```

- **Header comment:** Documents that at PAD seam we swap A with `pad_b_*` only (no A allocation).

```310:311:pkg/air/include/retrovue/blockplan/PipelineManager.hpp
  // At PAD seam we swap A with pad_b_* only (no A allocation). After handoff we
  // recreate pad_b_* so the chain is ready for the next PAD.
```

---

## 3) Consecutive PAD seams (e.g. PAD→CONTENT with 1–2 frames of PAD)

### 3a) Next CONTENT seam cannot be “missed” (arming)

- **Skip-PAD prep:** `ArmSegmentPrep` scans forward from `next_seg` to the first non-PAD segment (`target_seg`) and arms prep for that segment. So CONTENT-after-PAD is armed even when the immediate next segment is PAD.

```2822:2835:pkg/air/src/blockplan/PipelineManager.cpp
  // FIX (skip-PAD prep): PAD segments are handled inline in PerformSegmentSwap --
  // they need no decoder, no file I/O, and no async worker involvement.
  // Scan forward from next_seg to find the first non-PAD segment to prep.
  // This gives the worker the full duration of the current content segment as
  // lead time, instead of racing a 1-frame PAD window (which always loses).
  int32_t target_seg = next_seg;
  while (target_seg < static_cast<int32_t>(live_parent_block_.segments.size()) &&
         live_parent_block_.segments[target_seg].segment_type == SegmentType::kPad) {
    target_seg++;
  }
  // If all remaining segments are PAD (or block ends here), nothing to prep.
  if (target_seg >= static_cast<int32_t>(live_parent_block_.segments.size())) {
    return;
  }
```

- **Seam frame for CONTENT-after-PAD:** For CONTENT at index `target_seg`, the seam used for headroom is `segment_seam_frames_[target_seg - 1]` (end of the segment just before CONTENT, i.e. end of the last PAD). So headroom = time from “now” until that seam. When current segment is the first CONTENT (index 0), “now” is at block activation; headroom = duration(segment 0) + duration(segment 1) + … up to and including the PAD segment(s). So with CONTENT→PAD(1–2 frames)→CONTENT, headroom for the CONTENT-after-PAD prep = full CONTENT segment + 1–2 frames, which is large. Arming is done at block activation and again after each segment swap (including after the PAD swap).

```2864:2870:pkg/air/src/blockplan/PipelineManager.cpp
  int32_t seam_boundary_idx = target_seg - 1;
  int64_t seam_frame_val =
      (seam_boundary_idx < static_cast<int32_t>(segment_seam_frames_.size()))
      ? segment_seam_frames_[seam_boundary_idx]
      : INT64_MAX;
```

```915:915:pkg/air/src/blockplan/PipelineManager.cpp
    ArmSegmentPrep(session_frame_index);
```

```3176:3177:pkg/air/src/blockplan/PipelineManager.cpp
  // Step 5: Arm next segment prep.
  ArmSegmentPrep(session_frame_index);
```

So the next CONTENT seam is never “unarmed”: we either arm at block start (with headroom = current segment + all PADs until that CONTENT) or re-arm after the PAD swap.

### 3b) EnsureIncomingBReadyForSeam is not starved of headroom

- **PAD does not consume headroom in EnsureIncomingBReadyForSeam:** For PAD, `EnsureIncomingBReadyForSeam` returns immediately without creating or consuming `segment_b_*`. B for PAD is the persistent `pad_b_*`, which is not created here.

```2943:2947:pkg/air/src/blockplan/PipelineManager.cpp
  // PAD: use persistent pad_b_* (created at session init). No segment_b_* for PAD.
  if (is_pad) {
    return;
  }
```

- **CONTENT B and headroom:** Headroom is used in `ArmSegmentPrep` (when to submit the prep request), not in `EnsureIncomingBReadyForSeam`. Low headroom only causes a log and a possibly late worker result; at the seam we then defer until B is ready. `EnsureIncomingBReadyForSeam` only consumes an existing worker result to build `segment_b_*`; it does not depend on a “headroom budget” inside this function. So “starving EnsureIncomingBReadyForSeam of headroom” does not occur: headroom affects whether the worker finishes in time; if it doesn’t, we defer (see below). The only marginal case is a block that starts with PAD (seg0 = PAD, seg1 = CONTENT): we still arm with headroom = PAD duration (1–2 frames), log SEAM_PREP_HEADROOM_LOW, and may defer at the seam until B is ready.

```2871:2894:pkg/air/src/blockplan/PipelineManager.cpp
  int64_t headroom_frames = (seam_frame_val != INT64_MAX && seam_frame_val > session_frame_index)
      ? (seam_frame_val - session_frame_index)
      : 0;
  ...
  if (headroom_frames < required_headroom_frames) {
    std::ostringstream oss;
    oss << "[PipelineManager] SEAM_PREP_HEADROOM_LOW"
```

---

## 4) Minimum headroom for CONTENT B to reach 500 ms, and when headroom is smaller

### 4a) Constants

- **Swap gate (CONTENT B depth):** 500 ms audio and ≥1 video frame required for CONTENT swap.

```69:72:pkg/air/src/blockplan/PipelineManager.cpp
static constexpr int kMinAudioPrimeMs = 500;
// Segment swap gate: minimum incoming buffer depth before swapping (avoids async fill race).
static constexpr int kMinSegmentSwapAudioMs = 500;
static constexpr int kMinSegmentSwapVideoFrames = 1;
```

- **Arming headroom (required lead time):** `required_headroom_frames = max(kMinSegmentPrepHeadroomFrames, frames equivalent of kMinSegmentPrepHeadroomMs)` with `kMinSegmentPrepHeadroomMs = 250`, `kMinSegmentPrepHeadroomFrames = 8`. So at 30 fps: 250 ms → 8 frames (rounded up); required = max(8, 8) = **8 frames** (~267 ms at 30 fps).

```74:76:pkg/air/src/blockplan/PipelineManager.cpp
// B-chain fill: minimum lead time (frames/ms) so segment prep reaches target depth before seam.
static constexpr int kMinSegmentPrepHeadroomMs = 250;
static constexpr int kMinSegmentPrepHeadroomFrames = 8;
```

```2877:2881:pkg/air/src/blockplan/PipelineManager.cpp
  int64_t required_frames_from_ms = (kMinSegmentPrepHeadroomMs * ctx_->fps_num + 1000 * ctx_->fps_den - 1)
      / (1000 * ctx_->fps_den);
  int64_t required_headroom_frames = std::max(
      static_cast<int64_t>(kMinSegmentPrepHeadroomFrames),
      required_frames_from_ms);
```

- **Exact minimum headroom for CONTENT B to reach 500 ms:** The gate requires 500 ms. The design uses **at least 8 frames (or 250 ms in frames, whichever is larger)** as the nominal required headroom for arming. For the worker to actually reach 500 ms audio, real-world headroom must be enough for decode + prime; the code does not compute that dynamically—it arms with available headroom and defers at the seam if B is not ready.

### 4b) When headroom is smaller than required

- **Arming:** We still submit the prep request; we only log `SEAM_PREP_HEADROOM_LOW`. No skip of arming.

```2883:2894:pkg/air/src/blockplan/PipelineManager.cpp
  if (headroom_frames < required_headroom_frames) {
    std::ostringstream oss;
    oss << "[PipelineManager] SEAM_PREP_HEADROOM_LOW"
        << " headroom_frames=" << headroom_frames
        ...
    Logger::Warn(oss.str());
  }
  SeamRequest req;
  ...
  seam_preparer_->Submit(std::move(req));
```

- **Deferral at seam:** If at the seam tick there is no incoming B (CONTENT with no `segment_b_*`), `GetIncomingSegmentState` returns `std::nullopt`; we do not call `PerformSegmentSwap` and log `SEGMENT_SWAP_DEFERRED reason=no_incoming`. `take_segment` is true for every tick with `session_frame_index >= next_seam_frame_`, so we keep calling `EnsureIncomingBReadyForSeam` and the gate on subsequent ticks until B is ready, then we swap.

```1956:1982:pkg/air/src/blockplan/PipelineManager.cpp
      if (!incoming) {
        // No incoming source (no segment B, no worker result).
        if (last_logged_defer_seam_frame_ != next_seam_frame_) {
          ...
            oss << "[PipelineManager] SEGMENT_SWAP_DEFERRED"
                << " reason=no_incoming"
          ...
        }
        // Keep current live; do not call PerformSegmentSwap.
      } else if (!IsIncomingSegmentEligibleForSwap(*incoming)) {
        ...
            oss << "[PipelineManager] SEGMENT_SWAP_DEFERRED"
                << " reason=not_ready"
        ...
        // Keep current live; do not call PerformSegmentSwap.
```

```1278:1280:pkg/air/src/blockplan/PipelineManager.cpp
    const bool take = (session_frame_index >= next_seam_frame_);
    const bool take_b = take && (next_seam_type_ == SeamType::kBlock);
    const bool take_segment = take && (next_seam_type_ == SeamType::kSegment);
```

- **Fallback (PAD seam):** If the incoming segment is PAD but `pad_b_*` are missing, we take the MISS branch: create `segment_b_*` (TickProducer + buffers), move them into A slots, and log `SEGMENT_SEAM_PAD_FALLBACK`. So we never leave live empty; we fall back to a synthetic B.

```3102:3134:pkg/air/src/blockplan/PipelineManager.cpp
  } else if (segment_b_video_buffer_ && segment_b_audio_buffer_) {
    ...
  } else {
    // INV-SEAM-SEG-007: MISS — create B (only), then move B into A slots.
    segment_b_producer_ = std::make_unique<TickProducer>(...);
    ...
    { std::ostringstream oss;
      oss << "[PipelineManager] SEGMENT_SEAM_PAD_FALLBACK"
```

---

## Conclusion

- **1)** PAD segments are represented in the seam schedule like any other: one entry in `segment_seam_frames_` per segment boundary from `live_boundaries_`; type comes from `live_parent_block_.segments[i].segment_type`.
- **2)** When PAD is incoming: the gate always returns eligible (PAD state always returned, `IsIncomingSegmentEligibleForSwap` returns `true` for PAD); `PerformSegmentSwap` uses only persistent `pad_b_*` and does not allocate A.
- **3)** Consecutive PAD seams: skip-PAD prep arms the first non-PAD segment (CONTENT) with headroom to the end of the last PAD; CONTENT-after-PAD is armed at block start and after the PAD swap. `EnsureIncomingBReadyForSeam` for PAD is a no-op and is not “starved” of headroom.
- **4)** Minimum headroom for arming is **max(8 frames, 250 ms in frames)**; for CONTENT B to reach 500 ms the swap gate requires 500 ms depth. When headroom is smaller we still arm, log SEAM_PREP_HEADROOM_LOW, and at the seam either defer (SEGMENT_SWAP_DEFERRED) until B is ready or, at a PAD seam without `pad_b_*`, use the MISS/SEGMENT_SEAM_PAD_FALLBACK path.

**PASS** — 1–2 frame PAD is safe: PAD is always eligible, uses only `pad_b_*` with no A allocation, CONTENT-after-PAD is armed with sufficient lead time (skip-PAD), and low headroom leads to deferral or PAD fallback, not to missed arming or starvation of the B-ready logic.
