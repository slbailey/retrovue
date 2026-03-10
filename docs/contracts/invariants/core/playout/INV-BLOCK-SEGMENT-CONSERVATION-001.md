# INV-BLOCK-SEGMENT-CONSERVATION-001 — Segment durations must equal block duration at every pipeline stage

Status: Invariant
Authority Level: Execution Intent
Derived From: `LAW-GRID`, `LAW-TIMELINE`

## Purpose

Protects `LAW-GRID` and `LAW-TIMELINE` by ensuring that the total duration of all segments within a ScheduledBlock equals the block's time envelope at every stage of the pipeline — construction, fill, persistence, deserialization, and feed.

Over-coverage (sum > duration) forces AIR to compress content into a shorter wall-clock window, causing playback at the wrong speed. Under-coverage (sum < duration) leaves a gap within the block, violating `LAW-TIMELINE`.

## Guarantee

For every ScheduledBlock at every stage of the pipeline:

```
delta = abs(sum(segment.segment_duration_ms for segment in block.segments)
            - (block.end_utc_ms - block.start_utc_ms))
delta <= FRAME_TOLERANCE_MS
```

Where `FRAME_TOLERANCE_MS = 40` (one frame at 29.97fps rounded up). Frame rounding, timebase conversions, and ad segment trimming may introduce up to 1 frame of drift. Deltas beyond one frame are always a defect.

All segment durations MUST be positive:

```
segment.segment_duration_ms >= 1
```

A zero or negative segment duration is always a defect — negative durations can satisfy the sum predicate by cancellation, masking real overflows.

This predicate MUST hold:

1. **After Tier 1 construction** (`_expand_blocks_inner`): presentation, content, and filler placeholder durations sum to the block envelope.
2. **After Tier 2 fill** (`fill_ad_blocks`): filled interstitial durations replace placeholder durations without changing the total.
3. **At persistence** (`ensure_block_compiled`, `PlaylistBuilderDaemon`): the block written to PlaylistEvent satisfies the predicate.
4. **At deserialization** (`_deserialize_scheduled_block`, `_get_filled_block_by_id`, `ensure_block_compiled` read path): a block read from PlaylistEvent MUST be validated against the predicate. A row that violates it MUST be rejected and recompiled.
5. **At feed time** (`channel_manager._generate_next_block`): the block converted to a BlockPlan for AIR satisfies the predicate.

## Preconditions

- The ScheduledBlock has at least one segment.
- `start_utc_ms` and `end_utc_ms` are set by the planning layer (not derived from segments).
- All segment durations MUST be positive (`segment_duration_ms >= 1`).

## Observability

At each enforcement point, compute the delta between segment sum and block duration. Any delta exceeding `FRAME_TOLERANCE_MS` is a violation. The following MUST be logged on failure:

- `block_id`
- `expected_duration` (block envelope)
- `actual_sum` (segment total)
- `delta` (signed difference)
- `segment_count`
- `stage` (tier1 | tier2_fill | persistence | deserialization | feed)

## Deterministic Testability

Construct a ScheduledBlock with presentation segments (e.g. 74s intro + 5s ratings card) and content + filler. Set filler to `slot - presentation - content` (correct) or `slot - content` (violation: presentation not deducted). Assert that the correct block passes and the overstuffed block is rejected at the deserialization boundary.

## Failure Semantics

**Generation fault** (stages 1-3): The block was constructed or filled incorrectly. Presentation duration was not deducted from the filler budget, or the fill stage introduced overflow.

**Persistence fault** (stage 4): A stale PlaylistEvent row was written by an older code version that did not enforce the invariant. The deserialization boundary MUST detect and reject this. Rejection triggers synchronous recompilation from the corrected in-memory Tier 1 block.

**Feed fault** (stage 5): A block that violates the predicate reached the AIR feed path. This is a defense-in-depth check — if stages 1-4 hold, stage 5 never fires.

## Required Tests

- `pkg/core/tests/contracts/test_tier2_conservation_guard.py::TestTier2ConservationGuard::test_deserialize_rejects_overstuffed_block`
- `pkg/core/tests/contracts/test_tier2_conservation_guard.py::TestTier2ConservationGuard::test_correct_block_round_trips`
- `pkg/core/tests/contracts/test_tier2_conservation_guard.py::TestTier2ConservationGuard::test_overstuffed_block_has_79s_delta`
- `pkg/core/tests/contracts/test_tier2_conservation_guard.py::TestTier2ConservationGuard::test_negative_segment_rejected`
- `pkg/core/tests/contracts/test_tier2_conservation_guard.py::TestTier2ConservationGuard::test_within_frame_tolerance_passes`
- `pkg/core/tests/contracts/test_presentation_tier1_expansion.py::TestBlockFrameConservation::test_segment_sum_equals_block_duration_with_presentation`
- `pkg/core/tests/contracts/test_presentation_tier1_expansion.py::TestBlockFrameConservation::test_segment_sum_equals_block_duration_no_presentation`
- `pkg/core/tests/contracts/test_presentation_tier1_expansion.py::TestBlockFrameConservation::test_presentation_reduces_filler_not_content`

## Enforcement Evidence

TODO
