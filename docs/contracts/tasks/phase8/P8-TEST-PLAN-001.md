Task ID: P8-TEST-PLAN-001
Rule ID: INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001
Governing Law: LAW-AUTHORITY-HIERARCHY
Subsystem: AIR (FileProducer)
Task Type: TEST
File(s) to Modify: pkg/air/tests/playout/test_content_deficit.cpp
Owner: AIR
Blocked By: P8-PLAN-002

Instructions:
- Add contract test: Short content triggers early EOF
- Verify EARLY_EOF logged with correct counts
- Verify deficit frames calculation correct
- Verify content deficit fill triggered

---

Governing Principle (LAW-AUTHORITY-HIERARCHY):
> Clock authority supersedes frame completion for switch execution.

Rule Definition (INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001):
If actual content is shorter than planned frame_count, content deficit fill applies.

Test Cases:

1. Test early EOF detected:
   - Setup: LoadPreview with frame_count=300; content has 250 frames
   - Action: Play until decoder EOF
   - Expected: Early EOF detected at frame 250

2. Test EARLY_EOF logged:
   - Setup: Same as above
   - Action: Check logs
   - Expected: `EARLY_EOF segment={id} planned=300 delivered=250 deficit_frames=50`

3. Test deficit frames calculation:
   - Setup: Various planned/actual combinations
   - Action: Calculate deficit
   - Expected: deficit = planned - delivered; always ≥ 0

4. Test content deficit fill triggered:
   - Setup: Short content
   - Action: Check deficit state after EOF
   - Expected: `_content_deficit_active = true`

5. Test exact match (no early EOF):
   - Setup: LoadPreview with frame_count=300; content has exactly 300 frames
   - Action: Play until decoder EOF
   - Expected: No EARLY_EOF; normal EOF handling

6. Test planned frame count stored:
   - Setup: LoadPreview with frame_count=300
   - Action: Check FileProducer state
   - Expected: `_planned_frame_count = 300`

7. Test frames delivered counter:
   - Setup: Play 100 frames
   - Action: Check counter
   - Expected: `_frames_delivered = 100`

Done Criteria:
EARLY_EOF logged with correct planned/delivered/deficit; deficit fill triggered; frame tracking accurate.
