# INV-ASPECT-PRESERVE-001

## Behavioral Guarantee

When `aspect_policy` is `preserve` (the default), the decoder MUST compute Display Aspect Ratio (DAR) from the source's coded dimensions and Sample Aspect Ratio (SAR), scale to fit within the target raster, and pad the remaining area with black bars. Source pixels MUST NOT be distorted (stretched or compressed).

## Authority Model

FFmpegDecoder owns scaling and padding computation. ProgramFormat carries the `aspect_policy` from Core through gRPC to AIR.

## Boundary / Constraint

- DAR MUST be derived via integer cross-multiplication: `src_dar_num = src_width * sar.num`, `src_dar_den = src_height * sar.den`. No floating-point division.
- When SAR is absent or invalid (0:0), square pixels (1:1) MUST be assumed.
- Scaled dimensions MUST fit within the target raster: `scale_width <= target_width` and `scale_height <= target_height`.
- Padding MUST center the scaled image: `pad_x = (target_width - scale_width) / 2`, `pad_y = (target_height - scale_height) / 2`.
- When scaled dimensions are within 1 pixel of the target, the target dimensions MUST be used directly (no sub-pixel padding).
- Padded area MUST be black (Y=0, U=128, V=128).
- When `aspect_policy` is `stretch`, scaling MUST fill the raster with no padding.

## Violation

Source content is stretched or compressed to fill the target raster when `aspect_policy` is `preserve`. Observable as geometric distortion in output frames.

## Derives From

`LAW-RUNTIME-AUTHORITY`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/AspectPreserveContractTests.cpp`
- `pkg/core/tests/contracts/test_aspect_policy.py`

## Enforcement Evidence

TODO
