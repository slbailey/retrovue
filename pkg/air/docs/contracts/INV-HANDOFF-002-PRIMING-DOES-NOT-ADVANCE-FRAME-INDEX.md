# INV-HANDOFF-002: Priming must not advance the producer output frame index

**Invariant:** INV-HANDOFF-002

**Title:** Priming must not advance the producer output frame index.

**Statement:** Frames decoded during `TickProducer::PrimeFirstTick()` are used only to prepare audio and video buffers for startup and must not advance the producer's output frame index.

---

## Rules

1. `frame_index_` must equal 0 after `PrimeFirstTick()` completes.
2. The first frame returned from `TryGetFrame()` for a new block must have `source_frame_index == 0` (or the first scheduler-selected index).
3. The first frame pushed into LIVE_VIDEO_BUFFER must align with the scheduler's `selected_src` for the first content tick.

---

## Rationale

Audio priming decodes several frames to fill the audio pipeline before playback begins. These frames are not yet part of the session output and must not advance the producer's frame index. If they do, the live buffer begins ahead of the scheduler and the INV-HANDOFF-001 invariant (`actual_src_emitted == selected_src`) is violated.

**Implementation:** In `TickProducer::PrimeFirstTick()`, the audio-priming decode loop must call `DecodeNextFrameRaw(false)` so that `frame_index_` is not advanced during priming.

---

## Required tests

| Test | File | Purpose |
|------|------|---------|
| `test_prime_first_tick_does_not_advance_frame_index` | `tests/contracts/test_prime_first_tick_does_not_advance_frame_index.cpp` | After AssignBlock + PrimeFirstTick, EXPECT(GetFrameIndex() == 0). Cheap, deterministic. |
| `test_first_live_frame_matches_scheduler` | `tests/contracts/test_first_live_frame_matches_scheduler.cpp` | After AssignBlock, PrimeFirstTick, StartFilling, first frame from LIVE_VIDEO_BUFFER has source_frame_index == selected_src for first content tick. Protects against priming/handoff/producer-reset bugs. |

---

## Related

- **INV-HANDOFF-001:** `actual_src_emitted == selected_src` every output tick. INV-HANDOFF-002 ensures startup does not violate it.
- **INV-HANDOFF-001-SOURCE-FRAME-TRACE:** [design/INV-HANDOFF-001-SOURCE-FRAME-TRACE.md](../design/INV-HANDOFF-001-SOURCE-FRAME-TRACE.md) — root cause analysis and fix (PrimeFirstTick must use `DecodeNextFrameRaw(false)`).
