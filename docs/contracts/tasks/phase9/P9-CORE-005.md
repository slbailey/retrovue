Task ID: P9-CORE-005
Rule ID: INV-P9-STEADY-002
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: FileProducer
Task Type: IMPLEMENT
File(s) to Modify: pkg/air/src/producers/file/FileProducer.cpp
Owner: AIR
Blocked By: —

Instructions:
- Implement slot-based decode gating
- Block at capacity: when `buffer.Size() >= buffer.Capacity()`
- Resume on 1 slot free: when `buffer.Size() < buffer.Capacity()`
- NO hysteresis (no low-water mark)
- Gate at decode level, NOT at push level

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P9-STEADY-002):
After output attach, producers MUST NOT free-run (decode as fast as possible). Producers MUST decode only when downstream capacity exists (slot-based gating). The producer thread MUST yield when the buffer is at capacity.

Implementation:

1. Add slot-based gating in decode loop:
   ```cpp
   bool WaitForDecodeSlot() {
       while (video_buffer_->Size() >= video_buffer_->Capacity()) {
           if (stop_requested_ || write_barrier_active_) {
               return false;
           }
           // Block at capacity
           std::this_thread::sleep_for(std::chrono::milliseconds(1));
       }
       // Slot available - resume immediately
       return true;
   }
   ```

2. Use gate BEFORE decode, not after:
   ```cpp
   void DecodeLoop() {
       while (!stop_requested_) {
           // Gate BEFORE work - CORRECT
           if (!WaitForDecodeSlot()) break;

           // Now safe to read and decode
           AVPacket* pkt = av_read_frame(...);
           AVFrame* frame = Decode(pkt);
           Push(frame);  // Guaranteed to succeed - we have a slot
       }
   }
   ```

3. FORBIDDEN patterns:
   ```cpp
   // WRONG: Hysteresis with low-water mark
   while (buffer.Size() > LOW_WATER_MARK) { wait; }

   // WRONG: Gate at push level (causes A/V desync)
   AVPacket* pkt = av_read_frame(...);  // reads unconditionally
   AVFrame* frame = Decode(pkt);
   WaitForPushSlot();  // audio ran ahead!
   Push(frame);
   ```

4. Add logging:
   ```cpp
   LOG_DEBUG("INV-P9-STEADY-002: blocked at capacity depth={}",
             video_buffer_->Size());
   LOG_DEBUG("INV-P9-STEADY-002: released depth={}",
             video_buffer_->Size());
   ```

Rationale:
Hysteresis gating (block at high-water, resume at low-water) creates sawtooth pattern. Slot-based gating keeps producer-consumer in lockstep when buffer is full.

Done Criteria:
Producer blocks at capacity (`Size() >= Capacity()`); resumes when exactly 1 slot frees (`Size() < Capacity()`); no hysteresis; gate at decode level.
