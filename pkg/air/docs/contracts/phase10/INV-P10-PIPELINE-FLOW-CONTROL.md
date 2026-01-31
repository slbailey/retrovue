# Phase 10 — Pipeline Flow Control (Steady-State Realtime Playout)

_Related: [Phase 9 Output Bootstrap](../phases/Phase9-OutputBootstrap.md) · [Phase 8 Overview](../phases/Phase8-Overview.md)_

**Status:** IMPLEMENTED

**Principle:** After a successful switch (Phase 9), the pipeline must sustain realtime playout indefinitely without frame drops, buffer overruns, or timing drift. Phase 10 defines the flow control invariants that govern producer-consumer relationships during steady-state operation.

Phase 9 is **frozen**. This contract does not modify bootstrap semantics, switching, or initial PCR establishment.

---

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../PlayoutInvariants-BroadcastGradeGuarantees.md)).

---

## 1. Problem Statement

Phase 9 solved the bootstrap problem: getting from segment commit to first observable output with correct timing. However, Phase 9 does not address what happens **after** bootstrap:

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 9 Complete: Switch succeeded, first frames emitted   │
│       ↓                                                     │
│  Producer continues decoding at decode rate                 │
│       ↓                                                     │
│  Consumer (encoder) processes at realtime rate              │
│       ↓                                                     │
│  MISMATCH: decode rate ≠ realtime rate                      │
│       ↓                                                     │
│  Buffer fills (backpressure) OR buffer empties (underrun)   │
│       ↓                                                     │
│  FAILURE: Frame drops, stuttering, or memory exhaustion     │
└─────────────────────────────────────────────────────────────┘
```

**Phase 10 scope:** Ensure the producer-to-consumer pipeline maintains equilibrium during sustained playout, with explicit rules for when frame drops are acceptable and when they are forbidden.

---

## 2. Boundary: Phase 9 vs Phase 10

| Concern | Phase 9 | Phase 10 |
|---------|---------|----------|
| Bootstrap/first frame | ✓ Owns | Does not modify |
| Switch completion | ✓ Owns | Does not modify |
| PCR establishment | ✓ Owns | Does not modify |
| Sustained throughput | — | ✓ Owns |
| Backpressure handling | — | ✓ Owns |
| Producer throttling | — | ✓ Owns |
| Long-running stability | — | ✓ Owns |

Phase 10 begins when:
- Switch is complete (Phase 9 exit criteria met)
- First frame has been emitted to sink
- Silence injection has transitioned to real audio (or silence is stable)

Phase 10 continues until:
- Next switch begins (return to Phase 8/9)
- Channel stops
- EOF reached

---

## 3. Required Invariants

### 3.1 Realtime Throughput Invariant

**INV-P10-REALTIME-THROUGHPUT**: During steady-state playout, the output rate must match the configured frame rate within tolerance.

- Video: Output must emit frames at target FPS ± 1%
- Audio: Sample rate must match configured rate exactly (no drift)
- PTS advancement must be monotonic
- **PTS must remain bounded to MasterClock** with no cumulative drift beyond threshold (100ms) over any 10-second window
- Jitter budget: ≤ 1 frame duration (33ms at 30fps)

**Clock Authority:** MasterClock is the source of truth, not wall clock. PTS correctness is measured against MasterClock, not against instantaneous wall clock readings. This avoids micro-correction policies and preserves PCR authority established in Phase 9. **Authoritative definition of the clock law lives in [PlayoutInvariants-BroadcastGradeGuarantees.md](../PlayoutInvariants-BroadcastGradeGuarantees.md).**

**Measurement:** Over any 10-second window:
- Frame count must equal `target_fps * 10 ± 1`
- `|master_clock_elapsed - pts_elapsed| < 100ms`

### 3.2 Audio/Video Backpressure Symmetry

**INV-P10-BACKPRESSURE-SYMMETRIC**: When backpressure is applied (buffer full), both audio and video must be throttled symmetrically.

- If video buffer is full, producer blocks on video push
- Audio push must also block (or be rate-limited) to prevent A/V desync
- Neither stream may "run ahead" of the other by more than 1 frame duration
- Backpressure must propagate to decoder, not cause frame drops

**Forbidden pattern:**
```
❌ Video blocks on full buffer while audio continues decoding
❌ Audio blocks while video continues
❌ Either stream drops frames due to asymmetric backpressure
```

### 3.2.1 Architectural Rule: Elastic Decode-Level Gating

**RULE-P10-DECODE-GATE**: Flow control must be applied at the earliest admission point (decode/demux), not at push/emit. However, flow control must use **elastic gating with hysteresis** to allow jitter compensation.

This is a **binding architectural rule** that all producers must follow:

```
✅ CORRECT: Elastic gate with bounded decode-ahead
   WaitForDecodeReady()  ← blocks only when buffer > high-water mark
     └── av_read_frame()        (resumes at low-water mark = hysteresis)
           ├── audio packet → decode → push (with retry if needed)
           └── video packet → decode → push (with retry if needed)

