Task ID: P9-CORE-001
Rule ID: INV-P9-STEADY-001
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: MpegTSOutputSink
Task Type: IMPLEMENT
File(s) to Modify: pkg/air/src/renderer/MpegTSOutputSink.cpp, pkg/air/include/retrovue/renderer/MpegTSOutputSink.h
Owner: AIR
Blocked By: —

Instructions:
- Add `steady_state_entered_` flag (bool, default false)
- Add `pcr_paced_active_` flag (bool, default false)
- Add detection logic for steady-state entry conditions
- Entry conditions: sink attached AND buffer depth ≥ kSteadyStateMinDepth AND bootstrap complete
- Set flags when conditions met
- Log `INV-P9-STEADY-STATE: entered` on entry

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P9-STEADY-001):
After output attach, the mux loop MUST be the sole pacing authority. Frame emission occurs when the output clock (PCR-paced wall clock) reaches frame CT, not when frames become available.

Implementation:

1. Add header fields:
   ```cpp
   bool steady_state_entered_ = false;
   bool pcr_paced_active_ = false;
   ```

2. Add steady-state entry detection (in mux loop or attach path):
   ```cpp
   void CheckSteadyStateEntry() {
       if (!steady_state_entered_ &&
           sink_attached_ &&
           video_buffer_->Size() >= kSteadyStateMinDepth &&
           bootstrap_complete_) {
           steady_state_entered_ = true;
           pcr_paced_active_ = true;
           LOG_INFO("INV-P9-STEADY-STATE: entered channel={} depth={}",
                    channel_id_, video_buffer_->Size());
       }
   }
   ```

3. Add constants:
   ```cpp
   static constexpr int kSteadyStateMinDepth = 1;
   ```

Rationale:
Steady-state entry detection gates the transition from bootstrap (producer-driven) to steady-state (output-driven). Without explicit detection, there is no transition point for enabling PCR-paced mux.

Done Criteria:
Flags exist and are properly initialized; steady-state entry logged when conditions met; no behavioral change to mux loop yet (this task is detection scaffolding).
