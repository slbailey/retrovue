Task ID: P8-FILL-002
Rule ID: INV-P8-CONTENT-DEFICIT-FILL-001
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: AIR (ProgramOutput)
Task Type: CORE
File(s) to Modify: pkg/air/src/playout/program_output.cpp
Owner: AIR
Blocked By: P8-FILL-001

Instructions:
- Emit pad frames during content deficit period
- Maintain real-time frame cadence (target_fps)
- Preserve TS emission cadence (no HTTP timeout)
- Pad frames have valid CT; mux never stalls

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P8-CONTENT-DEFICIT-FILL-001):
Gap between EOF and boundary MUST be filled with pad at real-time cadence. Output liveness and TS cadence are preserved; the mux never stalls.

Implementation Notes:

1. In ProgramOutput render loop, check deficit state:
   ```cpp
   void ProgramOutput::EmitFrame() {
       Frame frame = GetNextFrame();

       if (frame.IsEmpty() && _engine->IsContentDeficitActive()) {
           // Content deficit: emit pad at current CT
           frame = CreatePadFrame(_timeline_controller->GetCurrentCT());
           LOG_DEBUG("DEFICIT_PAD_FRAME ct={}", frame.ct);
       }

       // Emit frame (content or pad) to encoder
       _encoder_pipeline->EnqueueFrame(frame);
   }
   ```

2. Pad frame creation:
   - Black video (solid frame at house resolution)
   - Silence audio (house format, zero samples)
   - Valid CT from TimelineController

3. TS emission continues at configured rate
   - MpegTSOutputSink receives frames at target_fps
   - No gaps in TS packets
   - HTTP connection maintained

4. This is the existing pad mechanism; deficit flag gates it during normal playback

Observable Proof:
- TS packets continue at cadence during deficit
- Pad frames visible in output (black + silence)
- HTTP 200 maintained; no timeout
- Debug log: `DEFICIT_PAD_FRAME ct={ct}`

Done Criteria:
Pad emitted during content deficit; frame cadence maintained; TS emission continues; mux never stalls; HTTP connection survives.

**Done:** 2026-02-02. ProgramOutput: SetContentDeficitActiveFlag(std::atomic<bool>*); when buffer empty and content_deficit_active_ptr_->load() && first_real_frame_emitted_, goto emit_pad_frame (no freeze window). DEFICIT_PAD_FRAME ct=... logged every 30th pad during deficit. PlayoutEngine wires &state->content_deficit_active_ in StartChannel.
