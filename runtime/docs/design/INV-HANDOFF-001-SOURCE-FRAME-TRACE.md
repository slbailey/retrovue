# INV-HANDOFF-001: Source-Frame Selection Trace and Root Cause

**Invariant:** For every output tick where we emit content (ADVANCE or REPEAT),  
**actual_src_emitted == selected_src**  
(where `selected_src = SourceFrameForTick(output_tick)`).

**Violation:** Logs `INV-HANDOFF-001 VIOLATION` with output_tick, selected_src, actual_src_emitted, path.  
Observed: +26 offset at first content tick, then growing gap in decode path.

---

## 1. Where `actual_src_emitted` is assigned

- **PipelineManager** (tick loop): On ADVANCE we call `v_src->TryPopFrame(vbf)` and set  
  `last_good_source_frame_index_ = vbf.source_frame_index`.  
  That value is what we use as “actual_src_emitted” for this tick (and for the next REPEAT tick).
- **VideoBufferFrame.source_frame_index** is set when the frame is **pushed** to the buffer, not when it is popped.
- **VideoLookaheadBuffer** (fill thread and StartFilling): When pushing a frame it sets  
  `vf.source_frame_index = fd->source_frame_index` from the `FrameData` returned by `producer->TryGetFrame()`.
- **TickProducer::TryGetFrame()** sets `fd->source_frame_index` (and `fd->frame_path`) on every return path:
  - **Primed:** `frame.source_frame_index = frame_index_` (then `frame_index_++`).
  - **Buffered:** `frame.source_frame_index = frame_index_` (then `frame_index_++`).
  - **Decode (OFF/CADENCE):** `fd->source_frame_index = frame_index_ - 1` (after `DecodeNextFrameRaw()` has already incremented `frame_index_`).

So **actual_src_emitted** is the **decode-order index** of the frame that the **fill thread** last pushed and the **tick loop** then popped. It is **not** derived from `SourceFrameForTick` anywhere; it is whatever index the producer stamped when it produced that frame.

---

## 2. How buffered/decoded frames are “matched” to SourceFrameForTick

They are **not** matched.

- **Tick loop** computes `selected_src_this_tick = SourceFrameForTick(resample_tick_, ...)` and decides ADVANCE vs REPEAT.
- On **ADVANCE** it **pops the head** of the video buffer (`TryPopFrame(vbf)`) and uses that frame. There is **no check** that `vbf.source_frame_index == selected_src_this_tick`.
- The **fill thread** runs independently: when depth &lt; target it calls `TryGetFrame()` and pushes the returned frame. It never asks “what source index does the tick loop need?”.

So the architecture is **“next frame wins”**: the frame at the front of the queue is used for this tick. The queue is a **FIFO in decode order**. For the invariant to hold, the **head of the queue** must always be the frame for **selected_src** for the current output tick. That requires the **fill thread** to push frames in the same **order and cadence** as the tick loop consumes them (including REPEAT: no new frame pushed when the tick loop would REPEAT). Today the fill thread does **not** follow the tick loop’s cadence; it fills up to target depth by calling `TryGetFrame()` whenever it can, so the queue can contain “future” frames and we advance source too fast.

---

## 3. Where the +26 startup offset is introduced

- **Observed:** First content tick has `actual_src_emitted=27` and `path=primed`, while `selected_src=1`.
- So the **first frame** we popped from the live buffer had `source_frame_index == 27` and was produced on the **primed** path.
- On the primed path we set `frame.source_frame_index = frame_index_`. So when that primed frame was returned, **frame_index_ was 27**.
- So the producer that filled the **live** buffer had already **returned 27 frames** before returning that “primed” frame. So either:
  - The **same** producer was used to fill another buffer first (e.g. segment B or preview), advanced to 27, then was used to fill the live buffer **without** being reset (no new `AssignBlock`), so the first frame it supplied to the live buffer was stamped 27; or
  - The live buffer was (re)started with a producer that had **not** had `frame_index_` reset to 0 for this segment (e.g. segment swap path that flushes the live buffer and calls `StartFilling(live_buffer, segment_b_producer_)` while `segment_b_producer_` has already advanced to 27).

