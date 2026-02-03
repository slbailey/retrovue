Task ID: P8-TEST-EOF-002
Rule ID: INV-P8-SEGMENT-EOF-DISTINCT-001
Governing Law: LAW-SWITCHING
Subsystem: AIR (PlayoutEngine)
Task Type: TEST
File(s) to Modify: pkg/air/tests/playout/test_content_deficit.cpp
Owner: AIR
Blocked By: P8-EOF-002

Instructions:
- Add contract test: EOF does not trigger switch
- Verify switch occurs at boundary time, not EOF time
- Verify boundary state unchanged by EOF
- Verify preview segment not activated early

---

Governing Principle (LAW-SWITCHING):
> Transitions MUST complete within one video frame duration of scheduled absolute boundary time.

Rule Definition (INV-P8-SEGMENT-EOF-DISTINCT-001):
EOF is an event within the segment; boundary is the scheduled instant at which the switch occurs.

Test Cases:

1. Test switch at boundary, not EOF:
   - Setup: Boundary at T+10s; EOF at T+8s; preview loaded
   - Action: EOF occurs at T+8s
   - Expected: No switch at T+8s; switch at T+10s (±1 frame)

2. Test boundary state unchanged by EOF:
   - Setup: Boundary scheduled; EOF before boundary
   - Action: Query boundary state after EOF
   - Expected: State is SWITCH_SCHEDULED (or equivalent), not LIVE

3. Test preview not activated early:
   - Setup: Preview segment loaded; EOF at T+8s
   - Action: Check live producer at T+9s
   - Expected: Live producer unchanged; preview waiting

4. Test switch timing precision:
   - Setup: Boundary at T+10.000s; EOF at T+8s
   - Action: Measure actual switch time
   - Expected: Switch at T+10.000s ±33ms (one frame at 30fps)

5. Test no double switch:
   - Setup: EOF at T+8s; boundary at T+10s
   - Action: Monitor switch events
   - Expected: Exactly one switch (at boundary)

Done Criteria:
Switch at boundary time, not EOF time; boundary state unchanged by EOF; preview not activated early.
