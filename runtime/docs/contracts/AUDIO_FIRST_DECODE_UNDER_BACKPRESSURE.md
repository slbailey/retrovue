# Audio-First Decode Under Backpressure (INV-AUDIO-LIVENESS-001)

**Status:** Implemented  
**Owner:** VideoLookaheadBuffer (fill loop), PipelineManager (metrics)

---

## Problem

When playing mixed-FPS content (e.g. 60fps ads into 29.97 output), the video lookahead buffer can reach capacity while the tick loop continues to consume one frame per tick. The fill thread was **gated solely by video depth**: when `depth >= target_depth_frames_` it transitioned to PARKED and waited on `space_cv_`. While parked, it performed **no decode**, so **no audio** was produced. The tick loop kept popping one tick of audio per tick, so the audio buffer drained and we hit **AUDIO_UNDERFLOW_SILENCE** even though the video buffer was full. This violated **INV-AUDIO-LIVENESS-001** (audio servicing must not be prevented by video queue backpressure) and **INV-P10-PIPELINE-FLOW-CONTROL** (symmetric backpressure; we must not starve audio when video is backpressured).

---

## Gating Change (Summary)

1. **FILLING path**  
   When `depth >= target_depth_frames_`, we now check **audio** before deciding to park:
   - If `audio_buffer->DepthMs() < audio_buffer->LowWaterMs()`: do **not** park; set `skip_wait = true` and `drop_video_this_cycle = true`. The fill thread continues to decode; we still push decoded audio to `AudioLookaheadBuffer`, but we **do not** enqueue the video frame (we drop it so the video buffer does not grow).
   - Otherwise: transition to PARKED as before (log PARK with `video_depth_frames` and `audio_depth_ms`).

2. **PARKED path (condvar)**  
   - We use `space_cv_.wait_for(lock, kParkWaitTimeout, predicate)` (e.g. 20ms) so the predicate is re-evaluated periodically. That allows us to wake when **audio** drops below low-water even if no one has called `TryPopFrame()` (no video slot freed).
   - In the predicate we added: if `depth >= target_depth_frames_` and `audio_buffer->DepthMs() < audio_buffer->LowWaterMs()`, return true (wake) and set `steady_filling_ = true`.
   - After waking from the wait, if we woke due to “audio low while video full”, we set `drop_video_this_cycle = true` so this decode cycle only pushes audio and drops the video frame.

3. **Push logic**  
   If `drop_video_this_cycle` we increment the diagnostic counter `decode_continued_for_audio_while_video_full` and **do not** push the video frame; we only push audio (already done earlier in the loop). Video buffer depth and memory stay bounded.

---

## Why This Enforces INV-AUDIO-LIVENESS-001

- **INV-AUDIO-LIVENESS-001** requires: *“Video saturation may block video enqueues but MUST NOT halt: demux servicing for audio packets, audio decoder draining, audio frame production.”*
- Before the change: when the video buffer was at capacity we parked and did no decode → no demux, no audio decode, no audio production → **violation**.
- After the change: when the video buffer is at capacity we still **continue decode** whenever audio is below low-water. We run the same decode path (TryGetFrame → demux/decode/resample) and push **audio** to `AudioLookaheadBuffer`; we only **omit** enqueueing the video frame. So demux, audio decoder draining, and audio frame production are **not** halted by video backpressure. Video enqueues are still blocked (we drop the frame), which is allowed by the invariant.

One-output-frame-per-tick behavior is unchanged: the tick loop still pops one video frame and one tick of audio per tick; we do not add catch-up bursts.

---

## Diagnostics (No New Invariants)

- **Counters (VideoLookaheadBuffer):**
  - `decode_continued_for_audio_while_video_full`: number of decode cycles where we continued for audio and dropped the video frame.
  - `decode_parked_video_full_audio_low`: reserved for “parked with video full and audio low”; with the fix this should remain 0 (we never park in that state).
- **Logs:** PARK and UNPARK transitions log `video_depth_frames` and `audio_depth_ms`.
- **Metrics:** PipelineMetrics snapshot includes the two counters for heartbeat/telemetry.

---

## Contract Test

`LookaheadContract.INV_AUDIO_LIVENESS_001_AudioServicedWhenVideoFull`:  
Video buffer is filled to target; consumer pops **only** audio at output tick rate (no video pop). Without audio-first gating the fill thread would stay parked and audio would underflow. The test asserts no audio underflow and that `DecodeContinuedForAudioWhileVideoFull() > 0`.
