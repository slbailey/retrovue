# AUDIO_UNDERFLOW at PREROLLED Segment Seam — Code Trace and Root Cause

## 1) Where `audio_depth_ms` is computed for PREP_COMPLETE and which buffer it measures

**File:** `pkg/air/src/blockplan/SeamPreparer.cpp`  
**Lines:** 232, 279.

- **Computation:** `audio_depth_ms` is **not** read from any `AudioLookaheadBuffer`. It comes from the **SeamPreparer worker’s** `PrimeFirstTick()` return value:
  - Line 232: `auto prime_result = source->PrimeFirstTick(req.min_audio_prime_ms);`
  - Line 279: `<< " audio_depth_ms=" << prime_result.actual_depth_ms`

- **What it measures:** `actual_depth_ms` is computed inside **TickProducer::PrimeFirstTick** (`pkg/air/src/blockplan/TickProducer.cpp` lines 275–356). It is the **total audio sample count** of the decoded frames held **inside that TickProducer** (in `primed_frame_` and `primed_frames` / `buffered_frames_`), converted to ms:
  - Lines 282–288: count samples from `primed_frame_`; lines 327–332: accumulate from each `DecodeNextFrameRaw()` frame; line 330–331: `depth_ms = (audio_samples * 1000) / buffer::kHouseAudioSampleRate`.
  - So **PREP_COMPLETE’s `audio_depth_ms` is the depth of decoded audio inside the worker’s TickProducer**, not the depth of any preview or live `AudioLookaheadBuffer`.

**Conclusion:** PREP_COMPLETE’s `audio_depth_ms=512` is the **segment prep worker’s primed + buffered decoded audio (512 ms)**. It does **not** measure `segment_preview_audio_buffer_` or any other buffer (and in the current code path, segment preview buffers are not used for segment seam; see section 3).

---

## 2) Where `buffer_depth_ms` is computed for AUDIO_UNDERFLOW_SILENCE and which buffer it measures

**File:** `pkg/air/src/blockplan/PipelineManager.cpp`  
**Lines:** 2084–2086.

- **Computation:**  
  `oss << "[PipelineManager] AUDIO_UNDERFLOW_SILENCE" << " frame=" << session_frame_index << " buffer_depth_ms=" << a_src->DepthMs() << ...`

- **Buffer:** `a_src` is the **live** `AudioLookaheadBuffer` at the moment of the tick. It is set earlier in the same tick iteration:
  - Lines 1299–1312: if `take_segment && segment_preview_video_buffer_` then `a_src = segment_preview_audio_buffer_.get()`, else if no swap then `a_src = audio_buffer_.get()`.
  - After `PerformSegmentSwap` (line 1970), line 1973 updates: `a_src = audio_buffer_.get()`.
  So on the ticks **after** the seam take, `a_src` is always **`audio_buffer_`** (the live buffer).

- **Depth calculation:** `DepthMs()` is implemented in **`pkg/air/src/blockplan/AudioLookaheadBuffer.cpp`** lines 156–159:  
  `return (total_samples_in_buffer_ * 1000) / sample_rate_;`  
  So **`buffer_depth_ms` in AUDIO_UNDERFLOW_SILENCE is the current depth in ms of the live `audio_buffer_`**.

**Conclusion:** AUDIO_UNDERFLOW_SILENCE’s `buffer_depth_ms` is the **live** `AudioLookaheadBuffer`’s depth (`audio_buffer_`), via `a_src->DepthMs()` at PipelineManager.cpp:2086, with depth computed in AudioLookaheadBuffer.cpp:156–159.

---

## 3) PREROLLED seam path: where preview audio is transferred (or not)

**PREROLLED path used in the log:** The log shows `prep_mode=PREROLLED` and `[FillLoop:LIVE_AUDIO_BUFFER] ENTER` right after `SEGMENT_SEAM_TAKE`. So the path taken is **not** the one that moves `segment_preview_video_buffer_` / `segment_preview_audio_buffer_` into live.

