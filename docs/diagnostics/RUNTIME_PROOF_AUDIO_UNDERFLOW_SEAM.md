# Runtime Proof: AUDIO_UNDERFLOW_SILENCE Cannot Occur at Segment Seam Due to A/B Swap

This document provides a **runtime proof request** checklist: verify that when the eligibility gate passes and we perform a segment swap (B→A), AUDIO_UNDERFLOW_SILENCE cannot occur on that same tick due to the swap itself. Evidence is via log sequence and code-path ordering.

---

## 1) Exact log lines and file:line anchors

| Log name | Purpose | File:line | Fields emitted |
|----------|---------|-----------|----------------|
| **B creation (success)** | EnsureIncomingBReadyForSeam created segment_b_* and called StartFilling | `PipelineManager.cpp:3000` | `[PipelineManager] EnsureIncomingBReadyForSeam B_ready` — `tick=`, `to_segment=`, `segment_b_audio_depth_ms=`, `segment_b_video_depth_frames=` |
| **B StartFilling start** | VideoLookaheadBuffer::StartFilling entry for segment B | `VideoLookaheadBuffer.cpp:71` | `[VideoBuffer:SEGMENT_B_VIDEO_BUFFER] StartFilling:` — `HasPrimedFrame=`, `has_decoder=`, `audio_buffer=` |
| **B StartFilling primed push** | First frame audio pushed to B’s audio buffer | `VideoLookaheadBuffer.cpp:94` | `[VideoBuffer:SEGMENT_B_VIDEO_BUFFER] StartFilling:` — `audio_depth_ms=` (after primed push) |
| **Gate – deferred** | Swap deferred (no B or not ready) | `PipelineManager.cpp:1962` or `1973` | `[PipelineManager] SEGMENT_SWAP_DEFERRED` — `reason=no_incoming|not_ready`, `incoming_audio_ms=`, `incoming_video_frames=`, `tick=` |
| **Gate – eligible** | Swap committed; state before swap | `PipelineManager.cpp:1990` | `[PipelineManager] SEGMENT_TAKE_COMMIT` — `tick=`, `from_segment=`, `to_segment= (to_type)`, `segment_b_audio_depth_ms=`, `segment_b_video_depth_frames=`, `audio_depth_ms=`, `audio_gen=`, `asset=`, `seg_b_ready=` |
| **PerformSegmentSwap result** | Swap completed; which branch | `PipelineManager.cpp:3205` | `[PipelineManager] SEGMENT_SEAM_TAKE` — `tick=`, `from_segment=`, `to_segment=`, `prep_mode=`, `swap_branch=`, `next_seam_frame=` |
| **Post-swap live depth** | Live audio buffer depth immediately after swap | `PipelineManager.cpp:2008` | `[PipelineManager] SEGMENT_SWAP_POST` — `tick=`, `live_audio_depth_ms=` |
| **AUDIO_UNDERFLOW_SILENCE** | Underflow diagnostic (if TryPopSamples fails) | `PipelineManager.cpp:2125` | `[PipelineManager] AUDIO_UNDERFLOW_SILENCE` — `frame=` (= session_frame_index), `buffer_depth_ms=`, `needed=`, `total_pushed=`, `total_popped=` |

---

## 2) Expected log sequence (same tick)

On a **segment seam tick** where the gate passes and swap runs, the following order must hold within that single tick:

1. **EnsureIncomingBReadyForSeam B_ready** — `tick=T`, `to_segment=K`, `segment_b_audio_depth_ms=`, `segment_b_video_depth_frames=`  
   (Only if B was created this tick; if B existed from a previous deferred tick, this line is absent this tick.)

2. **B StartFilling** (if B created this tick) — `[VideoBuffer:SEGMENT_B_VIDEO_BUFFER] StartFilling:` lines (entry, then primed audio_depth_ms).  
   These occur *inside* EnsureIncomingBReadyForSeam, so they appear *before* B_ready.

