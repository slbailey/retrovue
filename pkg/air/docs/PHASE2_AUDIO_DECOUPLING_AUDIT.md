# Phase 2 Audio Decoupling Audit

**Date:** 2025-02-22  
**Scope:** Verify that Phase 2 (PumpDecoderOnce + packet-level backpressure) preserves the intent: audio production decoupled from video decode/backpressure. Audit only — no new architecture.

---

## Executive verdict: **Still coupled**

Audio production remains coupled to video buffer health. When the fill thread parks at video high-water (`space_cv_.wait` in `VideoLookaheadBuffer::FillLoop`), it performs no decode and therefore no audio production. **PumpDecoderOnce** and the deferred-video / pending-video queue are implemented and correct in `FFmpegDecoder`, but **no production path calls them**. The only path that runs decode is `TryGetFrame()` → `DecodeFrameToBuffer()` → `ReadAndDecodeFrame()` (the legacy demux loop). That path is only entered when the fill thread is not parked, so video backpressure (high depth → park) still starves audio. The “audio burst” and bootstrap logic allow the fill thread to wake and decode when audio is critically low (so more video frames are pushed up to 4× target); that is a compensation layer, not true decoupling via PumpDecoderOnce(kAudioOnlyService) / DrainAudioOnly.

---

## Invariant checklist

| Invariant | Result | Evidence |
|-----------|--------|----------|
| **INV-AUDIO-LIVENESS:** Audio must continue flowing when video buffer is full / backpressured, cadence repeat/skip, or video decode stalls / packet defer | **FAIL** | FillLoop parks in `VideoLookaheadBuffer.cpp:360` `space_cv_.wait(...)` when `depth > target_depth_frames_` and (in steady state) `depth > target_depth_frames_` and not in audio-burst or bootstrap. While parked, the fill thread never calls `TryGetFrame()` or any decoder API, so no `ReadAndDecodeFrame()` and no `PumpDecoderOnce()`. Audio is only produced when the thread wakes and runs `producer->TryGetFrame()` (line 450). So video backpressure (high depth → park) stops both video and audio production. Burst wake (audio_depth_ms < audio_burst_threshold_ms_, line 388) allows decode to run again but by allowing more video frames to be pushed, not by servicing audio without pushing video. |
| **No audio duplication for cadence repeats** (video may repeat, audio must not “repeat samples” to match repeats) | **PASS** | FillLoop: on cadence repeat (`should_decode == false` and `have_last_decoded`), it pushes **silence** to the audio buffer (`VideoLookaheadBuffer.cpp:371–374`) only when `content_gap`; on advance decode it pushes decoded audio from `fd->audio`. TickLoop: every tick (advance or repeat) pops one tick’s worth of samples from `AudioLookaheadBuffer` (`PipelineManager.cpp:2233–2236`). So repeat ticks consume one tick of audio that was either (a) decoded on a previous advance or (b) silence pushed by FillLoop on a repeat cycle. No duplicate decoded samples. |
| **Decode gating must not be “video-only”:** if audio buffer is low, decode must be able to proceed even if video cannot be advanced/pushed | **FAIL** | Decode gating is in FillLoop and is video-depth-centric. When not in bootstrap, the thread proceeds when `depth < high_water` (FILLING path) or when the condvar predicate is true (PARKED path). The predicate allows wake when audio is critically low (`audio_buffer->DepthMs() < audio_burst_threshold_ms_` and `depth < burst_cap`) — so decode *can* run when audio is low, but only by **pushing more video frames** (up to 4× target). There is no path that runs **audio-only** decode (PumpDecoderOnce(kAudioOnlyService)) while video is not pushed. So “decode proceeds without advancing video” is not implemented. |
| **Producer/Consumer split:** FillLoop fills based on health/backpressure; TickLoop repeat must not pop video; audio production not blocked by video decisions | **PASS** (structure) / **FAIL** (liveness) | FillLoop: fills based on depth, bootstrap, and burst (`VideoLookaheadBuffer.cpp:324–393`). TickLoop: on cadence repeat does **not** call `TryPopFrame()` (`PipelineManager.cpp:1470–1487`); it re-encodes `last_good_video_frame_`. So repeat does not pop video — correct. Audio production is still effectively blocked by video decisions because the only way to produce audio is to run the fill thread, and the fill thread parks when video is full and does not run PumpDecoderOnce(kAudioOnlyService). |
| **Audio consumption paced by output ticks; audio production must not be blocked by video decisions** | **FAIL** | Audio consumption: one tick of samples per tick from `AudioLookaheadBuffer` — correct. Audio production: happens only when FillLoop runs and calls `TryGetFrame()` → `DecodeFrameToBuffer()` → `ReadAndDecodeFrame()`. When FillLoop is parked due to video depth, production stops. So production is blocked by video (park) decisions. |

