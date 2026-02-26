# Investigation: Why Were These Files Deleted?

**Date:** 2026-02-26  
**Context:** Compile was working; then five files were missing from the working tree (uncommitted deletions). This doc records why they were deleted and how to prevent it.

---

## What Was Deleted (Uncommitted)

| File | In ProducerBus retirement checklist? | BlockPlan needs it? |
|------|--------------------------------------|---------------------|
| `src/runtime/TimingLoop.cpp` | **Yes** — "Verify no BlockPlan dependency, then delete" | No (legacy path only) |
| `src/blockplan/PipelineManager.cpp` | **No** | **Yes** — core BlockPlan engine |
| `src/blockplan/AudioLookaheadBuffer.cpp` | **No** | **Yes** — BlockPlan audio buffer |
| `include/retrovue/blockplan/AudioLookaheadBuffer.hpp` | **No** | **Yes** |
| `include/retrovue/output/SocketSink.h` | **No** | **Yes** — used by MpegTSOutputSink |

The deletions were **never committed**. Git status showed ` D` (deleted in working tree). Commit `ff9610d` still had all five files.

---

## Root Cause (Findings)

1. **No commit removed them**  
   `git log` shows no commit on this branch deleted those sources. So the removal happened in the working tree only (file delete or `git rm` without commit).

2. **Repo has no script that deletes them**  
   No Makefile, script, or automation in the repo deletes `PipelineManager.cpp`, `AudioLookaheadBuffer.*`, or `SocketSink.h`. The only doc that mentions deleting any of these is **ProducerBus-Retirement-Checklist.md**, and it only lists **TimingLoop** (and other ProducerBus components) for future deletion. It does **not** list PipelineManager or AudioLookaheadBuffer — those are BlockPlan components and must be retained.

3. **Checklist does not justify deleting PipelineManager / AudioLookaheadBuffer / SocketSink**  
   Following the checklist would at most lead to deleting TimingLoop (after verification). Deleting PipelineManager.cpp, AudioLookaheadBuffer.cpp/hpp, and SocketSink.h is **not** in the checklist and breaks the BlockPlan build.

4. **Most likely causes**
   - **Agent/session over-application:** A Cursor agent (or similar) asked to "retire ProducerBus" or "clean up legacy" may have deleted too many files — e.g. misreading the checklist or confusing “legacy path” with “all AIR runtime files.”
   - **Bulk delete by mistake:** Multi-file selection in the IDE or a global search-and-delete that included these by mistake.
   - **Broken refactor/clean:** A “remove dead code” or “clean project” action that incorrectly treated these as unused (e.g. wrong or partial build graph).

---

## Prevention

- **Do not delete** the following unless the BlockPlan path has been fully removed or replaced and the build no longer references them:
  - `pkg/air/src/blockplan/PipelineManager.cpp`
  - `pkg/air/src/blockplan/AudioLookaheadBuffer.cpp`
  - `pkg/air/include/retrovue/blockplan/AudioLookaheadBuffer.hpp`
  - `pkg/air/include/retrovue/output/SocketSink.h`
- **TimingLoop.cpp** is listed in the retirement checklist for future removal; it must only be deleted after verifying no BlockPlan dependency and after PlayoutEngine/PlayoutControl no longer reference it (or those are removed first).
- When working from **ProducerBus-Retirement-Checklist.md**, only delete files explicitly listed there and only after the stated “Action required” (e.g. verify, then delete). Do not delete PipelineManager, AudioLookaheadBuffer, or SocketSink based on that doc.

---

## Restoring the Build (Done)

The five files were restored with:

```bash
git checkout HEAD -- \
  pkg/air/src/runtime/TimingLoop.cpp \
  pkg/air/src/blockplan/PipelineManager.cpp \
  pkg/air/src/blockplan/AudioLookaheadBuffer.cpp \
  pkg/air/include/retrovue/blockplan/AudioLookaheadBuffer.hpp \
  pkg/air/include/retrovue/output/SocketSink.h
```

The missing `PerformSegmentSwap` declaration was added to `PipelineManager.hpp` so the existing `PipelineManager.cpp` compiles.
