# Layer 2 - Phase 10 Pipeline Flow Control Invariants

**Status:** Canonical
**Scope:** Steady-state realtime playout, backpressure, producer throttling, buffer equilibrium
**Authority:** Refines Layer 0 Laws; does not override Phase 9 semantics

Phase 9 is **frozen**. This contract does not modify bootstrap semantics, switching, or initial PCR establishment.

---

## Phase 10 Coordination Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-P10-BACKPRESSURE-SYMMETRIC** | CONTRACT | FileProducer, FrameRingBuffer | P10 | No | Yes |
| **INV-P10-PRODUCER-THROTTLE** | CONTRACT | FileProducer | P10 | No | Yes |
| **INV-P10-BUFFER-EQUILIBRIUM** | CONTRACT | FrameRingBuffer | P10 | No | Yes |
| **INV-P10-NO-SILENCE-INJECTION** | CONTRACT | MpegTSOutputSink | P10 | No | No |
| **INV-P10-SINK-GATE** | CONTRACT | ProgramOutput | P10 | No | No |
| **INV-OUTPUT-READY-BEFORE-LIVE** | CONTRACT | ChannelManager (Core) | P10 | No | Yes |
| **INV-SWITCH-READINESS** | CONTRACT | PlayoutEngine | P10 | No | Yes |
| **INV-SWITCH-SUCCESSOR-EMISSION** | CONTRACT | TimelineController | P10 | Yes | Yes |
| **RULE-P10-DECODE-GATE** | CONTRACT | FileProducer | P10 | No | Yes |
| **INV-P10-AUDIO-VIDEO-GATE** | CONTRACT | FileProducer | P10 | No | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P10-BACKPRESSURE-SYMMETRIC | When buffer full, both audio and video throttled symmetrically. **Audio samples MUST NOT be dropped due to queue backpressure; overflow MUST cause producer throttling.** |
| INV-P10-PRODUCER-THROTTLE | Producer decode rate governed by consumer capacity, not decoder speed |
| INV-P10-BUFFER-EQUILIBRIUM | Buffer depth oscillates around target, not unbounded or zero |
| INV-P10-NO-SILENCE-INJECTION | Audio liveness disabled when PCR-paced mux active |
| INV-P10-SINK-GATE | ProgramOutput must not consume frames before sink attached. **Clarification:** This gate exists solely to prevent buffer drain before routing is possible. It does not condition broadcast correctness or emission semantics on sink presence. Frames flow unconditionally once routing is established; absence of sink results in legal discard, not emission suppression. |
| INV-OUTPUT-READY-BEFORE-LIVE | **(Core only)** Core must not declare channel LIVE until output pipeline is observable. AIR exposes readiness signals; Core decides LIVE state. LIVE is a Core lifecycle state, not an AIR broadcast state. |
| INV-SWITCH-READINESS | **DIAGNOSTIC GOAL:** Switch SHOULD have video >=2, sink attached, format locked. *(Superseded by INV-SWITCH-DEADLINE-AUTHORITATIVE-001 for completion semantics)* |
| INV-SWITCH-SUCCESSOR-EMISSION | **DIAGNOSTIC GOAL:** Real successor video frame SHOULD be emitted at switch. *(Superseded by INV-SWITCH-DEADLINE-AUTHORITATIVE-001 for completion semantics)* |
| RULE-P10-DECODE-GATE | Slot-based gating at decode level; block at capacity, unblock when one slot frees |
| INV-P10-AUDIO-VIDEO-GATE | When segment video epoch is established, first audio frame MUST be queued within 100ms |

---

## DOCTRINE: Slot-Based Flow Control

> **"Slot-based flow control eliminates sawtooth stuttering.**
> **Hysteresis with low-water drain is the pattern that causes bursty delivery."**

This is the **cardinal rule** of Phase 10 flow control.

**The failure mode:** Hysteresis gating (block at high-water, resume at low-water of 2 frames) creates a sawtooth pattern:
1. Buffer fills to high-water -> producer blocks
2. Consumer drains buffer down to 2 frames
3. Producer unblocks and frantically refills
4. Repeat -> bursty delivery -> VLC stutter -> audio clicks

