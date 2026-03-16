# INV-HLS-SEGMENT-SELFCONTAINED-001

## Behavioral Guarantee

Every completed HLS segment is a valid MPEG-TS byte sequence containing PAT and PMT tables. A compliant TS demuxer can identify the program structure from the segment alone without reference to prior segments or external metadata.

## Authority Model

AIR's EncoderPipeline owns PAT/PMT emission. HLSSegmenter owns segment boundary placement to ensure structural completeness.

## Boundary / Constraint

- Every segment MUST contain at least one PAT and one PMT.
- Every segment MUST contain at least one complete video frame and its corresponding audio samples.
- Zero-byte or video-absent segments MUST NOT be produced.

## Violation

Segment missing PAT or PMT; segment with zero video frames; segment that a compliant demuxer cannot parse without prior segment context.

## Derives From

`LAW-DECODABILITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_production.py`

## Enforcement Evidence

TODO
