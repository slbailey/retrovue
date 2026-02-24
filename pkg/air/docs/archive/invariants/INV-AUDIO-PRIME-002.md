# INV-AUDIO-PRIME-002 — Prime Frame Must Carry Audio When Asset Has Audio

**Status:** Active  
**Owner:** TickProducer (PrimeFirstTick), VideoLookaheadBuffer (StartFilling log)  
**Related:** INV-AUDIO-PRIME-001, INV-BLOCK-PRIME-001/002

---

## Statement

If the asset has an audio stream, then after PrimeFirstTick completes, the **first frame** returned to StartFilling (the “primed frame”) must include **at least one audio packet**, or the system must not treat the buffer as ready for seam until audio is present. This prevents the “primed video but audio_count=0” false-ready condition that causes fence logic to panic and AUDIO_UNDERFLOW_SILENCE at cold start.

---

## Why It Matters

The very first decoded video frame often has **no** pending audio yet (codec delay / resampler warmup). If we treat “HasPrimedFrame” as ready while that primed frame has 0 audio, we hand the tick loop a buffer with one video frame and zero audio. The downstream gate (wait for audio_depth_ms >= 500) then races with the first tick and can underflow.

---

## Required

| Requirement | Implementation |
|-------------|-----------------|
| **Primed frame has ≥1 audio when audio exists** | In PrimeFirstTick, after restoring the first frame as primed_frame_: if the decoder has an audio stream and primed_frame_->audio is empty but buffered_frames_ has frames with audio, move one audio frame from the front of buffered_frames_ into primed_frame_->audio so the primed frame carries at least one packet. |
| **Ready for seam** | StartFilling logs `ready_for_seam` and `reason` using primed_frame.audio_count and audio_depth_ms after pushing primed audio. PipelineManager already gates start on audio_depth_ms >= kMinAudioPrimeMs; the log makes it obvious when the primed frame contributed no audio (`reason=primed_has_no_audio`). |
| **Logging** | When the primed frame is consumed in StartFilling, log: `has_audio_stream`, `audio_count`, `audio_depth_ms` (after push), `ready_for_seam`, `reason`. |

---

## Enforcement

- **Code:** TickProducer::PrimeFirstTick steals one audio from buffered into primed when primed has 0 and decoder has audio stream. VideoLookaheadBuffer::StartFilling logs the single line with has_audio_stream, audio_count, audio_depth_ms, ready_for_seam, reason.
- **Decoder:** ITickProducerDecoder::HasAudioStream() and FFmpegDecoder::HasAudioStream() (audio_stream_index_ >= 0) so we know when to require audio on the primed frame.
