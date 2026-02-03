Task ID: P9-CORE-007
Rule ID: INV-P9-STEADY-004
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: ProgramOutput
Task Type: IMPLEMENT
File(s) to Modify: pkg/air/src/renderer/ProgramOutput.cpp
Owner: AIR
Blocked By: —

Instructions:
- Add `pad_while_depth_high_` counter (int64_t)
- When emitting pad frame, check buffer depth
- If depth ≥ 10 (kPadViolationDepthThreshold), log violation and increment counter
- This indicates a flow control or CT tracking bug, not starvation

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P9-STEADY-004):
Pad frame emission while buffer depth ≥ 10 is a CONTRACT VIOLATION. If frames exist in the buffer but are not being consumed, this indicates a flow control or CT tracking bug, not content starvation.

Implementation:

1. Add header field:
   ```cpp
   int64_t pad_while_depth_high_ = 0;
   static constexpr int kPadViolationDepthThreshold = 10;
   ```

2. Add violation check in pad emission path:
   ```cpp
   void EmitPadFrame() {
       auto depth = video_buffer_->Size();

       if (depth >= kPadViolationDepthThreshold) {
           pad_while_depth_high_++;
           LOG_ERROR("INV-P9-STEADY-004 VIOLATION: "
                     "Pad emitted while depth={} >= {} "
                     "violations_total={}",
                     depth, kPadViolationDepthThreshold,
                     pad_while_depth_high_);
       }

       // Emit pad as usual
       EmitBlackSilenceFrame();
   }
   ```

3. Expose counter for metrics:
   ```cpp
   int64_t GetPadWhileDepthHighCount() const {
       return pad_while_depth_high_;
   }
   ```

4. Add metric export (P9-OPT-002):
   - `retrovue_pad_while_depth_high_total` → pad_while_depth_high_

Rationale:
If buffer has frames but output is emitting pad, something is fundamentally broken in the flow control or CT tracking. This is not a starvation condition - frames exist but are not being consumed. The violation log makes this bug visible.

Done Criteria:
Violation logged when pad emitted with depth ≥ 10; counter incremented; violation distinguishable from legitimate starvation.
