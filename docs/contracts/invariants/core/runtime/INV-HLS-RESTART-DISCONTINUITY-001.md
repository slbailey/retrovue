# INV-HLS-RESTART-DISCONTINUITY-001

## Behavioral Guarantee

When a producer restarts (after failure recovery or viewer departure + return), the first segment produced after restart MUST carry a discontinuity flag. The segmenter's PTS tracker MUST reset. Segment indices MUST continue from the channel's counter (not reset to zero).

## Authority Model

HLSSegmenter owns PTS tracker reset and discontinuity marking. ChannelManager owns index counter persistence.

## Boundary / Constraint

- On segmenter initialization (new producer session), the PTS tracker MUST be set to "no prior segment" state.
- The first segment produced MUST have `discontinuity = True`.
- The segment index MUST be `channel_segment_counter + 1`, not 0 or 1.
- If the ChannelManager persists across restart, the counter MUST survive. If the ChannelManager was destroyed, the counter starts fresh and the manifest MUST carry an incremented `EXT-X-DISCONTINUITY-SEQUENCE`.

## Violation

First segment after restart missing discontinuity flag; PTS tracker not reset; segment index resetting to zero; stale PTS tracker from prior session.

## Derives From

`INV-HLS-SEGMENT-PTS-CONTINUITY-001`, `INV-HLS-SEGMENT-IDENTITY-001`, `INV-HLS-DISCONTINUITY-MARKER-001`, `LAW-DECODABILITY`

## Required Tests

- `server/tests/contracts/test_inv_hls_channel_runtime.py`

## Enforcement Evidence

- `TestHlsRestartDiscontinuity::test_initial_construction_forces_discontinuity` — new segmenter forces discontinuity
- `TestHlsRestartDiscontinuity::test_reset_for_restart_forces_discontinuity` — reset sets _force_next_discontinuity=True
- `TestHlsRestartDiscontinuity::test_reset_for_restart_resets_pts_tracking` — PTS state cleared
- `TestHlsRestartDiscontinuity::test_reset_for_restart_continues_index` — index continues from next_index
- `TestHlsRestartDiscontinuity::test_reset_clears_accumulation_buffer` — buffers cleared
- `TestHlsRestartDiscontinuity::test_reset_reopens_closed_segmenter` — closed segmenter reopened