❌ WRONG: Hard gate that blocks on any fullness (causes buffer starvation)
   WaitForDecodeReady()  ← blocks immediately when buffer is full
     └── Downstream hiccup drains buffer before decode resumes

❌ WRONG: Gate at push level (causes A/V desync)
   av_read_frame()       ← reads unconditionally
     ├── audio packet → decode → WaitForPushReady() → push
     └── video packet → decode → WaitForPushReady() → push ← audio ran ahead!
```

**Why elastic gating is required:**
- Hard gating (block when full) removes jitter tolerance
- Downstream hiccups cause buffer to drain before decode resumes
- Result: buffer starvation, video stutter, audio silence
- Elastic gating allows bounded decode-ahead (e.g., 3-5 frames) for jitter compensation

**Hysteresis parameters:**
- High-water mark: Block when buffer exceeds (capacity - decode_ahead_budget)
- Low-water mark: Resume when buffer falls below threshold (e.g., 2-3 frames)
- The gap prevents oscillation between blocking and resuming

**The lesson:** Producers must not read/generate new units of work when downstream cannot accept them. Backpressure must be symmetric in time-equivalent units. But BOUNDED ELASTICITY is required for jitter tolerance.

### 3.3 Producer Throttling vs Consumer Capacity

**INV-P10-PRODUCER-THROTTLE**: Producer decode rate must be governed by consumer capacity, not by decoder speed.

- Decode-ahead budget: ≤ N frames (configurable, default 5)
- When buffer depth reaches threshold, producer must yield
- Throttling must not cause decoder stalls or seek penalties

**Bounded Decode Burstiness (Allowed):** The invariant permits bounded decode bursts without violation:
- Disk I/O may deliver frames in bursts (especially at segment boundaries)
- GOP-aligned decode is more efficient than frame-by-frame
- Producer may decode a burst of frames up to the budget, then pause
- This is not a violation as long as buffer depth stays within [1, 2N]

**What IS a violation:**
- Unbounded decode (buffer grows without limit)
- Sustained decode rate > consumer rate for > 10 seconds
- Ignoring backpressure signals

**Mechanism options (implementation chooses one):**
- Blocking push with backpressure
- Semaphore-gated decode loop
- Credit-based flow control

### 3.4 Frame Drop Policy

**INV-P10-FRAME-DROP-POLICY**: Frame drops are forbidden except under explicit conditions.

**Drops FORBIDDEN when:**
- Buffer has capacity (not full)
- Consumer is keeping up with realtime
- No seek or switch in progress
- No external resource starvation (disk I/O, network)

**Drops ALLOWED when:**
- Buffer is full AND consumer is behind realtime
- Explicit seek/discontinuity requested
- Switch is in progress (Phase 9 takes over)
- System overload detected (CPU > threshold)

**When drops occur:**
- Must drop entire GOP (not partial)
- Must log: `INV-P10-FRAME-DROP: reason=<reason>, dropped=<count>, buffer_depth=<n>`
- Must update metric: `retrovue_frames_dropped_total`
- Audio and video must drop together (A/V sync preserved)

### 3.5 Buffer Equilibrium

**INV-P10-BUFFER-EQUILIBRIUM**: Buffer depth must oscillate around a target, not grow unbounded or drain to zero.

- Target depth: N frames (configurable, default 3)
- Allowed range: [1, 2N] frames
- If depth < 1: underrun imminent, log warning
- If depth > 2N: overrun imminent, apply backpressure

**Time-Equivalent Units:** Buffer depth invariants are defined in **time-equivalent units**, even if implemented as frame counts. This ensures audio and video are measured consistently:
- Video: 1 frame at 30fps = 33.3ms
- Audio: 1024 samples at 48kHz = 21.3ms
- Target depth of "3 frames" means ~100ms of video OR equivalent audio duration
- A/V balance is measured by time buffered, not raw frame counts

This prevents situations where "video has 2 frames but audio has 200ms buffered" — both must be expressed as time-equivalent for comparison.

**Forbidden patterns:**
```
❌ Buffer grows monotonically (memory leak)
❌ Buffer drains to 0 during normal playback (stuttering)
❌ Buffer oscillates wildly (bursty decode/encode)
❌ Audio and video buffered durations diverge by > 1 frame duration
```

---

## 4. Philosophical Alignment (Design Decisions)

These decisions are **locked** and must not be reconsidered during Phase 10 implementation:

### 4.0 DOCTRINE: Elastic Buffering is Mandatory

> **"Zero dropped frames requires elastic buffering.**
> **Hard synchronization without jitter tolerance is a bug."**

This is the **cardinal rule** of Phase 10 flow control. It was learned through painful experience:

**The failure mode:** Hard gating (block immediately when buffer is full) removes jitter tolerance. When downstream has any hiccup, the buffer drains before decode can resume. Result: buffer starvation, video stutter, audio silence.

**The solution:** Elastic buffering with hysteresis. Allow bounded decode-ahead (e.g., 5 frames). Block only at high-water mark. Resume at low-water mark. This absorbs downstream jitter while still bounding memory growth.

**Why this matters for future producers:**
- Synthetic producers (Prevue, Weather, Emergency) don't need FFmpeg timing tricks
- They just obey the same buffer + CT rules
- They inherit jitter tolerance for free
- No special-casing per producer type

**Corollary rules:**
- Never gate on "buffer is full" — gate on "buffer exceeds high-water mark"
- Never resume on "buffer has space" — resume on "buffer below low-water mark"
- The gap between thresholds (hysteresis) is load-bearing, not optional


### 4.1 MasterClock is Authoritative

- All timing is measured against MasterClock, not wall clock
- PTS correctness means "bounded to MasterClock", not "equals wall clock at every instant"
- Phase 9 established PCR authority; Phase 10 must not undermine it

### 4.2 No Micro-Corrections

- PTS values are deterministic and never "nudged"
- No adaptive rate shifting, time-warping, or speed adjustment
- Drift indicates a bug, not a condition to paper over
- If drift exceeds threshold, escalate (rebootstrap), don't compensate

### 4.3 Broadcast-Like Determinism

- Same input + same MasterClock = same output
- No probabilistic or adaptive behaviors
- Frame drops are explicit, logged, and symmetric

### 4.4 Bounded Decode Burstiness is Acceptable

- Disk I/O and GOP alignment may cause decode bursts
- Bursts are fine as long as buffer stays in equilibrium range
- "Just-in-time decode" is a goal, not a micro-requirement
- Producer may decode ahead up to budget, pause, repeat

---

## 5. Non-Goals (Explicitly Out of Scope)

Phase 10 does **not** address:

- **Switching semantics** — Frozen per Phase 8/9
- **Bootstrap timing** — Frozen per Phase 9
- **PCR ownership rules** — Frozen per Phase 9
- **Multi-channel orchestration** — Core's responsibility
- **Adaptive bitrate** — Future phase
- **Quality degradation under load** — Future phase
- **Network congestion handling** — Sink's responsibility

---

## 6. Failure Modes

### 6.1 Underrun (Buffer Drains)

**Symptom:** Output stutters, VLC pauses/buffers
**Cause:** Consumer faster than producer, or producer stall
**Detection:** `buffer_depth < 1` for > 1 frame duration
**Recovery:** Producer catches up, silence injection bridges gap

**Note:** Silence injection behavior is defined in Phase 9 (INV-P9-AUDIO-LIVENESS) and is only *observed* here, not *controlled*. Phase 10 does not modify silence injection policy.

### 6.2 Overrun (Buffer Fills)

**Symptom:** Memory grows, latency increases
**Cause:** Producer faster than consumer (decode > realtime)
**Detection:** `buffer_depth > 2N` threshold
**Recovery:** Backpressure throttles producer

### 6.3 A/V Desync

**Symptom:** Lip sync issues, audio leads/lags video
**Cause:** Asymmetric backpressure or frame drops
**Detection:** `|audio_pts - video_pts| > threshold` (e.g., 100ms)
**Recovery:** Coordinated drop to resync, or wait for natural catchup

### 6.4 Timing Drift

**Symptom:** Playback gradually speeds up or slows down
**Cause:** Clock domain mismatch, PTS calculation error
**Detection:** `|master_clock_elapsed - pts_elapsed| > threshold`

**Recovery (in order of preference):**
1. **Detection + logging** — Record drift for diagnosis
2. **Natural convergence** — Allow pipeline to self-correct via backpressure/throttle
3. **Controlled escalation** — If drift exceeds hard threshold (e.g., 500ms), trigger rebootstrap

**Forbidden recovery patterns:**
```
❌ Micro-PTS corrections (nudging timestamps)
❌ Adaptive rate shifting
❌ Time-warping or speed adjustment
```

These are forbidden because they conflict with Phase 9's PCR authority and broadcast-like determinism. Drift indicates a bug to fix, not a condition to paper over.

---

## 7. Logging Requirements

Phase 10 requires these log lines for debugging:

```
INV-P10-STEADY-STATE: entered (buffer_depth=N, fps=30.0)
INV-P10-BACKPRESSURE: applied (buffer_depth=N, threshold=M)
INV-P10-BACKPRESSURE: released (buffer_depth=N)
INV-P10-UNDERRUN: warning (buffer_depth=0, duration_ms=X)
INV-P10-FRAME-DROP: reason=<reason>, dropped=<N>, buffer_depth=<M>
INV-P10-DESYNC: detected (audio_pts=X, video_pts=Y, delta_ms=Z)
```

---

## 8. Metrics Requirements

Phase 10 requires these metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `retrovue_buffer_depth_frames` | Gauge | Current buffer depth (video frames) |
| `retrovue_buffer_depth_target` | Gauge | Target buffer depth |
| `retrovue_buffer_depth_ms` | Gauge | Current buffer depth in milliseconds (optional, supports time-equivalent invariants) |
| `retrovue_frames_produced_total` | Counter | Frames decoded by producer |
| `retrovue_frames_consumed_total` | Counter | Frames encoded/emitted |
| `retrovue_frames_dropped_total` | Counter | Frames intentionally dropped |
| `retrovue_backpressure_events_total` | Counter | Backpressure activations |
| `retrovue_underrun_events_total` | Counter | Buffer underrun events |
| `retrovue_av_desync_events_total` | Counter | A/V desync detections |
| `retrovue_output_fps_actual` | Gauge | Measured output FPS |

---

## 9. Proposed Tests (Not Yet Implemented)

The following tests would prove Phase 10 compliance. Implementation deferred until contract is accepted.

### TEST-P10-REALTIME-THROUGHPUT-001: Sustained FPS

**Given:** Channel playing for 60 seconds
**When:** Frame output is counted
**Then:** Output FPS matches target ± 1%
**And:** No underrun events logged

### TEST-P10-REALTIME-THROUGHPUT-002: PTS Bounded to MasterClock

**Given:** Channel playing for 60 seconds
**When:** Final PTS compared to MasterClock elapsed
**Then:** Difference < 100ms
**And:** No micro-corrections were applied (PTS values are deterministic)

### TEST-P10-BACKPRESSURE-001: Producer Throttled When Buffer Full

**Given:** Consumer artificially slowed (encode delay injected)
**When:** Buffer reaches threshold
**Then:** Producer decode rate decreases
**And:** No frame drops occur
**And:** Buffer depth stabilizes below maximum

### TEST-P10-BACKPRESSURE-002: Audio and Video Throttled Together

**Given:** Backpressure applied
**When:** Measured over 10 seconds
**Then:** `|audio_frames_produced - video_frames_produced| ≤ 1`

### TEST-P10-FRAME-DROP-001: No Drops Under Normal Load

**Given:** Channel playing for 60 seconds with adequate CPU
**When:** Frame drop counter checked
**Then:** `retrovue_frames_dropped_total = 0`

### TEST-P10-FRAME-DROP-002: Drops Are Symmetric

**Given:** Artificial overload causing drops
**When:** Drops occur
**Then:** Audio and video dropped together
**And:** A/V sync maintained after recovery

### TEST-P10-EQUILIBRIUM-001: Buffer Depth Stable

**Given:** Channel playing for 60 seconds
**When:** Buffer depth sampled every second
**Then:** All samples in range [1, 2N]
**And:** Standard deviation < N/2

### TEST-P10-LONG-RUNNING-001: 10-Minute Stability

**Given:** Channel playing for 10 minutes
**Then:** No underruns
**And:** No memory growth > 10%
**And:** No frame drops (normal conditions)
**And:** A/V sync maintained throughout

---

## 10. Exit Criteria

Phase 10 is complete when:

1. **Sustained throughput**: 60-second playback at target FPS ± 1%
2. **No drops under normal load**: `frames_dropped = 0` for 60 seconds
3. **Backpressure works**: Producer throttles when buffer full, no drops
4. **Symmetric handling**: Audio and video always handled together
5. **Long-running stable**: 10-minute playback without regression
6. **Metrics exposed**: All required metrics available at `/metrics`
7. **No Phase 9 regressions**: All Phase 9 tests still pass

---

## 10.1 Producer Template Contract

All producers (FileProducer, PrevueProducer, WeatherProducer, EmergencyProducer, etc.) must follow this flow control contract.

### DOCTRINE (Read This First)

> **"Zero dropped frames requires elastic buffering.**
> **Hard synchronization without jitter tolerance is a bug."**

Do NOT implement hard gating. Do NOT block when buffer is merely "full". Use elastic flow control with hysteresis (high-water/low-water marks). This is non-negotiable.

### Mandatory Requirements

1. **Producers must not read/generate new units of work when downstream cannot accept them.**
   - Flow control gate BEFORE packet read/frame generation
   - NOT at push/emit level
   - **BUT: Use ELASTIC gating, not hard gating** (see doctrine above)

2. **Backpressure must be symmetric in time-equivalent units.**
   - Audio and video gated together
   - Neither stream may "run ahead" during backpressure

3. **No hidden queues between decode and push.**
   - All work generated must be immediately pushable
   - No internal buffering that bypasses flow control

4. **Video through TimelineController; audio uses sample clock.**
   - Video: call `AdmitFrame()` for each frame to get CT
   - Audio: call `AdmitFrame()` for FIRST frame only (origin CT)
   - Audio subsequent frames: `ct += (samples * 1_000_000) / sample_rate`
   - That's it. No adjustments. No nudging. No repairs.

5. **Audio time is SIMPLE (non-negotiable).**

   What to KEEP:
   - TimelineController sets origin CT (first frame only)
   - Sample clock advances time: `ct += sample_duration`
   - Monotonicity guard only if time goes backwards: `if (ct < last) ct = last`

   What is FORBIDDEN:
   - ❌ No `<=` comparison (equality is fine)
   - ❌ No `+1µs` nudging
   - ❌ No per-frame "adjustments" or "repairs"
   - ❌ No "Audio PTS adjusted" logic

   Why this is safe:
   - Audio clock is inherently monotonic (sample counter)
   - Sample duration defines cadence, not frame-by-frame fixups
   - Video jitter does NOT affect audio slope
   - PCR (audio-master) must free-run continuously
   - This is how real broadcast chains work

6. **INV-P10-PRODUCER-CT-AUTHORITATIVE: Muxer must use producer-provided CT.**

   The producer computes correct CT via TimelineController and sample clock.
   The muxer MUST use `audio_frame.pts_us` directly — no local counters.

   What is FORBIDDEN:
   - ❌ `int64_t audio_ct_us = 0;` — Never reset CT to 0 in muxer
   - ❌ Ignoring `audio_frame.pts_us` from producer
   - ❌ Maintaining a separate CT counter that shadows the producer's

   Why this matters:
   - Producer CT may start at hours into channel playback (not 0)
   - Muxer resetting to 0 causes audio freeze / A/V desync
   - Producer owns timeline truth; muxer is a pass-through

7. **INV-P10-PCR-PACED-MUX: Mux loop must be time-driven, not availability-driven.**

   The mux loop emits frames at their scheduled CT, not as fast as possible.
   This prevents buffer oscillation and ensures smooth playback.

   Algorithm:
   1. Peek at next video frame to get its CT
   2. Wait until wall clock matches that CT
   3. Dequeue and encode exactly ONE video frame
   4. Dequeue and encode all audio with CT ≤ video CT
   5. Repeat

   What is FORBIDDEN:
   - ❌ Draining loops ("while queue not empty → emit")
   - ❌ Burst writes (emit as fast as possible)
   - ❌ Adaptive speed-up / slow-down
   - ❌ Dropping frames to catch up

   Why this matters:
   - Availability-driven mux causes buffer saw-tooth oscillation
   - High-water / low-water gates fire repeatedly
   - Bursty delivery causes VLC stutter and audio clicks
   - PCR-paced emission produces smooth, steady output

8. **INV-P10-NO-SILENCE-INJECTION: Audio liveness must be disabled when PCR-paced mux is active.**

   When MpegTSOutputSink starts with PCR-paced mux, silence injection is permanently disabled.
   Producer audio is the ONLY audio source. No competing audio streams.

   What is FORBIDDEN:
   - ❌ Silence injection once PCR pacing starts
   - ❌ "Audio missing" heuristics
   - ❌ Fallback audio
   - ❌ Speculative silence
   - ❌ Any fabricated audio

   Correct behavior when audio queue is empty:
   - Mux loop stalls (does not emit video either)
   - Video and audio wait together
   - PCR only advances from real audio

   Why this matters:
   - Competing audio sources cause PTS discontinuities
   - VLC drops/mutes audio, then video freezes
   - PCR becomes inconsistent
   - Audio liveness was designed for Phase 9 bootstrap, not steady-state

### Common Flow Control Primitive

All producers should share a common flow control pattern:

```cpp
// RULE-P10-DECODE-GATE pattern (pseudocode)
bool WaitForProduceReady() {
    while (!CanPush()) {
        if (stop_requested || write_barrier) return false;
        log_once("Blocking at produce level");
        yield_or_sleep();
    }
    log_if_was_blocked("Released");
    return true;
}