- **Segment preview buffers:** In the codebase, **`segment_preview_` is never assigned** (only `.reset()` at teardown). The block that would create `segment_preview_video_buffer_` / `segment_preview_audio_buffer_` is at PipelineManager.cpp:1136–1155 and is gated on `segment_preview_` (comment at 1135: “Segment preview is no longer populated here”). So for segment seams, **segment preview buffers are not used**.

- **Actual PREROLLED path:** PerformSegmentSwap (PipelineManager.cpp:2968–3017):
  - **First branch (2968):** `if (segment_preview_video_buffer_)` → move segment preview into live. This is **not** taken because `segment_preview_video_buffer_` is never created (segment_preview_ never set).
  - **Second branch (2977–3004):** `else if (seam_preparer_->HasSegmentResult())` → **TakeSegmentResult()**, then:
    - `live_ = std::move(result->producer);` (worker’s primed TickProducer)
    - **New** `video_buffer_` and **new** `audio_buffer_` are created (2996, 2995–2997).
    - `StartFilling(AsTickProducer(live_.get()), audio_buffer_.get(), ...)` (2998–3001).

So on PREROLLED segment seam there is **no transfer** of preview audio into the live buffer. The live buffer is **newly created** and only gets audio from:
1. **StartFilling** (synchronous): one primed frame’s audio pushed in VideoLookaheadBuffer.cpp:90–93.
2. **FillLoop** (async): remaining frames from the same producer’s `buffered_frames_` (and further decode) pushed as the fill thread runs.

There is no code path that copies or moves the worker’s 512 ms of primed/buffered audio into the live `AudioLookaheadBuffer`; that 512 ms stays inside the worker’s TickProducer until the fill thread drains it via `TryGetFrame()` and pushes each frame’s audio.

**Conclusion:** For PREROLLED segment seams, preview audio is **not** “handed off” to the live buffer. The live buffer is a new buffer; only the first frame’s audio is pushed in StartFilling; the rest of the primed audio remains in the producer and is pushed asynchronously by the fill thread.

---

## 4) Why `cadence_active=0` and `my_audio_gen=0` at LIVE_AUDIO_BUFFER entry matter; where they are set

**Where they are set:**  
**File:** `pkg/air/src/blockplan/VideoLookaheadBuffer.cpp`  
**Lines:** 205–207 (`my_audio_gen`), 211–218 (`cadence_active`), 257–264 (logged at FillLoop ENTER).

- **my_audio_gen:** Captured at fill thread start (lines 205–207):  
  `uint64_t my_audio_gen = 0;` then `if (audio_buffer) { my_audio_gen = audio_buffer->CurrentGeneration(); }`  
  For a **new** `AudioLookaheadBuffer` (just created in PerformSegmentSwap), `CurrentGeneration()` is 0, so **my_audio_gen=0**. So the fill thread does not use a generation check to reject pushes (AudioLookaheadBuffer::Push accepts `expected_generation == 0` without matching; see AudioLookaheadBuffer.cpp:45–52, 64–71). So **my_audio_gen=0** does not by itself block pushes; it just reflects a fresh buffer.

- **cadence_active:** Set at lines 211–218:  
  `cadence_active = (input_fps_ > 0.0 && input_fps_ < output_fps_ * 0.98);`  
  For **60 fps input** and **30 fps output**, `60 < 30*0.98` is false, so **cadence_active=false** (cadence_OFF). So every output tick the fill thread **decodes one frame** and pushes that frame’s audio (no cadence “repeat” / skip). That means the fill thread is doing one decode per tick; it does not “hold” or duplicate frames. So we rely on decode rate to keep the buffer filled.

**Why it matters for PREROLLED:**  
At seam time we have a **new** live buffer with only **one frame’s audio** (~17 ms) from StartFilling. The fill thread has just started (FillLoop ENTER) and will push from `buffered_frames_` and then decode. With **cadence_active=0**, we need one decode per output tick to sustain 30 fps. If the tick thread runs before the fill thread has pushed enough (e.g. the remaining ~495 ms from buffered_frames_), we **underflow** (buffer_depth_ms=17, needed=1600 samples ≈ 33 ms). So **cadence_active=0** means we depend on immediate, full decode throughput; there is no cadence “cushion,” and the initial buffer has only one frame’s worth of audio, so underflow on the first ticks is expected.