---

## Phase 2 infrastructure status

| Question | Answer | Evidence |
|----------|--------|----------|
| Is **PumpDecoderOnce** present, correct, and used in the right place? | Present and correct; **not used** in production. | `FFmpegDecoder::PumpDecoderOnce` implemented in `pkg/air/src/decode/FFmpegDecoder.cpp:1121–1354`. Adapter forwards in `FFmpegDecoderAdapter.cpp:43–44`. No callers in `VideoLookaheadBuffer.cpp`, `PipelineManager.cpp`, or `TickProducer.cpp`. Only tests and reference doc reference it. |
| Is packet-level backpressure + deferred queue functioning as intended? | Implementation is correct; **never exercised** because PumpDecoderOnce is never called. | `deferred_video_packets_`, `pending_video_frames_`, `DrainVideoFrames`, `DrainAudioFrames`, kAudioOnlyService (defer video, service audio) are implemented. `DecodeFrameToBuffer` does **not** consume from `pending_video_frames_`; it uses `ReadAndDecodeFrame` (legacy loop). So the queue is only filled by PumpDecoderOnce, which is never called. |
| Any accidental re-coupling (e.g. ReadAndDecodeFrame draining video without processing audio)? | No re-coupling in ReadAndDecodeFrame. | `ReadAndDecodeFrame` (`FFmpegDecoder.cpp:711–818`) does process audio: on audio packet it sends to audio codec, drains to `pending_audio_frames_`, and continues. So when it runs, audio is serviced. The issue is that it **doesn’t run** when the fill thread is parked. |
| If Phase 2b (DrainAudioOnly) is NOT implemented, does scaffolding support it cleanly? | Yes. | `PumpDecoderOnce(PumpMode::kAudioOnlyService)` defers video packets to `deferred_video_packets_` and services audio only; audio frames go to `pending_audio_frames_`. A future “DrainAudioOnly” could: when FillLoop is parked (video depth ≥ high_water), loop `PumpDecoderOnce(kAudioOnlyService)` and push `GetPendingAudioFrame()` into `AudioLookaheadBuffer` until kBackpressured or kEof. No change to decoder API required. |

---

## Regression risk scan (compensation layers)

| Item | Status | Location / note |
|------|--------|------------------|
| **Burst thresholds** | Still present | `VideoLookaheadBuffer.cpp:343–344` (high_water 2× or 4× when `audio_boost_`), `387–390` (wake when `audio_buffer->DepthMs() < audio_burst_threshold_ms_` and `depth < burst_cap`). Compensation: allows decode to run when audio is low by allowing more video frames. |
| **Audio boost / hysteresis** | Still present | `audio_boost_` (`SetAudioBoost`, line 430–436), `steady_filling_` (INV-BUFFER-HYSTERESIS-001). Used for burst-fill and high-water cap. |
| **Silence padding when video blocked** | Not “when video blocked” in a generic sense | Silence is pushed in FillLoop only for (1) **content gap** (hold-last: `have_last_decoded` and `!fd`, line 364–368) and (2) **cadence repeat** when `content_gap` (line 371–374). Both are explicit hold-last/cadence behavior, not “silence because video buffer is full.” So no red-flag “silence when video blocked” path. |
| **AUDIO_UNDERFLOW_SILENCE** | Present as transitional fallback | `PipelineManager.cpp:2245–2267`: when buffer can’t satisfy `TryPopSamples`, inject silence and log. Contract INV-AUDIO-LIVENESS-002 says underflow silence must be transitional; if audio production flatlines due to video park, this would fire repeatedly — consistent with INV-AUDIO-LIVENESS violation, not a new compensation. |

---

## Top 3 concrete risks (even if fixes are applied)

