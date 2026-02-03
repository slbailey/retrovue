Task ID: P9-CORE-006
Rule ID: INV-P9-STEADY-003
Governing Law: LAW-AUDIO-FORMAT
Subsystem: FileProducer
Task Type: IMPLEMENT
File(s) to Modify: pkg/air/src/producers/file/FileProducer.cpp
Owner: AIR
Blocked By: P9-CORE-005

Instructions:
- Implement symmetric A/V backpressure
- When video blocked at decode gate, audio MUST also block
- When audio blocked, video MUST also block
- Neither stream may run ahead by more than 1 frame duration (33ms at 30fps)
- Use shared blocking flag or coordinated gate

---

Governing Principle (LAW-AUDIO-FORMAT):
> Channel defines house format; all audio normalized before OutputBus.

Rule Definition (INV-P9-STEADY-003):
Audio and video MUST advance together. Neither stream may run ahead of the other by more than one frame duration (33ms at 30fps). When backpressure is applied, both streams MUST be throttled symmetrically.

Implementation:

1. Add shared blocking flag:
   ```cpp
   std::atomic<bool> av_blocked_{false};
   std::mutex av_gate_mutex_;
   std::condition_variable av_gate_cv_;
   ```

2. Implement coordinated gate:
   ```cpp
   bool WaitForDecodeSlotSymmetric() {
       std::unique_lock<std::mutex> lock(av_gate_mutex_);

       while (video_buffer_->Size() >= video_buffer_->Capacity() ||
              audio_buffer_->Size() >= audio_buffer_->Capacity()) {

           if (stop_requested_ || write_barrier_active_) {
               return false;
           }

           av_blocked_ = true;
           av_gate_cv_.wait_for(lock, std::chrono::milliseconds(1));
       }

       av_blocked_ = false;
       return true;
   }
   ```

3. Apply gate to BOTH audio and video decode paths:
   ```cpp
   void DecodeLoop() {
       while (!stop_requested_) {
           // Symmetric gate - blocks both streams together
           if (!WaitForDecodeSlotSymmetric()) break;

           // Decode video
           if (HasVideoPacket()) {
               auto frame = DecodeVideo();
               PushVideo(frame);
           }

           // Decode audio (same iteration, same gate)
           if (HasAudioPacket()) {
               auto frame = DecodeAudio();
               PushAudio(frame);
           }
       }
   }
   ```

4. Ensure A/V delta stays bounded:
   ```cpp
   // Invariant: |audio_ct - video_ct| <= 1 frame duration
   // Enforced by symmetric gating - both wait together
   ```

5. FORBIDDEN patterns:
   - Video blocks while audio continues decoding
   - Audio blocks while video continues
   - Either stream drops frames due to asymmetric backpressure

Rationale:
Asymmetric backpressure causes A/V desync. If video blocks but audio continues, audio runs ahead. When video resumes, A/V sync is broken.

Done Criteria:
When video blocked, audio also blocks (and vice versa); A/V delta ≤ 1 frame duration at all times; both streams resume together when capacity available.