// Production loop
while (!stop) {
    if (!WaitForProduceReady()) break;  // Gate BEFORE work
    GenerateWork();                      // Read packet / generate frame
    Push();                              // Guaranteed to succeed
}
```

### Metrics

All producers should expose:
- `retrovue_decode_gate_events_total` — Count of backpressure episodes
- `retrovue_frames_produced_total` — Total frames produced

---

## 11. Implementation Notes (Guidance, Not Prescription)

These are suggestions for implementation, not requirements:

### Backpressure Mechanism

The simplest approach is blocking push with timeout:
```cpp
bool pushed = false;
while (!pushed && !stop_requested) {
    pushed = ring_buffer.TryPush(frame, timeout_ms);
    if (!pushed) {
        // Backpressure: buffer full, yield
        std::this_thread::sleep_for(1ms);
    }
}
```

### Throttle Coordination

Audio and video throttling can share a semaphore or credit pool to ensure symmetry.

### Drop Decision

When drops are necessary:
1. Check if both A/V buffers can drop a GOP
2. Drop atomically (both streams, same PTS range)
3. Log with reason
4. Resume after drop

---

## 12. Relation to Other Phases

| Phase | Concern | Phase 10 Dependency |
|-------|---------|---------------------|
| Phase 8 | Timeline/commit | Consumes commit signals |
| Phase 9 | Bootstrap/first frame | Begins after Phase 9 exits |
| Phase 10 | Sustained playout | **This phase** |
| Phase 11+ | (Future) | May extend flow control |

---

## 13. Acceptance Criteria

This contract is accepted when:

1. All stakeholders agree on invariant definitions
2. Test specifications are deemed sufficient
3. No conflicts with Phase 8/9 semantics identified
4. Implementation path is clear

**Phase 10 implementation may not begin until this contract is accepted.**