3. **SEGMENT_TAKE_COMMIT** — `tick=T`, `to_segment=K (Content|Pad)`, `segment_b_audio_depth_ms≥500`, `segment_b_video_depth_frames≥1`, plus current live `audio_depth_ms` and `seg_b_ready=1`.

4. **SEGMENT_SEAM_TAKE** — `tick=T`, `swap_branch=SWAP_B_TO_A` (content) or `PAD_SWAP` (pad), `prep_mode=PREROLLED` for content.

5. **SEGMENT_SWAP_POST** — `tick=T`, `live_audio_depth_ms=` (must equal `segment_b_audio_depth_ms` from step 3, same buffer moved into live).

6. **INV-AUDIO-LOOKAHEAD-001** audio pop: either success (no underflow) or **AUDIO_UNDERFLOW_SILENCE** — `frame=T`, `buffer_depth_ms=`, `needed=`, …

**Proof invariant:** If the gate passed, `segment_b_audio_depth_ms ≥ kMinSegmentSwapAudioMs` (500) and the live buffer after swap *is* the former B buffer. So `live_audio_depth_ms` in SEGMENT_SWAP_POST must equal the B depth at gate time; no consumer drains it between gate and pop. Therefore **AUDIO_UNDERFLOW_SILENCE must not occur on the same tick** when swap_branch is SWAP_B_TO_A and gate passed — unless there is a bug (e.g. wrong buffer, or drain between gate and pop).

---

## 3) Fields confirmed on the same tick

- **session_frame_index:** present as `tick=` on B_ready, SEGMENT_TAKE_COMMIT, SEGMENT_SEAM_TAKE, SEGMENT_SWAP_POST; as `frame=` on AUDIO_UNDERFLOW_SILENCE.
- **to_segment id/type:** `to_segment=` and `(Content|Pad)` in SEGMENT_TAKE_COMMIT and SEGMENT_SEAM_TAKE.
- **segment_b_audio_depth_ms and segment_b_video_depth_frames at gate time:** in SEGMENT_TAKE_COMMIT (`segment_b_audio_depth_ms=`, `segment_b_video_depth_frames=` from `*incoming`).
- **Live audio_buffer_ depth right after swap:** in SEGMENT_SWAP_POST (`live_audio_depth_ms=` from `a_src->DepthMs()` after `a_src = audio_buffer_.get()`).

---

## 4) Code path ordering (proof)

Single tick, `take_segment == true`:

1. **PipelineManager.cpp:1955** — `EnsureIncomingBReadyForSeam(to_seg, session_frame_index)`  
   - If CONTENT and worker result available: takes result, creates `segment_b_*`, calls `segment_b_video_buffer_->StartFilling(...)` (PipelineManager.cpp:2985).  
   - StartFilling logs at VideoLookaheadBuffer.cpp:71 and :94.  
   - On success, B_ready log at PipelineManager.cpp:3000.

2. **PipelineManager.cpp:1956** — `GetIncomingSegmentState(to_seg)`  
   - Reads from `segment_b_audio_buffer_` and `segment_b_video_buffer_` (DepthMs(), DepthFrames()) at PipelineManager.cpp:3003–3004 (GetIncomingSegmentState:3002–3006).  
   - Returns optional with `incoming_audio_ms`, `incoming_video_frames`.

3. **PipelineManager.cpp:1970 / 1983** — Gate: if `!incoming` → SEGMENT_SWAP_DEFERRED (1962); if `!IsIncomingSegmentEligibleForSwap(*incoming)` → SEGMENT_SWAP_DEFERRED (1973). Else eligible → SEGMENT_TAKE_COMMIT (1990).

4. **PipelineManager.cpp:2004** — `PerformSegmentSwap(session_frame_index)`  
   - Swap moves `segment_b_*` into `video_buffer_`/`audio_buffer_`/`live_` (3108–3112 for SWAP_B_TO_A).  
   - SEGMENT_SEAM_TAKE log at 3205.

