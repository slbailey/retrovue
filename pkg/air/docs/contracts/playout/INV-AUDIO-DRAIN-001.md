# INV-AUDIO-DRAIN-001: Full Audio Drain Per Decode Cycle

## Classification
| Field | Value |
|-------|-------|
| ID | INV-AUDIO-DRAIN-001 |
| Type | Semantic |
| Owner | `TickProducer` |
| Enforcement | Runtime |

## One-Line Definition

All decoded audio frames must be transferred from the decoder into
RetroVue-managed buffers during the same decode cycle. The decoder must
never serve as a long-term audio buffer.

## Decode Cycle Definition

A **decode cycle** is any call to the producer that retrieves decoded media
from the codec context. This includes:

- `TryGetFrame()` — buffered frame production
- `DecodeNextFrameRaw()` — raw decode path
- `PrimeFirstTick()` — priming path
- Any future buffer refill path

The invariant applies to every decode cycle, not just video-triggered decodes.

## Rationale

The FFmpeg decoder accumulates decoded audio frames in an internal queue
(`pending_audio_frames_`) as a side-effect of demuxing and decoding video.
The number of audio frames per video frame depends on the codec, sample rate,
container packetization, and decoder delay:

| Codec | Samples/Frame | Frames per 24fps video frame at 48kHz |
|-------|--------------|---------------------------------------|
| AAC LC | 1024 | ~2 |
| HE-AAC | varies | varies |
| AC3 | 1536 | ~1.3 |
| E-AC3 | varies | varies |
| FLAC/PCM | variable | variable |
| 512-sample (observed) | 512 | ~4 |

Multiple demuxed packets may produce audio frames in a single decode cycle.
For example, two AAC packets arriving together yield 2 × 1024 = 2048 samples
across multiple audio frames — all of which must be drained.

An artificial cap on audio frames per decode cycle (`kMaxAudioFramesPerVideoFrame`)
creates a hidden buffer inside the decoder. Undrained audio accumulates, causing:

1. **Progressive A/V desync**: Audio PTS remains correct, but delivery is
   delayed. The consumer plays captured audio at real-time speed while the
   decoder retains frames with future PTS values. This manifests as audio
   drifting ahead of video or bursty playback.
2. **Bursty delivery**: Subsequent decode cycles inherit the backlog, producing
   irregular audio frame counts.
3. **Codec-dependent behavior**: The system works for some codecs and fails
   for others depending on whether the cap happens to be sufficient.

## Invariant

```
WHEN TickProducer performs a decode cycle (any path that retrieves decoded
media from the codec context):
  AFTER decoding the video frame,
  the audio drain loop MUST call GetPendingAudioFrame() until it returns false.
  The loop MUST NOT impose an artificial cap on the number of frames drained.

  A safety fuse (e.g., 64 frames) MAY exist as a purely defensive measure
  against broken containers, corrupt timestamps, decoder bugs, or malformed
  bitstreams. The safety fuse:
    - MUST be set high enough that it never fires under any supported codec
      or container format during normal operation.
    - MUST NOT be relied upon for normal operation.
    - MUST log an AUDIO_DRAIN_VIOLATION if it fires.
    - MUST NOT be lowered to "tune" audio behavior. If audio behavior needs
      tuning, the problem is elsewhere.
```

## Violation

The invariant is violated if `GetPendingAudioFrame()` would return true
after the drain loop exits — i.e., the decoder still has decoded audio frames
that were not transferred to RetroVue-managed buffers.

Observable symptoms:

- Audio drifts ahead of video (progressive desync)
- `AV_SYNC_PROBE` shows `audio_frames` consistently at a fixed cap value
- Audio depth oscillates despite stable decode rate

## Diagnostic

- `AUDIO_DRAIN_VIOLATION`: Logged if safety fuse fires (decoder had more
  frames than the fuse limit). This indicates a pathological stream or
  decoder bug — not a tuning knob.

## Test

- `test_full_drain_no_residual`: Mock decoder queues N audio frames per video
  decode (N > any reasonable cap). After TryGetFrame, verify decoder queue is
  empty and all N frames appear in the returned FrameData::audio vector.
- `test_variable_audio_per_decode`: Mock decoder queues different counts per
  decode (0, 1, 4, 7). Verify all are captured exactly.
- `test_decoder_backlog_from_multiple_packets`: Mock decoder queues audio
  frames from two separate packets (3 + 4 = 7 frames) in a single decode
  cycle. Verify all 7 are drained. Simulates real AAC/DTS multi-packet
  behavior.
