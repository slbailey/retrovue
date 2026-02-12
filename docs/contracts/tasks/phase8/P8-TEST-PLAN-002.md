Task ID: P8-TEST-PLAN-002
Rule ID: INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001
Governing Law: LAW-AUTHORITY-HIERARCHY
Subsystem: AIR (FileProducer)
Task Type: TEST
File(s) to Modify: pkg/air/tests/playout/test_content_deficit.cpp
Owner: AIR
Blocked By: P8-PLAN-003

Instructions:
- Add contract test: Long content truncated at boundary
- Verify CONTENT_TRUNCATED logged
- Verify no frames delivered after planned count
- Verify boundary timing unchanged

---

Governing Principle (LAW-AUTHORITY-HIERARCHY):
> Clock authority supersedes frame completion for switch execution.

Rule Definition (INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001):
If content is longer than planned frame_count, segment end time governs (schedule authoritative). Excess content is truncated.

Test Cases:

1. Test long content truncated:
   - Setup: legacy preload RPC with frame_count=300; content has 350 frames
   - Action: Play until planned count reached
   - Expected: Only 300 frames delivered; 50 frames not played

2. Test CONTENT_TRUNCATED logged:
   - Setup: Same as above
   - Action: Check logs
   - Expected: `CONTENT_TRUNCATED segment={id} planned=300 available=350 excess_frames=50`

3. Test truncation at frame_count:
   - Setup: Same as above
   - Action: Count frames delivered
   - Expected: Exactly 300 frames

4. Test no early EOF on long content:
   - Setup: Long content
   - Action: Check for EARLY_EOF
   - Expected: No EARLY_EOF logged

5. Test boundary timing unchanged:
   - Setup: Long content; boundary at T+10s
   - Action: Monitor boundary
   - Expected: Switch at T+10s; extra content does not extend segment

6. Test truncation logged once:
   - Setup: Long content
   - Action: Count CONTENT_TRUNCATED logs
   - Expected: Exactly one log per segment

7. Test switch occurs normally:
   - Setup: Long content with preview loaded
   - Action: Wait for boundary
   - Expected: Switch executes; next segment starts

Done Criteria:
Long content truncated at frame_count; CONTENT_TRUNCATED logged; boundary timing authoritative; excess frames not played.
