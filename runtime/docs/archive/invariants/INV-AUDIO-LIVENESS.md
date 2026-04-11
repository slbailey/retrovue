# INV-AUDIO-LIVENESS

## Purpose

Define and protect the liveness guarantee that audio servicing must not be
starved by video queue backpressure during CONTENT playback.

This invariant prevents regressions where video ring saturation halts the
FillLoop in a way that freezes audio production and causes chronic
AUDIO_UNDERFLOW_SILENCE.

---

## INV-AUDIO-LIVENESS-001 — Audio Servicing Is Decoupled From Video Backpressure

### Rule

During CONTENT playback with audio enabled, video queue backpressure MUST NOT
prevent ongoing audio servicing.

Video saturation (e.g., video ring depth ≥ high_water) may block further
video enqueues, but it MUST NOT halt:

- Demux servicing required for audio packet dispatch
- Audio decoder draining
- Audio frame production into the AudioLookaheadBuffer

### Operational Definition

While:

- `is_pad == false`
- Audio stream is present
- Audio source is primed or expected to produce

The system MUST continue to attempt audio servicing at least once per
output tick (or equivalent bounded servicing interval), independent of
video ring fullness.

### Allowed Behaviors Under Video Saturation

When video depth is at or above high-water:

- Drop decoded video frames
- Discard decoded video output
- Skip video enqueue
- Hold last video frame
- Apply cadence (DROP/REPEAT) logic

### Disallowed Behavior

It is a contract violation if:

- Video queue saturation causes the FillLoop (or equivalent servicing loop)
  to park in a way that stops both video and audio production, AND
- Audio production flatlines (no samples pushed) for sustained intervals
  during active CONTENT playback.

---

## INV-AUDIO-LIVENESS-002 — Underflow Silence Is Transitional, Not Steady-State

### Rule

AUDIO_UNDERFLOW_SILENCE is a safety fallback and MUST be transitional.

During steady-state CONTENT playback, silence injection MUST NOT occur
continuously for sustained durations once audio has been primed.

### Operational Guideline

After initial priming or segment transition:

- Audio buffer depth should stabilize above minimal operational threshold.
- Consecutive fallback ticks injecting silence should not exceed a bounded,
  short transitional window.

Continuous silence injection across sustained playback of a single CONTENT
segment indicates a violation of audio liveness guarantees.

---

## Rationale

Video is bursty and subject to backpressure constraints.

Audio is continuity-critical and must remain live.

Professional broadcast playout systems decouple audio servicing from
video buffering constraints to prevent starvation and audible failure.

This invariant codifies that architectural separation.

---

## Test Coverage

The following contract tests enforce this invariant:

- P6_AudioLivenessNotBlockedByVideoBackpressure
- (Optional structural saturation checks using VideoLookaheadBuffer::DepthFrames)

Any future queue optimization or servicing change that causes audio
production to flatline under video saturation must fail contract tests.

---

## Scope

Applies to:

- FileProducer
- VideoLookaheadBuffer
- AudioLookaheadBuffer
- FillLoop / servicing logic
- Cadence (DROP / REPEAT) logic
- Any future producer types with audio streams

Does NOT apply to:

- PAD segments (PAD is silence by design)
- FENCE_AUDIO_PAD
- Explicit audio-disabled content

---

## Related Invariants

- INV-AIR-MEDIA-TIME-005 — Pad is never primary
- INV-PAD-PRODUCER-001 — Pad is a first-class source
- INV-AUDIO-LOOKAHEAD-001 — Centralized audio emission