1. **PumpDecoderOnce still unused after Phase 2b**  
   If Phase 2b adds a DrainAudioOnly path that calls PumpDecoderOnce(kAudioOnlyService) only when parked, any bug that keeps the fill thread “filling” (e.g. high_water never reached) could mean DrainAudioOnly is never exercised and audio-video coupling persists in practice under load.

2. **DecodeFrameToBuffer not consuming pending_video_frames_**  
   The reference doc (`PHASE2_DECODER_REFERENCE.cpp`) shows ReadAndDecodeFrame refactored to “while (pending_video_frames_.empty()) PumpDecoderOnce(kNormal); pop pending.” Current code still uses the legacy av_read_frame loop. If later someone wires PumpDecoderOnce(kNormal) from FillLoop without refactoring DecodeFrameToBuffer to pop from `pending_video_frames_`, video frames produced by PumpDecoderOnce would never be consumed and could leak or stall.

3. **Burst cap (4× target) under heavy cadence**  
   With 23.976→29.97 cadence, FillLoop decodes at ~24 fps while TickLoop can advance at ~30 fps. If consumption briefly outstrips decode, depth can drop; burst mode then allows refill up to 4× target. That is bounded but can increase memory and latency; worth monitoring if target depth or burst_cap are raised.

---

## Minimal fix (surgical) if INV-AUDIO-LIVENESS must hold

**Goal:** When the fill thread is parked due to video high-water, continue audio servicing without pushing video (DrainAudioOnly-style behavior).

**Option A — DrainAudioOnly in FillLoop when parked (recommended)**  
- In `VideoLookaheadBuffer::FillLoop`, when the thread would block in `space_cv_.wait`, **before** or **instead of** blocking, check whether the producer has a decoder and supports PumpDecoderOnce (e.g. optional interface or HasDecoder() and a new “DrainAudioOnly” on the producer).  
- If so, in a bounded loop (e.g. until audio buffer above a small threshold or PumpDecoderOnce returns kBackpressured/kEof), call `producer->PumpDecoderOnce(kAudioOnlyService)` and for each `GetPendingAudioFrame()` push to `audio_buffer_`.  
- Then re-evaluate the wait predicate (video depth may have dropped from pops, or audio depth may be sufficient).  
- **Scope:** FillLoop only; no change to TickLoop or DecodeFrameToBuffer. Producer must expose PumpDecoderOnce (already on ITickProducerDecoder) and GetPendingAudioFrame; TickProducer already has decoder and can forward.

**Option B — Wake fill thread for audio-only ticks**  
- Have the tick loop (or a timer) signal the fill thread when audio depth is below a threshold, so the fill thread wakes and runs. Then either (1) run DrainAudioOnly as in A, or (2) allow one decode (current behavior) and push video+audio. Option (2) does not satisfy “decode without advancing video”; option (1) is equivalent to A with wake triggered from outside.

**Recommendation:** Implement Option A in FillLoop so that when the predicate would return false (stay parked), the fill thread first attempts a bounded DrainAudioOnly pass, then re-checks the predicate. That satisfies “audio servicing at least once per equivalent interval” without redesign and uses the existing Phase 2 scaffolding.

---

## References

- `pkg/air/src/blockplan/FFmpegDecoderAdapter.cpp` — PumpDecoderOnce forward
- `pkg/air/src/blockplan/VideoLookaheadBuffer.cpp` — FillLoop, space_cv_.wait, burst/bootstrap
- `pkg/air/src/blockplan/PipelineManager.cpp` — TickLoop cadence repeat/advance, audio pop
- `pkg/air/src/blockplan/TickProducer.cpp` — TryGetFrame → DecodeFrameToBuffer
- `pkg/air/src/decode/FFmpegDecoder.cpp` — DecodeFrameToBuffer, ReadAndDecodeFrame, PumpDecoderOnce
- `pkg/air/include/retrovue/blockplan/ITickProducerDecoder.hpp` — PumpMode, PumpResult, PumpDecoderOnce
- `pkg/air/docs/contracts/semantics/INV-AUDIO-LIVENESS.md` — Contract definition
- `pkg/air/docs/PHASE2_DECODER_REFERENCE.cpp` — Intended refactor (ReadAndDecodeFrame using pending queue)