**Citations:**  
- VideoLookaheadBuffer.cpp:205–207 (my_audio_gen), 211–218 (cadence_active), 257–264 (ENTER log).  
- AudioLookaheadBuffer.cpp:45–52, 64–71 (Push accepts gen 0).  
- VideoLookaheadBuffer.cpp:404–411 (should_decode when cadence_active; 60→30 decodes every time).

---

## 5) Most likely root cause (one sentence + evidence)

**Conclusion:** **Pre-roll audio is not being handed off:** the 512 ms from PrimeFirstTick lives only inside the SeamPreparer worker’s TickProducer (`primed_frame_` + `buffered_frames_`); at PREROLLED seam time the live path creates a **new** `AudioLookaheadBuffer` and only the **first frame’s** audio (~17 ms) is pushed into it in StartFilling; the rest is pushed asynchronously by the fill thread, so the tick thread underflows (buffer_depth_ms=17, needed=1600) until the fill thread catches up, and with 60 fps source and no cadence cushion we stay at the edge or behind.

**Evidence (code + log):**

1. **PREP_COMPLETE’s 512 ms is not in any buffer**  
   SeamPreparer.cpp:232, 279 — `audio_depth_ms` is `prime_result.actual_depth_ms` from TickProducer::PrimeFirstTick. TickProducer.cpp:282–332 — that value is the sum of audio samples in the producer’s primed/buffered frames only; nothing is pushed to an AudioLookaheadBuffer there. So the log’s `PREP_COMPLETE ... audio_depth_ms=512` does not imply 512 ms in the live buffer.

2. **Live buffer gets only one frame at swap**  
   PerformSegmentSwap uses HasSegmentResult() (no segment_preview_video_buffer_): PipelineManager.cpp:2977–3001. It creates a new `audio_buffer_` and calls StartFilling(live_, audio_buffer_, ...). VideoLookaheadBuffer.cpp:76–97: StartFilling calls TryGetFrame() once and pushes that single frame’s audio to the buffer. So the new live buffer has only one frame’s worth (~17 ms). Log: `buffer_depth_ms=17` at first underflow matches one frame at 48 kHz.

3. **Underflow immediately after PREP_COMPLETE**  
   Log order: `SEGMENT_SEAM_TAKE ... prep_mode=PREROLLED` → `[FillLoop:LIVE_AUDIO_BUFFER] ENTER ... cadence_active=0 my_audio_gen=0` → later `PREP_COMPLETE ... audio_depth_ms=512` (for next segment) → `AUDIO_UNDERFLOW_SILENCE frame=2241 buffer_depth_ms=17 needed=1600`. So right after the PREROLLED swap the live buffer has 17 ms and the tick needs 1600 samples; the fill thread has not yet pushed the remaining primed audio from the producer, so underflow is expected and matches “pre-roll audio not handed off.”

---

## Summary table

| Item | Location | What it measures |
|------|----------|------------------|
| PREP_COMPLETE `audio_depth_ms` | SeamPreparer.cpp:232, 279 (from TickProducer::PrimeFirstTick) | Decoded audio inside the **worker’s TickProducer** (primed + buffered frames), not any buffer. |
| AUDIO_UNDERFLOW_SILENCE `buffer_depth_ms` | PipelineManager.cpp:2086 `a_src->DepthMs()`; a_src = audio_buffer_.get() after swap (1973) | **Live** `AudioLookaheadBuffer` depth (AudioLookaheadBuffer.cpp:156–159). |
| PREROLLED “transfer” | No transfer. PerformSegmentSwap 2977–3001: new buffers + StartFilling with result->producer; only first frame pushed in StartFilling (VideoLookaheadBuffer.cpp:76–97). | Pre-roll audio beyond the first frame stays in the producer and is pushed asynchronously by the fill thread. |