**Conclusion:** The +26 offset is introduced when we **start filling the live buffer** with a producer whose **frame_index_** is not 0 for the segment we are displaying. That can happen if:

1. We reuse a producer that was previously used to fill another buffer (e.g. segment B or preview) and we do **not** move that buffer into the live slot (buffer swap); instead we flush the live buffer and call `StartFilling(video_buffer_, that_producer)`, so the first frame pushed is the producer’s “next” frame (e.g. 27).
2. We assign a new block/segment but **do not** call `AssignBlock` on the producer before priming/filling, so `frame_index_` is never reset to 0.
3. Some path passes the “wrong” producer (e.g. still the old segment’s producer with advanced `frame_index_`) into `StartFilling` for the live buffer.

**Fix direction:** Ensure that whenever the **live** buffer is filled for a new segment/block, the producer used has **frame_index_ == 0** for that content (i.e. `AssignBlock` was called and no frames have been taken from that producer for this segment yet). Prefer **buffer swap** (move the already-filled segment B buffer to live) over “flush live + StartFilling with segment B producer”, so we never re-fill the live buffer with a producer that has already advanced.

---

## 4. Why the offset grows after the decode path takes over

- **Tick loop:** Each ADVANCE pops **one** frame from the buffer. So we consume one frame per ADVANCE tick.
- **Fill thread:** Whenever depth &lt; target it calls `TryGetFrame()` and pushes **one** frame. So it pushes as fast as the buffer drains (plus refill to target). In steady state the fill thread runs **whenever a pop happens** (it’s woken by space), so it tends to push one frame per pop. But it does **not** know about REPEAT: the tick loop may REPEAT (not pop) for several ticks, while the fill thread may still have been woken earlier and already pushed extra frames. So the buffer can contain “future” frames (e.g. we need selected_src=42 but the head is already 71).
- **Decode path** in TickProducer returns the **next** decoded frame and stamps it with `frame_index_ - 1`. So the fill thread is always pushing the **next** frame in decode order. If the buffer ever gets ahead (e.g. due to the +26 startup offset or due to fill thread pushing without the tick loop popping on REPEAT), then every subsequent ADVANCE pops that “ahead” frame and we never catch up. So **actual_src_emitted** drifts further ahead of **selected_src**.

So the growth is because:
1. We never **discard** or **skip** frames in the buffer to realign with `selected_src`.
2. The fill thread is **not** cadence-aware: it doesn’t only push when the next frame needed by the tick loop is the next decode.

---

## 5. Frame_index_ / decode-order leaking across segment startup or buffer fill

- **TickProducer::AssignBlock()** sets `frame_index_ = 0` (and assigns the block). So a **new** block always starts at 0.
- **PrimeFirstTick** does **not** reset `frame_index_`; it only fills `primed_frame_` and `buffered_frames_`. So after prime, `frame_index_` is still 0.
- When we **move** a buffer (e.g. segment_b_video_buffer_ → video_buffer_ in PerformSegmentSwap), we do **not** call `StartFilling` again; the buffer already has the correct frames (0, 1, 2, …) from when segment B was being filled. So no leak there.
- Leak happens when we **reuse** a producer that has already been used (frame_index_ &gt; 0) to **start filling** a buffer that will be the live buffer, and we don’t assign a new block. So the “first” frame we push for that buffer is stamped with the current `frame_index_` (e.g. 27). Any path that does “flush live buffer then StartFilling(live_buffer, producer_that_has_already_advanced)” introduces the leak.

---

## 6. Queue semantics: “next frame wins” vs “frame matching selected_src wins”

