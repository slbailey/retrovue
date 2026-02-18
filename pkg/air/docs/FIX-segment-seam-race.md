# FIX: Segment Seam Race Condition Causing Black Frames

**Repository:** Retrovue-playout  
**Component:** BlockPlan PipelineManager  
**Date:** 2026-02-18  
**Files Changed:** `src/blockplan/PipelineManager.cpp`, `include/retrovue/blockplan/PipelineMetrics.hpp`  
**Files Not Changed:** `src/blockplan/SeamPreparer.cpp`, `include/retrovue/blockplan/SeamPreparer.hpp`

---

## Problem Description

### Symptom

When AIR's `PipelineManager` processes multi-segment blocks with interleaved PAD segments (e.g. `CONTENT → PAD → CONTENT → PAD → ...`), black frames appear at segment boundaries and never recover. The session may continue but content frames never return after the first miss.

### Log Evidence

```
[PipelineManager] SEGMENT_PREP_ARMED tick=0 next_segment=1 segment_type=PAD seam_frame=901
[PipelineManager] SEGMENT_SEAM_TAKE from_segment=0 (CONTENT) to_segment=1 (PAD) prep_mode=MISS
[PipelineManager] SEGMENT_SEAM_PAD_FALLBACK tick=901 segment_index=0
[PipelineManager] SEGMENT_SEAM_TAKE from_segment=1 (PAD) to_segment=2 (CONTENT) prep_mode=MISS
[PipelineManager] SEGMENT_SEAM_PAD_FALLBACK tick=902 segment_index=1
```

`prep_mode=MISS` fires because the SeamPreparer worker had zero wall-clock lead time to prepare the content. Every subsequent seam is also a MISS because the system never recovers — the single-slot SeamPreparer can only hold one result, and it's always consumed (or lost) before the next content segment activates.

---

## Root Cause Analysis

### Architecture Background

`PipelineManager` uses a single-worker, single-slot `SeamPreparer` to prep upcoming segments/blocks in the background. The worker opens a decoder, primes audio, and posts the ready `TickProducer` to a slot. The tick loop polls the slot at the seam frame and swaps the live producer.

### The Race

**Current `ArmSegmentPrep` behavior:**
```
Segment 0 (CONTENT, 10min) activates
  → ArmSegmentPrep arms prep for segment 1 (PAD, 33ms = 1 frame)
  → Worker has ~10 minutes to prep... a PAD segment (near-instant)
  → Seam 0→1 fires: worker gives PAD result
  → ArmSegmentPrep arms prep for segment 2 (CONTENT, 10min)
  → Worker now has 33ms (1 PAD frame) to open decoder, seek, prime audio
  → Seam 1→2 fires: worker not done → MISS → black frames
```

The root problem: `ArmSegmentPrep` always arms for `current_segment_index_ + 1`. When `N+1` is a 1-frame PAD segment, the worker only gets one frame period (~33ms at 30fps) to prep the following content segment. Decoder open + seek + audio prime requires 500–2000ms. The worker always loses this race.

### Why PADs Are 1 Frame

PAD segments exist to fill the exact number of frames between content segments and the block fence. They are declared as `SegmentType::kPad` with `asset_uri = ""`. They have no decoder and require no file I/O. Prepping them via the async worker is wasted machinery — PAD transitions are trivially instant.

---

## Solution Design

Three surgical changes to `PipelineManager.cpp`. **No changes to `SeamPreparer.cpp/.hpp`.**

### Change 1: `ArmSegmentPrep` Skips PAD Segments

Instead of always arming for `current_segment_index_ + 1`, scan forward to find the next non-PAD segment and prep that instead.

**Before:**
```
Segment 0 (CONTENT) activates → arm prep for segment 1 (PAD)
  Worker gets: ~0ms lead time for segment 2 (CONTENT)
```

**After:**
```
Segment 0 (CONTENT) activates → skip PAD(1), arm prep for CONTENT(2)
  Worker gets: full duration of segment 0 (10+ minutes) as lead time
```

**Guard against double-submission:** When a PAD seam fires inline (Change 2), `ArmSegmentPrep` is called again. It checks `seam_preparer_->HasSegmentResult()` with matching identity — if CONTENT(2) is already prepped, it skips re-submission. If the worker is still running (for this segment), it also skips.

### Change 2: `PerformSegmentSwap` Handles PAD Inline

