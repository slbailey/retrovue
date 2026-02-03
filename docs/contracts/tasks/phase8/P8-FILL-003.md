Task ID: P8-FILL-003
Rule ID: INV-P8-CONTENT-DEFICIT-FILL-001
Governing Law: LAW-SWITCHING
Subsystem: AIR (PlayoutEngine)
Task Type: CORE
File(s) to Modify: pkg/air/src/playout/playout_engine.cpp
Owner: AIR
Blocked By: P8-FILL-002

Instructions:
- End content deficit on boundary switch
- Clear deficit state when switch executes
- Log CONTENT_DEFICIT_FILL_END with duration
- Record deficit duration metric

---

Governing Principle (LAW-SWITCHING):
> No gaps, no PTS regression, no silence during switches.

Rule Definition (INV-P8-CONTENT-DEFICIT-FILL-001):
Content deficit fill ends when the scheduled boundary switch occurs. The next segment's content replaces pad; no gap in output.

Implementation Notes:

1. In ExecuteSwitch (or equivalent switch handler):
   ```cpp
   void PlayoutEngine::ExecuteSwitch() {
       if (_content_deficit_active) {
           EndContentDeficitFill();
       }

       // Normal switch execution...
       _live_producer = _preview_producer;
       _preview_producer = nullptr;
       // ...
   }
   ```

2. EndContentDeficitFill:
   ```cpp
   void PlayoutEngine::EndContentDeficitFill() {
       int64_t now_ct = _timeline_controller->GetCurrentCT();
       int64_t duration_ms = (now_ct - _deficit_start_ct) / 1000;

       LOG_INFO("CONTENT_DEFICIT_FILL_END segment={} duration_ms={}",
                _current_segment_id, duration_ms);

       // Metric: deficit duration
       _metrics->RecordHistogram("retrovue_air_content_deficit_duration_ms", duration_ms);

       _content_deficit_active = false;
       _deficit_start_ct = 0;
       _deficit_boundary_ct = 0;
   }
   ```

3. After switch, content from next segment flows; pad stops

4. No gap at switch point (LAW-SWITCHING): last pad frame → first content frame

Observable Proof:
- Log: `CONTENT_DEFICIT_FILL_END segment={id} duration_ms={d}`
- Metric: deficit duration recorded
- Content from next segment after boundary
- No gap between pad and content

Done Criteria:
Content deficit ends on switch; CONTENT_DEFICIT_FILL_END logged; duration metric recorded; seamless transition to next segment.

**Done:** 2026-02-02. EndContentDeficitFill(state): if content_deficit_active, log CONTENT_DEFICIT_FILL_END segment=... duration_ms=..., clear state and target_boundary_time_ms_. Called at start of ExecuteSwitchAtDeadline, in SpawnSwitchWatcher before swap, and in direct switch path before swap.
