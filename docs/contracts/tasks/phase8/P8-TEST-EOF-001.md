Task ID: P8-TEST-EOF-001
Rule ID: INV-P8-SEGMENT-EOF-DISTINCT-001
Governing Law: LAW-AUTHORITY-HIERARCHY
Subsystem: AIR (FileProducer, PlayoutEngine, TimelineController)
Task Type: TEST
File(s) to Modify: pkg/air/tests/playout/test_content_deficit.cpp
Owner: AIR
Blocked By: P8-EOF-003

Instructions:
- Add contract test: EOF signaled before boundary, CT continues
- Verify EOF event logged
- Verify CT remains monotonic after EOF
- Verify no boundary advance on EOF

---

Governing Principle (LAW-AUTHORITY-HIERARCHY):
> Clock authority supersedes frame completion for switch execution.

Rule Definition (INV-P8-SEGMENT-EOF-DISTINCT-001):
EOF is an event within the segment; boundary is the scheduled instant. CT continues advancing after EOF.

Test Cases:

1. Test EOF signaled at correct CT:
   - Setup: Segment with 100 frames planned; decoder has only 80 frames
   - Action: Play until decoder EOF
   - Expected: DECODER_EOF logged at frame 80; CT at EOF correct

2. Test CT continues after EOF:
   - Setup: Same as above
   - Action: Advance time past EOF
   - Expected: CT continues advancing; CT at boundary > CT at EOF

3. Test CT monotonicity preserved:
   - Setup: Same as above
   - Action: Sample CT before EOF, at EOF, after EOF, at boundary
   - Expected: CT values strictly increasing

4. Test no boundary advance on EOF:
   - Setup: Segment ends at T+10s; EOF at T+8s
   - Action: EOF occurs at T+8s
   - Expected: Boundary state unchanged at T+8s; switch at T+10s

5. Test frame pacing unchanged:
   - Setup: target_fps = 30
   - Action: Measure frame emission rate before and after EOF
   - Expected: 30 fps maintained (pad frames after EOF)

Done Criteria:
EOF logged; CT monotonic; no boundary advance on EOF; frame pacing preserved.