When the incoming segment type is PAD, take an early return path that:
1. Creates a fresh empty `TickProducer` (no decoder → no real frames → pad output)
2. Creates fresh `VideoLookaheadBuffer` and `AudioLookaheadBuffer`
3. Starts the fill thread on the empty producer (immediately parks, buffer stays unprimed)
4. The tick loop naturally emits pad frames via `PadProducer` (existing mechanism)
5. **Never touches `SeamPreparer`** — no submission, no consumption

This labels the transition as `prep_mode=INSTANT` in `SEGMENT_SEAM_TAKE` logs.

### Change 3: Metric Observability

Added `segment_seam_pad_inline_count` to `PipelineMetrics` to count PAD-inline seam transitions. This allows tests and operators to verify that PAD seams go through the inline path (not the worker).

---

## Sequence Diagrams

### Before Fix (Broken)

```
Tick Loop          ArmSegmentPrep        SeamPreparer Worker
    |                    |                      |
    | CONTENT(0) active  |                      |
    |-------------------->|                      |
    |                    | arm seg1=PAD         |
    |                    |--------------------->|
    |                    |                      | prep PAD (instant)
    | 1 PAD frame passes |                      | result ready
    | seam 0→1 fires     |                      |
    |<----- SWAP PAD <---|                      |
    |  arm seg2=CONTENT  |                      |
    |-------------------->|                      |
    |                    | arm seg2             |
    |                    |--------------------->|
    |                    |              [START: open decoder, seek, prime]
    | 1 frame later      |                      |
    | seam 1→2 fires     |                      | [still decoding...]
    |<-- SWAP: MISS ----<|                      |
    |  PAD fallback      |                      |
    |  BLACK FRAMES      |                      |
```

### After Fix (Correct)

```
Tick Loop          ArmSegmentPrep        SeamPreparer Worker
    |                    |                      |
    | CONTENT(0) active  |                      |
    |-------------------->|                      |
    |                    | skip PAD(1),         |
    |                    | arm seg2=CONTENT     |
    |                    |--------------------->|
    |                    |            [START: open decoder, seek, prime]
    | 10min of CONTENT   |                      | [decoding... done in <2s]
    |                    |                      | result slot: CONTENT(2) READY
    | seam 0→1 fires     |                      |
    |  PAD inline!       |                      |
    |  NO WORKER TOUCH   |                      | result slot: still holding
    |                    |                      |
    | 1 PAD frame        |                      |
    | seam 1→2 fires     |                      |
    |<-- SWAP: PREROLLED-|                      |
    |  CLEAN SWITCH      |                      |
    | CONTENT(2) active  |                      |
    |-------------------->|                      |
    |                    | skip PAD(3),         |
    |                    | arm seg4=CONTENT     |
    |                    |--------------------->|
    |    ...             |                      | [decoding...]
```

---

## Resource Impact

**Identical to current.** The fix does not change the SeamPreparer architecture (single worker, single result slot). It only changes which segment gets submitted and handles PAD transitions without the worker.

| Resource           | Before  | After   |
|--------------------|---------|---------|
| Decoder instances  | 2/chan  | 2/chan  |
| Worker threads     | 1/chan  | 1/chan  |
| Memory (decoders)  | 2× avg  | 2× avg  |
| Memory (PAD swap)  | 3 alloc | 3 alloc |

At 10 channels: still 20 total decoders, 10 worker threads. No regression.

---

## Edge Cases Handled

| Scenario                        | Behavior                                                  |
|---------------------------------|-----------------------------------------------------------|
| `CONTENT → PAD → CONTENT → ...` | Skip PAD in prep; PAD inline; CONTENT prerolled           |
| Block with all PADs             | Scan finds nothing; no prep armed; all seams inline       |
| Block ending in PAD             | Last seam inline; `ArmSegmentPrep` returns (out of range) |
| Single-segment block            | Existing early return (size ≤ 1)                          |
| PAD at position 0               | Inline; `ArmSegmentPrep` scans from 1 for next content    |
| Multiple consecutive PADs       | All inline; single prep armed for next non-PAD            |
| Worker already has result       | Guard prevents double-submission                          |
| Worker running (for target)     | Guard skips; worker finishes naturally                    |

---

## Preserved Invariants

- `SeamPreparer` single-worker, single-slot architecture: **unchanged**
- All existing log formats (`SEGMENT_PREP_ARMED`, `SEGMENT_SEAM_TAKE`, etc.): **preserved**
- `PAD` inline path reuses `PadProducer` (session-lifetime, zero per-frame allocation)
- All existing tests pass without modification
