Task ID: P8-TEST-FILL-002
Rule ID: INV-P8-CONTENT-DEFICIT-FILL-001
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: AIR (MpegTSOutputSink)
Task Type: TEST
File(s) to Modify: pkg/air/tests/playout/test_content_deficit.cpp
Owner: AIR
Blocked By: P8-FILL-002

Instructions:
- Add contract test: TS emission continues during content deficit
- Verify TS packet rate stable across deficit
- Verify no TS gaps during deficit
- Verify HTTP connection would survive deficit

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P8-CONTENT-DEFICIT-FILL-001):
Output liveness and TS cadence are preserved; the mux never stalls.

Test Cases:

1. Test TS packet rate stable:
   - Setup: Measure TS packet rate during content; EOF occurs; measure during deficit
   - Action: Compare rates
   - Expected: Rates within tolerance (±5%)

2. Test no TS gaps:
   - Setup: EOF at T+8s; boundary at T+10s
   - Action: Analyze TS stream for gaps
   - Expected: Continuous TS packets; no gaps > 100ms

3. Test PCR continuity:
   - Setup: Same as above
   - Action: Verify PCR values in TS
   - Expected: PCR monotonic; no discontinuity flag

4. Test PES continuity:
   - Setup: Same as above
   - Action: Verify continuity counters
   - Expected: No unexpected discontinuities

5. Test HTTP timeout would not occur:
   - Setup: Typical HTTP timeout = 30s; deficit = 2s
   - Action: Verify data flow during deficit
   - Expected: TS bytes flow continuously; no timeout

6. Test sink receives frames during deficit:
   - Setup: Mock sink; EOF before boundary
   - Action: Count frames received during deficit
   - Expected: Frames received at target_fps

Done Criteria:
TS packet rate stable; no gaps; PCR/PES continuity maintained; HTTP would survive.
