# INV-TICK-GUARANTEED-OUTPUT

**Classification**: INVARIANT (Broadcast-Grade, Non-Negotiable)
**Owner**: MpegTSOutputSink / MuxLoop
**Enforcement Phase**: All phases after first frame
**Priority**: ABOVE all other invariants in output path

## Definition

Every output tick emits exactly one frame, unconditionally.

The fallback chain is:
1. **Real** — Dequeue from video queue
2. **Freeze** — Re-emit last successfully emitted frame
3. **Black** — Emit pre-allocated black frame

No conditional, timing check, buffer health check, or diagnostic can prevent emission.

## Rationale

**CONTINUITY > CORRECTNESS**

In broadcast:
- Dead air is a regulatory violation and advertiser liability
- A wrong frame is a production issue
- These are not equivalent

Professional playout systems (Harris, Grass Valley, Imagine, Evertz) enforce this
at the hardware level — the output card fires every 33.3ms and *something* goes out.
Software systems must achieve the same guarantee structurally.

## Bounded Pre-Timing Wait

Before timing is initialized (first real frame), MuxLoop waits up to **500ms** for content.
If no frame arrives within that window:
1. Timing is initialized synthetically (ct_epoch_us = 0)
2. Black frames begin emitting immediately
3. Logging indicates "synthetic timing" mode

This ensures output flows even if the producer never delivers a first frame.

## Structural Enforcement

This invariant is enforced by **code structure**, not by checks:

```cpp
// PRE-LOOP: Allocate fallback ONCE (no allocation in hot path)
buffer::Frame prealloc_black_frame = CreateBlackFrame();
buffer::Frame last_emitted_frame;
bool have_last_frame = false;

while (!stop_requested && fd >= 0) {
    // INV-TICK-GUARANTEED-OUTPUT: This block is FIRST, UNCONDITIONAL
    if (no_real_frame_available) {
        if (have_last_frame) {
            emit(last_emitted_frame);  // FREEZE
        } else {
            emit(prealloc_black_frame);  // BLACK
        }
        continue;  // Emitted, loop continues
    }

    // Real frame path
    emit(real_frame);
    last_emitted_frame = real_frame;  // Save for freeze
    have_last_frame = true;
}
```

The key structural properties:
1. **Pre-allocated fallback** — No allocation in the hot path
2. **Fallback chain first** — Before any timing/pacing logic
3. **No conditional gates** — Every path through the loop emits exactly one frame
4. **Last frame tracking** — Enables freeze mode

## What This Invariant Supersedes

INV-TICK-GUARANTEED-OUTPUT takes precedence over:

| Lower-Priority Concern | What Happens |
|------------------------|--------------|
| Pacing/timing validation | Emit anyway, log if late |
| CT comparison | Emit anyway, timing is observational |
| Buffer health checks | Emit anyway, diagnostics are read-only |
| Audio sync | Emit video anyway, audio catches up |
| Producer EOF | Emit fallback, not EOF |

## Timing Demotion: Emit-First, Pace-After

All timing-related code has been **demoted from gates to observational**:

**Old approach (RETIRED):**
```cpp
// GATE: Wait until target time, then emit
if (now < target_time) {
    wait_until(target_time);  // BLOCKS emission
}
emit(frame);
```

**New approach (ENFORCED):**
```cpp
// OBSERVATIONAL: Emit immediately, track timing, pace after
emit(frame);  // UNCONDITIONAL
timing_delta = now - target_time;  // Observational metric
if (timing_delta < 0) {
    log("frame early by Xms");  // Counter, not gate
}
sleep(frame_period);  // Post-emission throttle
```

The key insight: **pacing happens AFTER emission**, not before. This ensures:
- Nothing can prevent emission (INV-TICK-GUARANTEED-OUTPUT)
- Transport is never starved waiting for timing
- Late frames are logged but still emitted
- Early frames are throttled (post-emit) but never blocked

## Forbidden Patterns

```cpp
// FORBIDDEN: Conditional emission
if (frame_available && timing_valid) {
    emit(frame);
}

// FORBIDDEN: Wait that can suppress emission
if (frame.pts > now) {
    wait_until(frame.pts);  // Could block indefinitely
}

// FORBIDDEN: Threshold before fallback
if (starvation_ms > 100) {  // 100ms of NO output
    emit(fallback);
}

// FORBIDDEN: Skip on late frame
if (frame.pts < now - tolerance) {
    skip();  // Creates gap in output
}
```

## Allowed Patterns

```cpp
// ALLOWED: Unconditional emission with fallback
frame = get_real() ?? get_freeze() ?? get_black();
emit(frame);  // ALWAYS executes

// ALLOWED: Timing as observation only
if (frame_was_late) {
    log("frame late by Xms");  // Does not affect emission
}

// ALLOWED: Immediate fallback on underrun
if (!have_real_frame) {
    emit(fallback);  // Immediate, no threshold
}
```

## Proof of Correctness

If INV-TICK-GUARANTEED-OUTPUT holds:
- VLC spinning cannot happen (always receiving frames)
- Client-side rebuffering cannot happen (continuous TS)
- Dead air cannot happen (fallback fills gaps)

The invariant directly prevents the "logo → frame → logo" symptom described
in the original bug report.

## Logging

Entry to fallback mode:
```
[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: Entering fallback mode (no real frames), source=freeze|black
```

Periodic fallback status:
```
[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: Fallback frame #N (freeze|black) at PTS=Xus
```

Exit from fallback mode:
```
[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: Exiting fallback mode, real frames available (emitted N fallback frames)
```

## Related Contracts

- `INV-SINK-NO-IMPLICIT-EOF` — Sink continues until explicit stop (downstream of this invariant)
- `LAW-OUTPUT-LIVENESS` — TS must flow continuously (enforced by this invariant)
- `INV-DIAGNOSTIC-ISOLATION` — Diagnostics cannot block emission
- `INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT` — Emit decodable TS within 500ms of AttachStream (derived from this invariant)

## Changelog

- 2025-01: Initial definition (broadcast-grade unconditional emission)
