# INV-HLS-PRODUCER-SEGMENT-FLOW-001

## Behavioral Guarantee

While a producer is active and the upstream reader is connected, the segmenter MUST produce segments at approximately real-time rate. A stall in segment production while the producer is healthy indicates a segmenter failure, not a producer failure.

## Authority Model

HLSSegmenter owns segment production. ChannelStream upstream reader owns byte delivery. ChannelManager owns stall detection.

## Boundary / Constraint

- The system MUST track the timestamp of the last completed segment.
- If no segment has been completed within `2 * target_segment_duration` while the upstream reader reports bytes flowing, the system MUST log at WARNING level with invariant ID.
- If the stall persists for `4 * target_segment_duration`, the system MUST log at ERROR level and trigger segmenter recovery (restart the segmenter without restarting the producer).
- If the producer itself has failed (upstream reader reports EOF), this invariant does not apply — `INV-CHANNEL-LIVENESS-RECOVERY-001` governs producer recovery.

## Violation

Segmenter stall while upstream bytes are flowing; no warning emitted after `2 * target_segment_duration` gap; no recovery after `4 * target_segment_duration` gap.

## Derives From

`INV-HLS-LIFECYCLE-SEGMENT-READY-001`, `INV-CHANNEL-LIVENESS-RECOVERY-001`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_channel_runtime.py`

## Enforcement Evidence

TODO
