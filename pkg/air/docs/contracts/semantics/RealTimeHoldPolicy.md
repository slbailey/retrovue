# RealTimeHold: No-Drop, Freeze-Then-Pad Timing Policy

**ID:** INV-PACING-ENFORCEMENT-002  
**Status:** Canonical  
**Owner:** ProgramOutput  
**Applies to:** All real-time playout paths (live, preview, air)

**Related:** [INV-PACING-001](PrimitiveInvariants.md) · [PlayoutInvariants-BroadcastGradeGuarantees](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)

---

## 1. Authoritative timing rule

The render loop **SHALL** emit at most one frame per frame period.

The render loop **SHALL NOT** emit frames faster than real time.

Wall-clock (or MasterClock) is the sole pacing authority.

This is the hard guardrail that enforces INV-PACING-001.

---

## 2. Late frame handling (no frame drops allowed)

When the render loop reaches a frame deadline and no new real frame is available:

### Phase A — Freeze (Primary Response)

The system **SHALL** re-emit the last successfully emitted real frame.

This freeze is considered intentional and on-time with respect to the playout clock, even though content production is late.

- Frame cadence remains correct (still exactly one frame per period).
- Audio continues uninterrupted.

**Freeze window:**

- Maximum continuous freeze duration: **250 ms** (configurable, default).

**Rationale:**

- Short freezes are perceptually preferable to black or time distortion.
- Maintains continuity during brief decode or seek gaps.

### Phase B — Pad (Secondary Response)

If the freeze window is exceeded and no real frame becomes available:

The system **SHALL** emit pad frames (black/slate) at normal cadence.

- Pad emission remains paced (no bursts).
- Audio continues uninterrupted unless explicitly configured otherwise.

**Rationale:**

- Prevents indefinite visual stalling.
- Makes prolonged failure visible without violating timing invariants.

---

## 3. Explicit prohibitions

The system **SHALL NOT**:

- Emit frames faster than real time to “catch up”
- Drop or skip real frames
- Advance PTS faster than wall-clock time
- Emit bursts of pad frames
- Mask lateness by compressing time

---

## 4. Observability & diagnostics (mandatory)

The following **MUST** be exposed as first-class telemetry:

| Metric | Meaning |
|--------|---------|
| `frame_lateness_ms` | now − deadline per frame |
| `freeze_frames` | Count of freeze re-emissions |
| `freeze_duration_ms` | Continuous freeze time |
| `pad_frames` | Pad frames emitted after freeze window |
| `late_events` | Count of missed deadlines |
| `max_freeze_streak_frames` | Longest consecutive freeze run |

### Canonical log signals

```
INV-PACING-002: FREEZE frame=N lateness=XXms
INV-PACING-002: PAD after freeze window exceeded (YYYms)
INV-PACING-002: RECOVERED real frame available
```

This keeps the system honest instead of “self-healing silently.”

---

## 5. Interaction with other invariants

| Invariant | Effect under this policy |
|-----------|--------------------------|
| INV-PACING-001 | Fully enforced |
| INV-DECODE-RATE-001 | Manifests as freeze/pad pressure, not timing collapse |
| INV-SEGMENT-CONTENT-001 | Results in pad after freeze window |
| Audio sync | Preserved in time, not frame count |

---

## 6. Professional precedent (why this is “real”)

This policy matches how professional systems behave:

- **Broadcast automation:** freeze on decode hiccup, then slate
- **SDI playout chains:** never compress time
- **Graphics engines:** hold last frame under load
- **Live control rooms:** continuity over illusion

The guiding principle is:

> **Time is sacred. Frames may wait.**

---

## 7. Final policy summary

The playout engine **SHALL** enforce real-time pacing without frame drops. When late, it **SHALL** freeze the last emitted frame for a bounded window, then emit pad frames if necessary, while maintaining continuous audio and honest timing telemetry. Under no circumstances **SHALL** it accelerate output or skip frames to recover from lateness.
