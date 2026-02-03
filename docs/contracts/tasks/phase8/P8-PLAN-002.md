Task ID: P8-PLAN-002
Rule ID: INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001
Governing Law: LAW-AUTHORITY-HIERARCHY
Subsystem: AIR (FileProducer)
Task Type: CORE
File(s) to Modify: pkg/air/src/playout/file_producer.cpp
Owner: AIR
Blocked By: P8-PLAN-001

Instructions:
- Detect early EOF (decoder exhausted before planned frame_count)
- Compare _frames_delivered to _planned_frame_count on decoder EOF
- Log EARLY_EOF with deficit frames count
- Signal EOF to PlayoutEngine (P8-EOF-001)

---

Governing Principle (LAW-AUTHORITY-HIERARCHY):
> Clock authority supersedes frame completion for switch execution.

Rule Definition (INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001):
If actual content is shorter than planned frame_count, content deficit fill applies (INV-P8-CONTENT-DEFICIT-FILL-001).

Implementation Notes:

1. On decoder EOF detection:
   ```cpp
   if (_frames_delivered < _planned_frame_count) {
       int64_t deficit = _planned_frame_count - _frames_delivered;
       LOG_INFO("EARLY_EOF segment={} planned={} delivered={} deficit_frames={}",
                _segment_id, _planned_frame_count, _frames_delivered, deficit);
       // Signal early EOF to PlayoutEngine
       _engine->OnProducerEarlyEOF(_segment_id, _frames_delivered, _planned_frame_count);
   }
   ```

2. Early EOF is distinct from normal EOF (content matches plan)

3. Deficit frames count feeds into content deficit fill timing

Observable Proof:
- Log: `EARLY_EOF segment={id} planned={p} delivered={d} deficit_frames={n}`
- Early EOF signaled to PlayoutEngine
- Deficit count accurate

Done Criteria:
Early EOF detected when frames_delivered < planned_frame_count; EARLY_EOF logged with correct counts; PlayoutEngine notified.

**Done:** 2026-02-02. FileProducer: on decoder EOF, if planned_frame_count >= 0 and frames_delivered < planned_frame_count, log EARLY_EOF (segment=asset_uri, planned, delivered, deficit_frames) and EmitEvent("early_eof", ...). PlayoutEngine continues to observe IsEOF(); full P8-EOF-001 callback wiring is separate.
