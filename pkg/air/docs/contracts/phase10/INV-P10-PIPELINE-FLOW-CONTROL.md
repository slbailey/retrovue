# Phase 10 — Pipeline Flow Control (Steady-State Realtime Playout)

_Related: [Phase 9 Output Bootstrap](../phases/Phase9-OutputBootstrap.md) · [Phase 8 Overview](../phases/Phase8-Overview.md)_

**Status:** PROPOSED (not yet implemented)

**Principle:** After a successful switch (Phase 9), the pipeline must sustain realtime playout indefinitely without frame drops, buffer overruns, or timing drift. Phase 10 defines the flow control invariants that govern producer-consumer relationships during steady-state operation.

Phase 9 is **frozen**. This contract does not modify bootstrap semantics, switching, or initial PCR establishment.

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

**Clock Authority:** MasterClock is the source of truth, not wall clock. PTS correctness is measured against MasterClock, not against instantaneous wall clock readings. This avoids micro-correction policies and preserves PCR authority established in Phase 9.

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

### 3.3 Producer Throttling vs Consumer Capacity

**INV-P10-PRODUCER-THROTTLE**: Producer decode rate must be governed by consumer capacity, not by decoder speed.

- Decode-ahead budget: ≤ N frames (configurable, default 5)
- When buffer depth reaches threshold, producer must yield
- Throttling must not cause decoder stalls or seek penalties
- Throttling must be smooth (not bursty)

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

## 4. Non-Goals (Explicitly Out of Phase 10 Scope)

Phase 10 does **not** address:

- **Switching semantics** — Frozen per Phase 8/9
- **Bootstrap timing** — Frozen per Phase 9
- **PCR ownership rules** — Frozen per Phase 9
- **Multi-channel orchestration** — Core's responsibility
- **Adaptive bitrate** — Future phase
- **Quality degradation under load** — Future phase
- **Network congestion handling** — Sink's responsibility

---

## 5. Failure Modes

### 5.1 Underrun (Buffer Drains)

**Symptom:** Output stutters, VLC pauses/buffers
**Cause:** Consumer faster than producer, or producer stall
**Detection:** `buffer_depth < 1` for > 1 frame duration
**Recovery:** Producer catches up, silence injection bridges gap

### 5.2 Overrun (Buffer Fills)

**Symptom:** Memory grows, latency increases
**Cause:** Producer faster than consumer (decode > realtime)
**Detection:** `buffer_depth > 2N` threshold
**Recovery:** Backpressure throttles producer

### 5.3 A/V Desync

**Symptom:** Lip sync issues, audio leads/lags video
**Cause:** Asymmetric backpressure or frame drops
**Detection:** `|audio_pts - video_pts| > threshold` (e.g., 100ms)
**Recovery:** Coordinated drop to resync, or wait for natural catchup

### 5.4 Timing Drift

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

## 6. Logging Requirements

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

## 7. Metrics Requirements

Phase 10 requires these metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `retrovue_buffer_depth_frames` | Gauge | Current buffer depth |
| `retrovue_buffer_depth_target` | Gauge | Target buffer depth |
| `retrovue_frames_produced_total` | Counter | Frames decoded by producer |
| `retrovue_frames_consumed_total` | Counter | Frames encoded/emitted |
| `retrovue_frames_dropped_total` | Counter | Frames intentionally dropped |
| `retrovue_backpressure_events_total` | Counter | Backpressure activations |
| `retrovue_underrun_events_total` | Counter | Buffer underrun events |
| `retrovue_av_desync_events_total` | Counter | A/V desync detections |
| `retrovue_output_fps_actual` | Gauge | Measured output FPS |

---

## 8. Proposed Tests (Not Yet Implemented)

The following tests would prove Phase 10 compliance. Implementation deferred until contract is accepted.

### TEST-P10-REALTIME-THROUGHPUT-001: Sustained FPS

**Given:** Channel playing for 60 seconds
**When:** Frame output is counted
**Then:** Output FPS matches target ± 1%
**And:** No underrun events logged

### TEST-P10-REALTIME-THROUGHPUT-002: PTS Matches Wall Clock

**Given:** Channel playing for 60 seconds
**When:** Final PTS compared to wall clock elapsed
**Then:** Difference < 100ms

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

## 9. Exit Criteria

Phase 10 is complete when:

1. **Sustained throughput**: 60-second playback at target FPS ± 1%
2. **No drops under normal load**: `frames_dropped = 0` for 60 seconds
3. **Backpressure works**: Producer throttles when buffer full, no drops
4. **Symmetric handling**: Audio and video always handled together
5. **Long-running stable**: 10-minute playback without regression
6. **Metrics exposed**: All required metrics available at `/metrics`
7. **No Phase 9 regressions**: All Phase 9 tests still pass

---

## 10. Implementation Notes (Guidance, Not Prescription)

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

## 11. Relation to Other Phases

| Phase | Concern | Phase 10 Dependency |
|-------|---------|---------------------|
| Phase 8 | Timeline/commit | Consumes commit signals |
| Phase 9 | Bootstrap/first frame | Begins after Phase 9 exits |
| Phase 10 | Sustained playout | **This phase** |
| Phase 11+ | (Future) | May extend flow control |

---

## 12. Acceptance Criteria

This contract is accepted when:

1. All stakeholders agree on invariant definitions
2. Test specifications are deemed sufficient
3. No conflicts with Phase 8/9 semantics identified
4. Implementation path is clear

**Phase 10 implementation may not begin until this contract is accepted.**
