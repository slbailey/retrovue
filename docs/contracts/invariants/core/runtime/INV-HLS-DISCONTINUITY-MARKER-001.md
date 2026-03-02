# INV-HLS-DISCONTINUITY-MARKER-001

## Behavioral Guarantee

HLS segmenter MUST emit `#EXT-X-DISCONTINUITY` before any segment where a PCR discontinuity was detected during accumulation. Players MUST NOT be required to infer timeline breaks.

## Authority Model

`HLSSegmenter` owns PCR tracking and playlist generation. Discontinuity detection is PCR-based. Future enhancement: explicit in-band signaling from AIR (SCTE-35 or equivalent).

## Boundary / Constraint

1. When `_current_seg_duration()` detects a PCR discontinuity, the current segment MUST be marked discontinuous.
2. `_generate_playlist()` MUST emit `#EXT-X-DISCONTINUITY` before the `#EXTINF` line of any discontinuous segment.
3. `HLSSegment` MUST carry a `discontinuity: bool` field.
4. Segments with continuous PCR MUST NOT be marked discontinuous.

## Violation

Missing `#EXT-X-DISCONTINUITY` when PCR jumps beyond detection threshold; spurious discontinuity tags on segments with continuous PCR; player A/V desync across content boundaries.

## Derives From

`LAW-DECODABILITY`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_discontinuity_marker.py`

## Enforcement Evidence

TODO
