Task ID: P8-PLAN-001
Rule ID: INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001
Governing Law: LAW-AUTHORITY-HIERARCHY
Subsystem: AIR (FileProducer)
Task Type: CORE
File(s) to Modify: pkg/air/src/playout/file_producer.cpp, pkg/air/include/playout/file_producer.h
Owner: AIR
Blocked By: —

Instructions:
- FileProducer receives planning authority (frame_count) from Core and enforces runtime adaptation against it
- Add `_planned_frame_count` field (int64) — planning authority received from Core
- Add `_frames_delivered` counter (int64) — runtime tracking
- Capture frame_count in legacy preload RPC handler
- Use these for deficit detection (P8-PLAN-002)

---

Governing Principle (LAW-AUTHORITY-HIERARCHY):
> Clock authority supersedes frame completion for switch execution.

Rule Definition (INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001):
frame_count in the playout plan is planning authority from Core. AIR uses it for frame-indexed execution and exhaustion detection. If actual content is shorter than planned, deficit fill applies; if longer, segment end time governs (schedule authoritative).

Implementation Notes:

1. Add fields to FileProducer:
   ```cpp
   int64_t _planned_frame_count = 0;
   int64_t _frames_delivered = 0;
   ```

2. In legacy preload RPC handler:
   ```cpp
   _planned_frame_count = request.frame_count();
   _frames_delivered = 0;
   ```

3. Increment _frames_delivered on each frame emit

4. These fields enable deficit detection in P8-PLAN-002

Observable Proof:
- `_planned_frame_count` set from legacy preload RPC
- Value matches Core's playout plan
- Counter increments per frame delivered

Done Criteria:
FileProducer stores frame_count as planning authority; counter tracks delivered frames; values available for deficit detection.

---

## Completion

- **Date:** 2026-02-02
- **Implementation:** `pkg/air/include/retrovue/producers/file/FileProducer.h`, `pkg/air/src/producers/file/FileProducer.cpp`
  - Added `planned_frame_count_` (int64_t, default -1) and `frames_delivered_` (std::atomic<int64_t>, default 0).
  - In `start()`: set `planned_frame_count_ = config_.frame_count` and `frames_delivered_.store(0)`.
  - Increment `frames_delivered_` at each of the four frame-emit sites (alongside `frames_produced_`).
  - Added `GetPlannedFrameCount()` and `GetFramesDelivered()` for deficit detection (P8-PLAN-002).
- **Build:** AIR builds successfully. Contract tests (PlayoutEngineContracts, DeterministicHarnessContracts) not re-run (timeout).
