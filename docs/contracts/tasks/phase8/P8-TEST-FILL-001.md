Task ID: P8-TEST-FILL-001
Rule ID: INV-P8-CONTENT-DEFICIT-FILL-001
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: AIR (PlayoutEngine, ProgramOutput)
Task Type: TEST
File(s) to Modify: pkg/air/tests/playout/test_content_deficit.cpp
Owner: AIR
Blocked By: P8-FILL-002

Instructions:
- Add contract test: Pad emitted during content deficit
- Verify pad frames in output after EOF
- Verify TS cadence unchanged during deficit
- Verify pad frame format correct (black + silence)

---

Governing Principle (LAW-OUTPUT-LIVENESS):
> ProgramOutput never blocks; if no content → deterministic pad (black + silence).

Rule Definition (INV-P8-CONTENT-DEFICIT-FILL-001):
Gap between EOF and boundary MUST be filled with pad at real-time cadence. Output liveness preserved.

Test Cases:

1. Test pad emitted after EOF:
   - Setup: EOF at T+8s; boundary at T+10s
   - Action: Examine output frames from T+8s to T+10s
   - Expected: Pad frames present; frame count = 2s × fps

2. Test pad frame format:
   - Setup: Same as above
   - Action: Inspect pad frame content
   - Expected: Video is black; audio is silence; house format

3. Test pad has valid CT:
   - Setup: Same as above
   - Action: Check CT on pad frames
   - Expected: CT monotonic; CT advances at real-time rate

4. Test CONTENT_DEFICIT_FILL_START logged:
   - Setup: EOF before boundary
   - Action: Check logs
   - Expected: Log contains segment ID, CT, boundary_ct, gap_ms

5. Test deficit metric recorded:
   - Setup: EOF before boundary
   - Action: Check metrics
   - Expected: `retrovue_air_content_deficit_total` incremented

Done Criteria:
Pad frames in output after EOF; TS cadence unchanged; pad format correct; logs and metrics present.
