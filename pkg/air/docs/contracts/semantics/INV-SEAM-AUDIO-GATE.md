# INV-SEAM-AUDIO-GATE

## Scope
Segment seam transition behavior in `PipelineManager` when `take_segment` is true and `SEGMENT_TAKE_COMMIT` has not yet occurred.

## Invariants

### INV-SEAM-AUDIO-001
**Tick loop MUST NOT consume from Segment-B audio buffer until `SEGMENT_TAKE_COMMIT` succeeds.**

Operational meaning:
- If seam is reached but gate defers (`incoming_audio_ms < 500` or insufficient video), `a_src` must remain bound to live/A audio.
- During this deferred window, `segment_b_audio_buffer_->TotalSamplesPopped()` MUST NOT advance due to tick-loop consumption.

### INV-SEAM-GATE-001
**Gate measurements MUST be taken on a buffer not being drained by the live consumer unless commit has occurred.**

Operational meaning:
- During defer, the seam gate may inspect Segment-B depth (`gate_buf == segment_b_audio_buffer_`), but tick-loop consumer pointer (`a_src`) must not point to Segment-B.
- After commit, it is valid for gate buffer and consumer buffer to converge on Segment-B/live.

## Regression Coverage
Contract test: `P6_AudioLivenessNotBlockedByVideoBackpressure.cpp`
- Asserts defer phase keeps `a_src_ptr != seg_b_audio_ptr`
- Asserts Segment-B popped total does not advance while deferred
- Asserts source switches to Segment-B only after simulated threshold crossing + commit
