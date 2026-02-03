Task ID: P8-TEST-FILL-003
Rule ID: INV-P8-CONTENT-DEFICIT-FILL-001
Governing Law: LAW-SWITCHING
Subsystem: AIR (PlayoutEngine)
Task Type: TEST
File(s) to Modify: pkg/air/tests/playout/test_content_deficit.cpp
Owner: AIR
Blocked By: P8-FILL-003

Instructions:
- Add contract test: Switch terminates content deficit fill
- Verify content from next segment after boundary
- Verify CONTENT_DEFICIT_FILL_END logged
- Verify seamless transition (no gap)

---

Governing Principle (LAW-SWITCHING):
> No gaps, no PTS regression, no silence during switches.

Rule Definition (INV-P8-CONTENT-DEFICIT-FILL-001):
Content deficit fill ends when the scheduled boundary switch occurs.

Test Cases:

1. Test deficit ends on switch:
   - Setup: EOF at T+8s; boundary at T+10s; preview loaded
   - Action: Execute switch at T+10s
   - Expected: `_content_deficit_active = false` after switch

2. Test CONTENT_DEFICIT_FILL_END logged:
   - Setup: Same as above
   - Action: Check logs after switch
   - Expected: Log contains segment ID, duration_ms

3. Test duration metric recorded:
   - Setup: Same as above
   - Action: Check metrics
   - Expected: `retrovue_air_content_deficit_duration_ms` histogram updated

4. Test content from next segment:
   - Setup: Same as above
   - Action: Examine frames after T+10s
   - Expected: Content frames from preview segment; not pad

5. Test seamless transition:
   - Setup: Same as above
   - Action: Analyze frame sequence at boundary
   - Expected: Last pad frame → first content frame; no gap

6. Test PTS continuity at switch:
   - Setup: Same as above
   - Action: Verify PTS across boundary
   - Expected: PTS advances; no regression

7. Test deficit state cleared:
   - Setup: Same as above
   - Action: Check deficit state after switch
   - Expected: All deficit state reset (active=false, start_ct=0)

Done Criteria:
Switch ends deficit; CONTENT_DEFICIT_FILL_END logged; content from next segment; seamless transition.
