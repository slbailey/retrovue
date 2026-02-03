Task ID: P9-CORE-002
Rule ID: INV-P9-STEADY-001
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: MpegTSOutputSink
Task Type: IMPLEMENT
File(s) to Modify: pkg/air/src/renderer/MpegTSOutputSink.cpp
Owner: AIR
Blocked By: P9-CORE-001

Instructions:
- Modify mux loop to wait for wall clock to reach frame CT before dequeue
- When `pcr_paced_active_` is true, peek frame CT and wait
- Emit exactly one video frame per pacing period
- Emit all audio with CT ≤ video CT after video

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P9-STEADY-001):
After output attach, the mux loop MUST be the sole pacing authority. Frame emission occurs when the output clock (PCR-paced wall clock) reaches frame CT, not when frames become available.

Implementation:

1. Modify mux loop when `pcr_paced_active_`:
   ```cpp
   void MuxLoop() {
       while (!stop_requested_) {
           if (pcr_paced_active_) {
               // PCR-paced: wait for CT
               auto* frame = video_buffer_->Peek();
               if (!frame) {
                   // Stall until frame available
                   std::this_thread::sleep_for(1ms);
                   continue;
               }

               auto now = GetWallClockUs();
               auto wait_time = frame->ct_us - now;

               if (wait_time > 0) {
                   std::this_thread::sleep_for(
                       std::chrono::microseconds(wait_time));
               }

               // Dequeue and encode exactly one video frame
               auto video_frame = video_buffer_->Pop();
               EncodeVideoFrame(video_frame);

               // Encode all audio with CT ≤ video CT
               while (auto* audio = audio_buffer_->Peek()) {
                   if (audio->pts_us > video_frame.ct_us) break;
                   auto audio_frame = audio_buffer_->Pop();
                   EncodeAudioFrame(audio_frame);
               }
           } else {
               // Bootstrap mode: existing behavior
               RunBootstrapMuxLoop();
           }
       }
   }
   ```

2. FORBIDDEN patterns:
   - Draining loops ("while queue not empty → emit")
   - Burst writes (emit as fast as possible)
   - Adaptive speed-up / slow-down
   - Dropping frames to catch up

Rationale:
PCR-paced mux ensures smooth, steady output at real-time rate. Availability-driven mux causes buffer sawtooth oscillation and VLC stutter.

Done Criteria:
Mux waits for `wall_clock >= frame.ct` before dequeue when `pcr_paced_active_`; no burst consumption; frame rate matches target FPS.
