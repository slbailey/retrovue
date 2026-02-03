Task ID: P8-FILL-001
Rule ID: INV-P8-CONTENT-DEFICIT-FILL-001
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: AIR (PlayoutEngine)
Task Type: CORE
File(s) to Modify: pkg/air/src/playout/playout_engine.cpp, pkg/air/include/playout/playout_engine.h
Owner: AIR
Blocked By: P8-EOF-002

Instructions:
- Implement content deficit detection in PlayoutEngine
- Detect when live producer EOF before scheduled boundary
- Track deficit state: start CT, boundary CT, gap duration
- Log CONTENT_DEFICIT_FILL_START

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P8-CONTENT-DEFICIT-FILL-001):
If live decoder reaches EOF before the scheduled segment end time, the gap (content deficit) MUST be filled with pad at real-time cadence until the boundary. Output liveness and TS cadence are preserved.

Implementation Notes:

1. Add state fields to PlayoutEngine:
   ```cpp
   bool _content_deficit_active = false;
   int64_t _deficit_start_ct = 0;
   int64_t _deficit_boundary_ct = 0;
   ```

2. In StartContentDeficitFill (called from OnLiveProducerEOF):
   ```cpp
   void PlayoutEngine::StartContentDeficitFill(const std::string& segment_id,
                                                int64_t eof_ct,
                                                int64_t boundary_ct) {
       _content_deficit_active = true;
       _deficit_start_ct = eof_ct;
       _deficit_boundary_ct = boundary_ct;
       int64_t gap_ms = (boundary_ct - eof_ct) / 1000; // CT in microseconds

       LOG_INFO("CONTENT_DEFICIT_FILL_START segment={} ct={} boundary_ct={} gap_ms={}",
                segment_id, eof_ct, boundary_ct, gap_ms);

       // Metric: content deficit triggered
       _metrics->IncrementCounter("retrovue_air_content_deficit_total");
   }
   ```

3. Deficit active flag used by ProgramOutput to emit pad (P8-FILL-002)

Observable Proof:
- Log: `CONTENT_DEFICIT_FILL_START segment={id} ct={ct} boundary_ct={b} gap_ms={g}`
- `_content_deficit_active = true` during deficit
- Metric incremented

Done Criteria:
Content deficit detected on live EOF before boundary; state tracked; CONTENT_DEFICIT_FILL_START logged; metric recorded.

**Done:** 2026-02-02. PlayoutInstance: content_deficit_active_, deficit_start_ct_us_, deficit_boundary_ct_us_, deficit_segment_id_, target_boundary_time_ms_. OnLiveProducerEOF: lock, compute boundary_ct from target_boundary_time_ms_ and epoch; if ct_at_eof < boundary_ct call StartContentDeficitFill. StartContentDeficitFill sets state and logs CONTENT_DEFICIT_FILL_START. Metric left to telemetry layer.
