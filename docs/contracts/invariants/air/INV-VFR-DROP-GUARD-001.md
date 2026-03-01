# INV-VFR-DROP-GUARD-001

## Behavioral Guarantee
DROP resample mode MUST NOT be selected when the file's nominal frame rate (`r_frame_rate`) diverges from its actual average frame rate (`avg_frame_rate`) by more than 10%. In such cases, `avg_frame_rate` MUST be used for cadence detection.

## Authority Model
`FFmpegDecoder::GetVideoRationalFps()` is the sole authority for input frame rate reported to `TickProducer`.

## Boundary / Constraint
When `r_frame_rate` and `avg_frame_rate` are both valid and `|r - avg| / max(r, avg) > 0.10`, `GetVideoRationalFps()` MUST return the `avg_frame_rate` value (snapped to a standard broadcast rate via `SnapToStandardRationalFps`). The `r_frame_rate` value MUST NOT be used for cadence when this divergence threshold is exceeded.

## Violation
DROP mode selected on a VFR or mislabeled file; video decoder exhausted before segment duration elapses while audio buffer retains real content audio; viewer observes black video with continuing audio.

## Derives From
`INV-FPS-RESAMPLE`, `LAW-LIVENESS`

## Required Tests
- `pkg/air/tests/contracts/BlockPlan/MediaTimeContractTests.cpp` (VfrFile_MustNotEnterDropMode)

## Enforcement Evidence
TODO