**The solution:** Slot-based gating. Block only at capacity. Unblock when one slot frees. Producer and consumer flow in lockstep when buffer is full. No draining phase.

**Corollary rules:**
- Block only at capacity - not at "high-water mark"
- Resume immediately when one slot frees - not at "low-water mark"
- No hysteresis gap - immediate unblock maintains steady flow

---

## Detailed Invariant Definitions

### RULE-P10-DECODE-GATE

**Flow control must be applied at the earliest admission point (decode/demux), not at push/emit.**

Flow control uses **slot-based gating** (block at capacity, unblock when one slot frees) to maintain smooth producer-consumer flow.

```
CORRECT: Slot-based gate
   WaitForDecodeReady()  <- blocks only when buffer is at capacity
     |-- av_read_frame()        (resumes when one slot frees)
           |-- audio packet -> decode -> push (with retry if needed)
           |-- video packet -> decode -> push (with retry if needed)

WRONG: Hysteresis with low-water mark (causes sawtooth stutter)
   WaitForDecodeReady()  <- blocks at high-water, waits for low-water
     |-- Fill to high-water -> hard stop -> drain to 2 frames -> frantic refill

WRONG: Gate at push level (causes A/V desync)
   av_read_frame()       <- reads unconditionally
     |-- audio packet -> decode -> WaitForPushReady() -> push
     |-- video packet -> decode -> WaitForPushReady() -> push <- audio ran ahead!
```

---

### INV-P10-BACKPRESSURE-SYMMETRIC

**When backpressure is applied (buffer full), both audio and video must be throttled symmetrically.**

- If video buffer is full, producer blocks on video push
- Audio push must also block (or be rate-limited) to prevent A/V desync
- Neither stream may "run ahead" of the other by more than 1 frame duration
- Backpressure must propagate to decoder, not cause frame drops

**Forbidden pattern:**
- Video blocks on full buffer while audio continues decoding
- Audio blocks while video continues
- Either stream drops frames due to asymmetric backpressure

---

### INV-P10-PRODUCER-THROTTLE

**Producer decode rate must be governed by consumer capacity, not by decoder speed.**

- Decode-ahead budget: <= N frames (configurable, default 5)
- When buffer depth reaches threshold, producer must yield
- Throttling must not cause decoder stalls or seek penalties

**Bounded Decode Burstiness (Allowed):**
- Disk I/O may deliver frames in bursts (especially at segment boundaries)
- GOP-aligned decode is more efficient than frame-by-frame
- Producer may decode a burst of frames up to the budget, then pause
- This is not a violation as long as buffer depth stays within [1, 2N]

---

### INV-P10-BUFFER-EQUILIBRIUM

**Buffer depth must oscillate around a target, not grow unbounded or drain to zero.**

- Target depth: N frames (configurable, default 3)
- Allowed range: [1, 2N] frames
- If depth < 1: underrun imminent, log warning
- If depth > 2N: overrun imminent, apply backpressure

**Time-Equivalent Units:** Buffer depth invariants are defined in **time-equivalent units**:
- Video: 1 frame at 30fps = 33.3ms
- Audio: 1024 samples at 48kHz = 21.3ms
- Target depth of "3 frames" means ~100ms of video OR equivalent audio duration

---

### INV-P10-SINK-GATE

**ProgramOutput must not consume frames before an output sink is attached.**

**Ownership Clarification:** This gate exists solely to prevent buffer drain before routing is possible. It does NOT condition broadcast correctness or emission semantics on sink presence.

This prevents buffer starvation during the window between `StartChannel` and `AttachStream`:
- Without this gate, frames are popped but not routed anywhere
- Buffer drains without pacing, causing underrun before playback even begins
- Gate pauses frame consumption until OutputBus is connected

**What this invariant is NOT:**
- NOT an observer-gated output mechanism
- NOT a visibility gate
- NOT a broadcast correctness condition

Once routing is established, frames flow unconditionally. Absence of sink results in legal discard at OutputBus, not emission suppression at ProgramOutput.

---

### INV-OUTPUT-READY-BEFORE-LIVE

**Owner:** Core (ChannelManager)

