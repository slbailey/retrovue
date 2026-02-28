# INV-CONTENT-DEFICIT-FILL

## Behavioral Guarantee
If the live path reaches EOF before the scheduled segment end, the gap (content deficit) MUST be filled with pad at real-time cadence until the boundary. Output liveness and TS cadence are preserved; the mux does not stall.

## Authority Model
Core declares the segment boundary. Sink/mux fills the gap at real-time rate. No stall for lack of content.

## Boundary / Constraint
Gap between EOF and boundary MUST be filled at real-time cadence. Mux MUST NOT stall or break TS cadence due to the content gap.

## Violation
Mux stalling or breaking TS cadence due to pre-boundary content gap; gap not filled at real-time cadence. MUST be logged.

## Required Tests
- `pkg/air/tests/contracts/BlockPlan/SegmentAdvanceOnEOFTests.cpp`
- `pkg/air/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp` (pad-fill / gap fill)

## Enforcement Evidence

- `PipelineManager` advances to PAD on EOF — when the live content path reaches end-of-file before the scheduled segment end, authority transfers to `PadProducer` (never loops content or stalls).
- `PadProducer` provides real-time cadence fill frames (black video + silent audio) matching session format, maintaining output liveness through the content deficit.
- `MpegTSOutputSink` boot window ensures no mux stall during initial content acquisition — null packets maintain TS cadence even before first media frame.
- Contract tests: `SegmentAdvanceOnEOFTests.cpp` validates PAD activation on content EOF. `ContinuousOutputContractTests.cpp` validates continuous output (no TS cadence break) across content-to-pad transitions.
