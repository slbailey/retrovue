Task ID: P8-PLAN-003
Rule ID: INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001
Governing Law: LAW-AUTHORITY-HIERARCHY
Subsystem: AIR (FileProducer, PlayoutEngine)
Task Type: CORE
File(s) to Modify: pkg/air/src/playout/file_producer.cpp, pkg/air/src/playout/playout_engine.cpp
Owner: AIR
Blocked By: P8-PLAN-001

Instructions:
- Handle long content (decoder has more frames than planned)
- Stop delivery at planned_frame_count regardless of decoder state
- Log CONTENT_TRUNCATED with excess frame count
- Ensure boundary timing remains authoritative

---

Governing Principle (LAW-AUTHORITY-HIERARCHY):
> Clock authority supersedes frame completion for switch execution.

Rule Definition (INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001):
If content is longer than planned frame_count, segment end time still governs when the switch occurs (schedule is authoritative). Excess content is truncated, not played.

Implementation Notes:

1. In FileProducer frame delivery:
   ```cpp
   if (_frames_delivered >= _planned_frame_count) {
       // Do not deliver more frames than planned
       // Boundary will trigger switch; content truncated
       if (!_truncation_logged) {
           int64_t excess = decoder_frames_available - _planned_frame_count;
           LOG_WARN("CONTENT_TRUNCATED segment={} planned={} available={} excess_frames={}",
                    _segment_id, _planned_frame_count, decoder_frames_available, excess);
           _truncation_logged = true;
       }
       return; // No more frames from this segment
   }
   ```

2. Truncation happens at frame_count, not at boundary time

3. Schedule remains authoritative for boundary timing

4. The gap (if any) between last frame and boundary is filled with pad

Observable Proof:
- Log: `CONTENT_TRUNCATED segment={id} planned={p} available={a} excess_frames={n}`
- No frames delivered after planned_frame_count
- Boundary occurs at scheduled time

Done Criteria:
Long content truncated at frame_count; CONTENT_TRUNCATED logged; boundary timing unchanged; schedule authoritative.

**Done:** 2026-02-02. FileProducer: added truncation_logged_; main loop waits when frames_delivered >= planned_frame_count (emit segment_complete truncated_at_boundary); before Push in real and stub paths refuse delivery and log CONTENT_TRUNCATED once; reset truncation_logged_ in start/InitializeDecoder/ResetDecoder.