**Core MUST NOT declare a channel LIVE until the output pipeline is observable.**

**Ownership Clarification:** LIVE is a Core lifecycle state, not an AIR broadcast state. AIR exposes readiness signals (buffer depth, sink attachment status); Core decides when to transition to LIVE. AIR never decides "LIVE" — it only reports conditions.

- **LIVE** means "Core has declared the output pipeline observable"
- **NOT_READY** means "Core has not yet declared LIVE"

**Binding Rules (Core):**
- Core queries AIR readiness via Protocol
- Core transitions boundary state to LIVE when conditions are met
- AIR does not autonomously enter or declare LIVE state
- If buffer is ready but sink is not attached, remain in NOT_READY state

---

## Producer Template Contract

All producers (FileProducer, PrevueProducer, WeatherProducer, EmergencyProducer, etc.) must follow this flow control contract.

### Mandatory Requirements

1. **Producers must not read/generate new units of work when downstream cannot accept them.**
   - Flow control gate BEFORE packet read/frame generation
   - NOT at push/emit level
   - **Use SLOT-BASED gating** (block at capacity, unblock when one slot frees)
   - **Do NOT use hysteresis** (no low-water drain)

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

5. **Audio time is SIMPLE (non-negotiable).**

   What to KEEP:
   - TimelineController sets origin CT (first frame only)
   - Sample clock advances time: `ct += sample_duration`
   - Monotonicity guard only if time goes backwards

   What is FORBIDDEN:
   - No `<=` comparison (equality is fine)
   - No `+1us` nudging
   - No per-frame "adjustments" or "repairs"
   - No "Audio PTS adjusted" logic

6. **INV-P10-PRODUCER-CT-AUTHORITATIVE: Muxer must use producer-provided CT.**

   What is FORBIDDEN:
   - `int64_t audio_ct_us = 0;` - Never reset CT to 0 in muxer
   - Ignoring `audio_frame.pts_us` from producer
   - Maintaining a separate CT counter that shadows the producer's

7. **INV-P10-PCR-PACED-MUX: Mux loop must be time-driven, not availability-driven.**

   Algorithm:
   1. Peek at next video frame to get its CT
   2. Wait until wall clock matches that CT
   3. Dequeue and encode exactly ONE video frame
   4. Dequeue and encode all audio with CT <= video CT
   5. Repeat

   What is FORBIDDEN:
   - Draining loops ("while queue not empty -> emit")
   - Burst writes (emit as fast as possible)
   - Adaptive speed-up / slow-down
   - Dropping frames to catch up

---

## Failure Modes

### Underrun (Buffer Drains)

**Symptom:** Output stutters, VLC pauses/buffers
**Cause:** Consumer faster than producer, or producer stall
**Detection:** `buffer_depth < 1` for > 1 frame duration
**Recovery:** Producer catches up, silence injection bridges gap

### Overrun (Buffer Fills)

**Symptom:** Memory grows, latency increases
**Cause:** Producer faster than consumer (decode > realtime)
**Detection:** `buffer_depth > 2N` threshold
**Recovery:** Backpressure throttles producer

### A/V Desync

**Symptom:** Lip sync issues, audio leads/lags video
**Cause:** Asymmetric backpressure or frame drops
**Detection:** `|audio_pts - video_pts| > threshold` (e.g., 100ms)
**Recovery:** Coordinated drop to resync, or wait for natural catchup

### Timing Drift

**Symptom:** Playback gradually speeds up or slows down
**Cause:** Clock domain mismatch, PTS calculation error
**Detection:** `|master_clock_elapsed - pts_elapsed| > threshold`
**Recovery:** Detection + logging; natural convergence; controlled escalation if > 500ms

**Forbidden recovery patterns:**
- Micro-PTS corrections (nudging timestamps)
- Adaptive rate shifting
- Time-warping or speed adjustment

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) - Layer 0 Laws
- [PHASE9_BOOTSTRAP.md](./PHASE9_BOOTSTRAP.md) - Phase 9 Bootstrap
- [PHASE12_SESSION_TEARDOWN.md](./PHASE12_SESSION_TEARDOWN.md) - Phase 12 Teardown
- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth
