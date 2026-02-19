# Segment seam A/B chain analysis — code-only

## 1. Are `audio_buffer_` and `video_buffer_` recreated at every PREROLLED seam?

**No.** At a **PREROLLED** segment seam they are **not** recreated; they are replaced by **moving** the segment preview buffers into live.

**PREROLLED path (no new allocation):**

- `pkg/air/src/blockplan/PipelineManager.cpp` **2968–2971**  
  When `segment_preview_video_buffer_` is non-null, live buffers are replaced by move:
  - `video_buffer_ = std::move(segment_preview_video_buffer_);`
  - `audio_buffer_ = std::move(segment_preview_audio_buffer_);`
  - `live_ = std::move(segment_preview_);`
- Prep mode is set to `"PREROLLED"` at **2977** (content) or **3004** (incoming_is_pad branch).

**Paths where `audio_buffer_` / `video_buffer_` are recreated (new allocation) at segment seam:**

- **PAD inline** (incoming segment is PAD): **2903–2919** — `std::make_unique<VideoLookaheadBuffer>`, `std::make_unique<AudioLookaheadBuffer>`, then `StartFilling`.
- **HasSegmentResult (no segment preview)** (fallback when `!segment_preview_video_buffer_` but worker has result): **2985–3004** — new `VideoLookaheadBuffer` and `AudioLookaheadBuffer`, then `StartFilling`.
- **MISS** (no preview, no usable result): **3019–3034** — new buffers and `StartFilling`, `prep_mode = "MISS"`.

**Summary:** At a PREROLLED seam, live buffers are **not** recreated; they are the former segment-preview buffers. Recreation happens only on PAD-inline, HasSegmentResult (no preview), or MISS.

---

## 2. All code paths that destroy or recreate `audio_buffer_` during segment seam

All of the following are inside `PerformSegmentSwap` (`PipelineManager.cpp` **2855–3064**).

**Unconditional (every segment seam):**

- **2889–2890**  
  Outgoing live buffers are moved out (live references destroyed for the current chain):  
  `auto outgoing_audio_buffer = std::move(audio_buffer_);`  
  (and same for `video_buffer_`).  
  Then **2890** `outgoing_video_buffer->StopFillingAsync(/*flush=*/true)`.

**Then exactly one of:**

| Path              | Lines    | Effect on `audio_buffer_` |
|-------------------|----------|---------------------------|
| PREROLLED         | 2968–2971| `audio_buffer_ = std::move(segment_preview_audio_buffer_);` — no new allocation. |
| PAD inline        | 2913     | `audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(...);` — recreated. |
| HasSegmentResult  | 2996     | `audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(...);` — recreated. |
| MISS              | 3030     | `audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(...);` — recreated. |

**No other code in this file** destroys or recreates `audio_buffer_` specifically at segment seam; block-seam and other paths (e.g. **1607–1608**, **1693–1706**, **1716–1724**, **1826–1827**) are separate.

---

## 3. Seam eligibility check requiring `audio_buffer_->DepthMs() >= threshold` before switching live producer?

**No.** There is **no** seam-eligibility check that requires `audio_buffer_->DepthMs() >= threshold` (or any audio depth on the **incoming** buffer) before switching the live producer at a **segment** seam.

**Evidence:**

- **Take decision:** **1283–1285**  
  `take = (session_frame_index >= next_seam_frame_);`  
  `take_segment = take && (next_seam_type_ == SeamType::kSegment);`  
  No use of `audio_buffer_` or `DepthMs()` here.
- **Source selection for segment:** **1304–1306**  
  If `take_segment && segment_preview_video_buffer_`, then `v_src`/`a_src` are set to segment preview buffers. There is no check that `segment_preview_audio_buffer_->DepthMs() >= X` or that segment preview is primed.
- **Segment take commit:** **1956–1970**  
  When `take_segment` we log `seg_preview_ready=(segment_preview_video_buffer_ != nullptr)` and then **1970** `PerformSegmentSwap(session_frame_index)` is called unconditionally. No depth gate.
- **Block seam only:** For **block** seams, `kMinAudioPrimeMs` (500 ms) and `preview_audio_prime_depth_ms_` are used for **logging** (e.g. **1287–1296**, **1182–1191**) and for bootstrap at session start (**966**, **962**). There is no **segment**-seam check that blocks the swap until the incoming (segment preview) buffer has `DepthMs() >=` some threshold.

**DepthMs in fill logic (not seam gating):**

- **VideoLookaheadBuffer.cpp** **348**, **360**  
  `audio_buffer->DepthMs()` is used inside the **fill loop** (bootstrap and steady phase) to decide when the **fill thread** may continue decoding (`bootstrap_min_audio_ms_`, `audio_burst_threshold_ms_`). This gates fill behavior, not “may we switch live producer at seam?”

---

## 4. Conclusion: A/B chain with seam gating vs single-chain with async fill race

**Conclusion: B) Single-chain with async fill race.**

**Supporting citations:**

1. **A/B buffers exist:** Segment “B” chain is `segment_preview_video_buffer_` / `segment_preview_audio_buffer_` (and producer `segment_preview_`). They are created when `segment_preview_` is ready (**1136–1154**); **1152–1153** `StartFilling` is called (one frame pushed synchronously, rest filled by FillLoop asynchronously).
2. **No seam gating on B’s depth:** At segment seam tick we have `take_segment = (session_frame_index >= next_seam_frame_) && (next_seam_type_ == SeamType::kSegment)` (**1285**). When `take_segment` we always call `PerformSegmentSwap` (**1970**). There is no check that `segment_preview_audio_buffer_->DepthMs() >= threshold` or that segment preview video is primed before committing. So the seam is **time-based only**, not depth-gated.
3. **Swap uses B if present, regardless of fill state:** In `PerformSegmentSwap`, if `segment_preview_video_buffer_` is non-null we do the PREROLLED move (**2968–2971**). We do not require B to be “primed” or to have a minimum depth. So the tick loop can start consuming from the new live buffer (ex–segment-preview) when it may still have only the one frame pushed in `StartFilling`, with the rest filled asynchronously by FillLoop — i.e. a **race** between fill and consume.
4. **Block vs segment:** For **block** fence, INV-PREROLL-READY-001 (**1367–1375**) only **logs** when B is not primed; it does not prevent the take. There is no analogous “segment B must be primed or have DepthMs >= X” rule for segment seam.

**Therefore:** The design has separate A and B buffers for the segment (A = live, B = segment preview), but the **commit at segment seam is not gated** on B’s buffer depth or primed state. The switch to the new producer happens at the seam tick based on time alone, with B’s buffers being filled asynchronously after `StartFilling`. That matches **single-chain with async fill race** (no seam gating on B’s depth/readiness).