- **Current:** “Next frame wins” — we pop the **head** of the queue. No lookup by source index. So whatever the fill thread pushed last (in order) is what we show. For the invariant to hold, the head must always be the frame for `selected_src`. That requires the **producer order** and **push rate** to match the **tick loop’s consumption and cadence** (REPEAT = don’t push).
- **Alternative:** “Frame matching selected_src wins” — we would need either (a) to **peek/discard** until the head has `source_frame_index == selected_src`, or (b) to **drive the fill thread** by the tick loop so it only pushes the frame for the next `selected_src` when we ADVANCE. Option (a) would drop frames and complicate ordering; option (b) aligns push with cadence and preserves the invariant.

The intended design is (b): the **tick loop** is the authority for **which** source frame is shown; the fill thread should only supply frames in the order and rate implied by `SourceFrameForTick` and ADVANCE/REPEAT. Today the fill thread is only “depth”-driven, not “selected_src”-driven, so we get “next frame wins” and the invariant fails whenever the queue is ahead.

---

## 7. Summary: what must change to satisfy actual_src_emitted == selected_src

1. **Startup / segment handoff:** When the live buffer is first filled for a segment (or block), the producer used must have **frame_index_ == 0** for that segment. Prefer buffer swap so the buffer that already has frames 0,1,… becomes live; avoid “flush live + StartFilling with an already-advanced producer”.
2. **Cadence alignment:** Either (A) make the fill thread **cadence-aware** so it only pushes when the next frame it would push is the one the tick loop will need on the next ADVANCE (e.g. pass `selected_src` or “allow one push” from tick loop), or (B) have the tick loop **skip/discard** buffer frames until the head has `source_frame_index == selected_src` (wasteful and can cause underflow). Option (A) is the correct long-term fix.
3. **Invariant check:** Keep INV-HANDOFF-001: log Error when `last_good_source_frame_index_ != selected_src_this_tick` so any regression is caught immediately.

This document is the trace and analysis; implementation of (1) and (2) is the actual bug fix.

---

## 8. Phase 1 implementation (startup / producer reuse fix)

**Goal:** First content frame has `actual_src_emitted == 0` (or 1 per indexing); remove the +26 startup offset. No change to queue semantics.

**Changes:**

1. **`ITickProducer::GetSourceFrameIndex()`**  
   Returns the 0-based source frame index for the next frame this producer would emit (`-1` if not applicable). `TickProducer` returns `frame_index_` when state is `kReady`.

2. **`PipelineManager::EnsureLiveProducerAtSegmentStart()`**  
   If `live_` is READY and `GetSourceFrameIndex() > 0`, replaces `live_` with a fresh `TickProducer`, assigns the same block via `AssignBlock(block)`, so the next `StartFilling` emits from `source_frame_index` 0.

3. **Call sites for live buffer fill (ensure or swap):**
   - **Session start:** After `TryLoadLiveProducer()`, call `EnsureLiveProducerAtSegmentStart()` before priming and before the main loop’s first `StartFilling`. Ensures first block uses a producer at segment start even when adopted from preload.
   - **Block swap fallback (no preview buffer):** Before creating new `video_buffer_` and calling `StartFilling(live_tp(), ...)`, call `EnsureLiveProducerAtSegmentStart()` so the producer used for the new buffer has `frame_index_ == 0`.
   - **PADDED_GAP_EXIT:** If `preview_video_buffer_` is non-null, **swap** it to `video_buffer_` (and `preview_audio_buffer_` to `audio_buffer_`) so the buffer already filled by this producer becomes live; then call `StartFilling` to restart the fill thread. If `preview_video_buffer_` is null, call `EnsureLiveProducerAtSegmentStart()` then `StartFilling` on the existing live buffer.

**Verification:** After Phase 1, run the same diagnostic logs and confirm `actual_src_emitted == selected_src` for at least the first 300 ticks. If the invariant still breaks later in steady state, Phase 3 (cadence-aware fill) applies.

