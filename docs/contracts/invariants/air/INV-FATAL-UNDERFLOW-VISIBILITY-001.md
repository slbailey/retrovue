# INV-FATAL-UNDERFLOW-VISIBILITY-001 (Fatal underflow emits structured evidence)

## Behavioral Guarantee

When a post-primed decoder underflow terminates a session, AIR MUST record a structured error and MUST increment a session-fatal metric counter. A session terminating under this condition without both the structured error record and the counter increment MUST NOT occur.

## Authority Model

The AIR component that detects post-primed decoder underflow and terminates the session is the sole authority for the structured error and the counter increment. Both the error record and the counter MUST be emitted at the termination site, not reconstructed later by a consumer.

## Boundary / Constraint

- The structured error MUST carry the following fields: `reason`, `tick`, `block_id`, `decoder_ok`, `video_depth`, `audio_depth_ms`.
- The session-fatal metric counter MUST increment exactly once per terminating event.
- Pre-primed underflow (which does not terminate the session) is out of scope for this invariant and MUST NOT emit the session-fatal counter.

## Violation

A session termination caused by post-primed decoder underflow that completes without a structured error record; a structured error emitted for such a termination that omits any of the required fields; a terminating event that does not increment the session-fatal counter; a pre-primed underflow that increments the session-fatal counter.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/readiness/FatalUnderflowVisibilityTests.cpp`

## Enforcement Evidence

TODO
