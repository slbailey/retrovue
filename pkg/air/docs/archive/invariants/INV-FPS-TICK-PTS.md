# INV-FPS-TICK-PTS — Output PTS Owned by Tick Grid

**Status:** Active  
**Owner:** TickProducer (DROP/returned frame PTS), PipelineManager (mux PTS from OutputClock)  
**Related:** INV-FPS-MAPPING, OutputClock, INV-FENCE-PTS-DECOUPLE

---

## Statement

In OFF, DROP, and CADENCE, **output video PTS must advance by exactly one output tick per returned frame**. In DROP, even though multiple input frames are decoded per tick, the **returned** frame’s video PTS delta must be **1/output_fps** (tick duration), not 1/input_fps. Audio PTS must remain continuous and correspond to total pushed samples, but must not cause the muxer to pace at input-frame cadence. **PTS is owned by the tick grid, not by the decoder.**

---

## Required

| Requirement | Implementation |
|-------------|-----------------|
| **Video PTS per returned frame** | Each frame returned by TickProducer::TryGetFrame() must have video.metadata.pts set to the **output tick PTS** for that frame index (tick_index × tick_duration_us). In DROP, TickProducer overwrites the decoder’s per-input-frame PTS with the output tick PTS before returning. |
| **PTS delta = tick duration** | For consecutive returned frames, `returned_video_pts[n+1] - returned_video_pts[n] == tick_duration_us` (e.g. 33333 µs for 30 fps). Never 1/input_fps (e.g. 16667 µs for 60 fps input in DROP). |
| **Mux / downstream** | PipelineManager uses OutputClock::FrameIndexToPts90k(session_frame_index) for video PTS to the encoder; it does not use the returned frame’s metadata.pts for mux cadence. Any consumer that might use returned frame PTS must see tick-grid PTS so pacing cannot “run 2×”. |
| **Audio PTS** | Audio PTS is continuous and sample-based; muxer must not derive cadence from input-frame timing. |

---

## Rationale

If returned frame PTS were left at decoder (input) values in DROP, any code path that used `frame.metadata.pts` for pacing or PTS delta would advance at 60 fps instead of 30 fps, causing “2× speed” and AUDIO_UNDERFLOW_SILENCE. Fixing duration alone is insufficient if PTS is used as a second clock authority.

---

## Enforcement

- **Code:** TickProducer DROP path sets `first->video.metadata.pts` (and dts) to output tick PTS before return. Contract tests: TickProducer_DROP_OutputPTS_AdvancesByTickDuration (fake decoder, 5–10 ticks, assert PTS delta == tick_duration_us).