5. **PipelineManager.cpp:2007** — `a_src = audio_buffer_.get();`  
6. **PipelineManager.cpp:2008** — SEGMENT_SWAP_POST with `live_audio_depth_ms=`.

7. Later in same tick: **PipelineManager.cpp:2096** — `a_src->TryPopSamples(...)`; on failure, **2125** — AUDIO_UNDERFLOW_SILENCE.

**Order:**  
`EnsureIncomingBReadyForSeam` → `GetIncomingSegmentState` (from B) → gate decision (eligible vs deferred) → `PerformSegmentSwap` → update `a_src` and SEGMENT_SWAP_POST → … → audio pop / underflow log.

So B is created and filled before the gate; the gate reads B’s state; swap only runs when eligible; after swap, live is the ex-B buffer; underflow log is after all of that on the same tick.

---

## 5) One-run proof checklist (known-bad commercial)

Use a run that previously showed AUDIO_UNDERFLOW_SILENCE at a segment seam (e.g. known-bad commercial segment boundary):

1. [ ] **Same tick**  
   For the seam tick T, all of: B_ready (if B created this tick), SEGMENT_TAKE_COMMIT, SEGMENT_SEAM_TAKE, SEGMENT_SWAP_POST share the same `tick=T`.

2. [ ] **Gate passed**  
   SEGMENT_TAKE_COMMIT shows `segment_b_audio_depth_ms≥500`, `segment_b_video_depth_frames≥1`, `seg_b_ready=1`.

3. [ ] **Swap branch**  
   SEGMENT_SEAM_TAKE shows `swap_branch=SWAP_B_TO_A` (or `PAD_SWAP` for pad).

4. [ ] **Depth consistency**  
   SEGMENT_SWAP_POST `live_audio_depth_ms` equals SEGMENT_TAKE_COMMIT `segment_b_audio_depth_ms` (same buffer).

5. [ ] **No underflow on seam tick**  
   There is no `AUDIO_UNDERFLOW_SILENCE` with `frame=T` on the seam tick T.  
   If underflow appears on a *later* tick, it is a separate issue (e.g. fill thread not keeping up), not “at segment seam due to A/B swap.”

6. [ ] **If underflow on seam tick**  
   Then either: gate should not have passed (check deferred logs on prior ticks), or there is a bug (e.g. buffer identity or drain between gate and pop). Capture full log sequence for that tick and compare to this document.

---

## 6) File:line anchor summary

| Site | File | Line(s) |
|------|------|--------|
| B creation success (B_ready) | pkg/air/src/blockplan/PipelineManager.cpp | 3000–3006 |
| B StartFilling entry | pkg/air/src/blockplan/VideoLookaheadBuffer.cpp | 71–76 |
| B StartFilling audio_depth_ms after push | pkg/air/src/blockplan/VideoLookaheadBuffer.cpp | 94–97 |
| Gate deferred (no_incoming) | pkg/air/src/blockplan/PipelineManager.cpp | 1962–1967 |
| Gate deferred (not_ready) | pkg/air/src/blockplan/PipelineManager.cpp | 1973–1979 |
| Gate eligible (SEGMENT_TAKE_COMMIT) | pkg/air/src/blockplan/PipelineManager.cpp | 1986–2001 |
| PerformSegmentSwap (SEGMENT_SEAM_TAKE) | pkg/air/src/blockplan/PipelineManager.cpp | 3205–3212 |
| Post-swap live depth (SEGMENT_SWAP_POST) | pkg/air/src/blockplan/PipelineManager.cpp | 2007–2011 |
| AUDIO_UNDERFLOW_SILENCE | pkg/air/src/blockplan/PipelineManager.cpp | 2125–2131 |
| Order: EnsureIncomingBReadyForSeam | pkg/air/src/blockplan/PipelineManager.cpp | 1955 |
| Order: GetIncomingSegmentState | pkg/air/src/blockplan/PipelineManager.cpp | 1956 |
| Order: Gate / PerformSegmentSwap | pkg/air/src/blockplan/PipelineManager.cpp | 1970–1982, 2004 |
