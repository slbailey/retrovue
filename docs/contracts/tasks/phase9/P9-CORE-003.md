Task ID: P9-CORE-003
Rule ID: INV-P9-STEADY-008
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: MpegTSOutputSink
Task Type: IMPLEMENT
File(s) to Modify: pkg/air/src/renderer/MpegTSOutputSink.cpp
Owner: AIR
Blocked By: P9-CORE-001

Instructions:
- Add `silence_injection_disabled_` flag (bool, default false)
- Disable silence injection when steady-state entered
- When audio queue empty in steady-state, stall mux (video waits with audio)
- Log when silence injection disabled

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P9-STEADY-008):
Silence injection MUST be disabled when steady-state begins. Producer audio is the ONLY audio source. When audio queue is empty, the mux loop MUST stall (video waits with audio).

Implementation:

1. Add header field:
   ```cpp
   bool silence_injection_disabled_ = false;
   ```

2. In steady-state entry (P9-CORE-001 CheckSteadyStateEntry):
   ```cpp
   void CheckSteadyStateEntry() {
       if (!steady_state_entered_ && /* entry conditions */) {
           steady_state_entered_ = true;
           pcr_paced_active_ = true;
           silence_injection_disabled_ = true;
           LOG_INFO("INV-P9-STEADY-008: silence_injection_disabled=true");
       }
   }
   ```

3. In mux loop audio handling:
   ```cpp
   // In PCR-paced mode, if audio empty, stall
   if (pcr_paced_active_ && silence_injection_disabled_) {
       if (audio_buffer_->Empty()) {
           // Stall - do NOT emit video either
           LOG_DEBUG("INV-P9-STEADY-008: audio stall, video waiting");
           std::this_thread::sleep_for(1ms);
           continue;
       }
   }
   ```

4. FORBIDDEN in steady-state:
   - Silence injection
   - "Audio missing" heuristics
   - Fallback audio
   - Speculative silence
   - Any fabricated audio

Rationale:
Competing audio sources (producer + injected silence) cause PTS discontinuities. VLC drops/mutes audio, then video freezes. PCR becomes inconsistent.

Done Criteria:
`silence_injection_disabled_` set true on steady-state entry; mux stalls when audio empty (video waits); no silence frames emitted after entry.
