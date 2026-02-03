Task ID: P9-CORE-008
Rule ID: INV-P9-STEADY-005
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: FrameRingBuffer, ProgramOutput
Task Type: IMPLEMENT
File(s) to Modify: pkg/air/src/buffer/FrameRingBuffer.cpp, pkg/air/src/renderer/ProgramOutput.cpp
Owner: AIR
Blocked By: —

Instructions:
- Add equilibrium monitoring (depth in [1, 2N] where N = target depth)
- Track time spent outside equilibrium range
- Log warning if outside range for > 1 second (P9-OPT-001)
- Add violation counter for metrics

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P9-STEADY-005):
Buffer depth MUST oscillate around target (default: 3 frames). Depth MUST remain in range [1, 2N] during steady-state. Monotonic growth or drain to zero indicates a bug.

Implementation:

1. Add constants:
   ```cpp
   static constexpr int kTargetDepth = 3;
   static constexpr int kMinEquilibriumDepth = 1;
   static constexpr int kMaxEquilibriumDepth = 2 * kTargetDepth;  // 6
   static constexpr auto kEquilibriumSampleInterval =
       std::chrono::milliseconds(1000);
   ```

2. Add monitoring state:
   ```cpp
   std::chrono::steady_clock::time_point last_equilibrium_check_;
   std::chrono::steady_clock::time_point equilibrium_violation_start_;
   bool in_equilibrium_violation_ = false;
   int64_t equilibrium_violations_total_ = 0;
   ```

3. Add monitoring function:
   ```cpp
   void CheckEquilibrium() {
       auto now = std::chrono::steady_clock::now();

       if (now - last_equilibrium_check_ < kEquilibriumSampleInterval) {
           return;
       }
       last_equilibrium_check_ = now;

       auto depth = video_buffer_->Size();
       bool in_range = depth >= kMinEquilibriumDepth &&
                       depth <= kMaxEquilibriumDepth;

       if (!in_range) {
           if (!in_equilibrium_violation_) {
               in_equilibrium_violation_ = true;
               equilibrium_violation_start_ = now;
           } else {
               auto duration = now - equilibrium_violation_start_;
               if (duration > std::chrono::seconds(1)) {
                   equilibrium_violations_total_++;
                   LOG_WARNING("INV-P9-STEADY-005: "
                              "depth={} outside [{}..{}] for {}ms",
                              depth, kMinEquilibriumDepth,
                              kMaxEquilibriumDepth,
                              std::chrono::duration_cast<
                                  std::chrono::milliseconds>(duration)
                                  .count());
               }
           }
       } else {
           in_equilibrium_violation_ = false;
       }
   }
   ```

4. Call from render loop:
   ```cpp
   void RenderLoop() {
       while (!stop_) {
           CheckEquilibrium();
           // ... render
       }
   }
   ```

Rationale:
Buffer equilibrium is the steady-state health indicator. Sustained violations indicate producer-consumer mismatch that will eventually cause underrun or memory exhaustion.

Done Criteria:
Equilibrium monitored; violations logged after 1 second outside range; counter incremented; monotonic growth or drain detected.
