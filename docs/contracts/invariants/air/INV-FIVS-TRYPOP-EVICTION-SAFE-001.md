# INV-FIVS-TRYPOP-EVICTION-SAFE-001

## Classification
CONTRACT — AIR

## Owner
AIR (VideoLookaheadBuffer)

## One-Line Definition
TryPopFrame MUST NOT destroy FIVS entries beyond the single frame it consumed.

## Context

VideoLookaheadBuffer maintains two parallel data structures:
- A **deque** (`frames_`) for FIFO access via TryPopFrame
- A **FIVS** (`frame_store_`) for O(1) indexed access via GetByIndex

DepthFrames() reads from the FIVS. Swap eligibility gates read DepthFrames().

## Invariant

```
forall pop in TryPopFrame():
  let popped_index = pop.source_frame_index
  let fivs_before = frame_store_.Size() before pop
  let fivs_after  = frame_store_.Size() after pop
  fivs_before - fivs_after <= 1
```

TryPopFrame removes at most one frame from the deque and at most one entry
from the FIVS. It MUST NOT call EvictBelow with a threshold that removes
entries the pop did not consume.

## Violation Scenario (Observed 2026-03-17)

1. Segment B fill thread decodes 136 frames (indices 0–135), hits EOF, then
   continues pushing the last decoded frame (index=135) as duplicates.
2. Deque accumulates duplicates; hard-cap drops evict low-index entries from
   the front.  Deque front becomes a frame with `source_frame_index=135`.
3. FIVS retains 136 unique entries (duplicates replace via FIVS-DUPLICATE-POLICY).
4. SEAM_VSRC_GATE evaluates `DepthFrames()=136`, declares eligible.
5. `TryPopFrame` pops deque front (`source_frame_index=135`), calls
   `EvictBelow(136)` → removes ALL 136 FIVS entries.
6. `DepthFrames()` drops to 0 (then 1 after fill thread pushes another duplicate).
7. POST-TAKE re-evaluates: `incoming_video_frames=1 < required=15` → swap deferred.
8. Authority violation: emitted frame has origin=B, but active remains A.

## Root Cause

`EvictBelow(popped_index + 1)` assumes the deque front always has the lowest
source_frame_index. This assumption breaks when the fill thread pushes
duplicate frames after EOF, causing the deque's hard-cap eviction to drop
low-index entries while the FIVS retains them.

## Enforcement

TryPopFrame MUST NOT call `frame_store_.EvictBelow()`. FIVS lifecycle:
- **Capacity management**: AutoEvictIfNeeded (triggered per insert)
- **Consumer-driven cleanup**: Explicit EvictBelow from tick loop
- **Destruction**: Buffer teardown at PerformSegmentSwap

## Derives From

- INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 (frame origin must match active authority)
- LAW-LIVENESS (system must always produce valid output)

## Evidence

- Log: `hbo-air.log.prev` line 680: `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED tick=1077`
- FIVS depth: 136 at SEAM_VSRC_GATE → 1 at SEAM_TICK_EMISSION_AUDIT (same tick)
- Fill thread: `store_size=1 total_pushed=400` (duplicates after EOF)