---

## 9. Phase 2a — Decode-path boundary indexing

**Validated:** Ticks 1–30 (primed + buffered) satisfy `actual_src_emitted == selected_src` after 1-based primed/buffered fix.

**Remaining bug:** At tick 31 (first decode-path frame), `selected_src=25` but `actual_src_emitted=26`. The first decode frame was stamped one too high.

**Cause:** In the OFF/CADENCE decode path we had `fd->source_frame_index = frame_index_`. `DecodeNextFrameRaw()` returns the frame it just decoded and *then* increments `frame_index_`, so when we assign we see the *post*-increment value. The frame we have is the one at index `frame_index_ - 1` (1-based).

**Fix (decode path only):** Set `fd->source_frame_index = frame_index_ - 1` so the first decode frame after the buffered region is 25 at tick 31. Startup/primed/buffered logic unchanged.

**Revalidate (Phase 2b):** First 50 ticks, first 300 ticks, violation count, 5–10 s window. If steady-state drift still grows (e.g. actual ≫ selected by tick 290), Phase 3 (cadence-aware fill) required.

---

## 10. Phase 3 — Cadence-aware fill

**Goal:** Align fill thread with tick loop so only frames required by `SourceFrameForTick` are pushed. Queue semantics change from “next frame wins” (FIFO) to “frame matching selected_src wins” by gating decode on the tick loop’s required source index.

**Changes:**

1. **`VideoLookaheadBuffer::SetNextRequiredSourceFrame(int64_t idx)`**  
   Public setter; stores in `next_required_source_frame_` (atomic). `-1` = disabled (fill freely). Called by PipelineManager each tick when resample is enabled and the live buffer is the video source.

2. **`VideoLookaheadBuffer`: atomic `next_required_source_frame_{-1}`**  
   Read by the fill thread with acquire; written by the tick loop with release.

3. **Fill thread cadence gate (in `FillLoop`):**  
   Before calling `TryGetFrame()`, if `next_required_source_frame_ >= 0` and `producer->GetSourceFrameIndex() > next_required_source_frame_`, do not decode this iteration; sleep 1 ms and continue. So the fill thread only pushes when the next frame the producer would return is ≤ the frame the tick loop needs.

4. **`PipelineManager`:**  
   In the resample/cadence block, when `v_src == video_buffer_.get()`, call `video_buffer_->SetNextRequiredSourceFrame(curr_src + TargetDepthFrames())` so the fill thread may stay up to one target-depth ahead — avoids underflow while capping run-ahead.

5. **`StartFilling`:**  
   Reset `next_required_source_frame_` to `-1` so the gate is disabled until the tick loop sets it (avoids blocking bootstrap).

6. **Audio liveness bypass:** When cadence-gated (producer ahead of `next_required`), if `audio_buffer->DepthMs() < audio_buffer->TargetDepthMs()`, still decode and push audio but set `drop_video_this_cycle` so the video frame is not enqueued. Use **target** (not low-water) so decode runs whenever audio is below target, avoiding oscillation around a tight low-water threshold and micro jitter.

**Invariant:** `actual_src_emitted == selected_src` continues to be checked; Phase 3 prevents run-ahead by ensuring the fill thread does not push frames ahead of cadence.

---

## 11. Frame-store redesign (alternative)

The cadence-gate approach keeps FIFO semantics and enforces alignment in the fill thread. A different design is to make the **tick loop the sole authority** and have the consumer **request the exact frame** by `source_frame_index`. See **INV-HANDOFF-001-FRAME-STORE-REDESIGN.md** for:

- Frame store keyed by `source_frame_index` (no FIFO).
- Tick loop requests `selected_src`; REPEAT reuses prior frame; audio independent.
- Phased plan: Phase A = intermediate proof (consumer discards until head matches `selected_src`); Phases B–D = frame store and simplified fill.
