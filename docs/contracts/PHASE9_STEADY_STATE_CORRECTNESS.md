# Phase 9: Steady-State Playout Correctness

**Status:** DRAFT — Awaiting Implementation
**Created:** 2026-02-02
**Scope:** Post-attach steady-state playout correctness
**Prerequisite:** Phase 8 (COMPLETE), Output Bootstrap (COMPLETE)

---

## Document Role

This document defines the authoritative behavioral contracts for **steady-state playout** after:
- Successful segment switch (Phase 8)
- Output attach complete
- Buffers filled
- Epoch established
- Safety rails quiet

Phase 8 is FROZEN. This document does NOT modify timeline semantics, segment commit rules, CT/MT invariants, or switch orchestration.

---

## Architectural Decision (FINAL)

After output attach, **OUTPUT / MUX owns pacing**.

| Phase | Pacing Authority | Producer Role |
|-------|------------------|---------------|
| Preroll (pre-attach) | Producer-driven | Decode and buffer at decode rate |
| Steady-state (post-attach) | Output-driven | Decode only when pulled |

Producers are **time-blind** in steady state. They may decode and buffer during preroll, but MUST NOT free-run after attach. Audio and video advance **only** when pulled by the output clock (PCR / wall clock).

---

## A) PHASE 9 INVARIANTS

### INV-P9-STEADY-001: Output Owns Pacing Authority

**Classification:** CONTRACT
**Owner:** ProgramOutput, MpegTSOutputSink
**Enforcement:** Post-Attach / Steady-State

After output attach, the mux loop MUST be the sole pacing authority. Frame emission occurs when the output clock (PCR-paced wall clock) reaches frame CT, not when frames become available.

**MUST:** Mux loop waits for `wall_clock >= frame.ct_us` before dequeue.
**MUST NOT:** Mux consume frames as fast as they are produced.
**MUST NOT:** Producer pace the output loop.

---

### INV-P9-STEADY-002: Producer Pull-Only After Attach

**Classification:** CONTRACT
**Owner:** FileProducer, ProgrammaticProducer
**Enforcement:** Post-Attach / Steady-State

After output attach, producers MUST NOT free-run (decode as fast as possible). Producers MUST decode only when downstream capacity exists (slot-based gating). The producer thread MUST yield when the buffer is at capacity.

**MUST:** Block at decode gate when buffer full.
**MUST:** Resume when exactly one slot frees.
**MUST NOT:** Decode ahead unboundedly.
**MUST NOT:** Use hysteresis (low-water drain).

---

### INV-P9-STEADY-003: Audio Advances With Video

**Classification:** CONTRACT
**Owner:** FileProducer, MpegTSOutputSink
**Enforcement:** Post-Attach / Steady-State

Audio and video MUST advance together. Neither stream may run ahead of the other by more than one frame duration (33ms at 30fps). When backpressure is applied, both streams MUST be throttled symmetrically.

**MUST:** Audio blocked when video blocked (and vice versa).
**MUST:** A/V delta ≤ 1 frame duration at all times.
**MUST NOT:** Audio decode while video blocked.
**MUST NOT:** Video decode while audio blocked.

---

### INV-P9-STEADY-004: No Pad While Depth High

**Classification:** CONTRACT
**Owner:** ProgramOutput
**Enforcement:** Post-Attach / Steady-State

Pad frame emission while buffer depth ≥ 10 is a CONTRACT VIOLATION. If frames exist in the buffer but are not being consumed, this indicates a flow control or CT tracking bug, not content starvation.

**MUST:** Log `INV-P9-STEADY-004 VIOLATION` if pad emitted with depth ≥ 10.
**MUST NOT:** Emit pad frames when buffer has content.

---

### INV-P9-STEADY-005: Buffer Equilibrium Sustained

**Classification:** CONTRACT
**Owner:** FrameRingBuffer, ProgramOutput
**Enforcement:** Post-Attach / Steady-State

Buffer depth MUST oscillate around target (default: 3 frames). Depth MUST remain in range [1, 2N] during steady-state. Monotonic growth or drain to zero indicates a bug.

**MUST:** Maintain depth in [1, 2N] range.
**MUST NOT:** Grow unboundedly (memory leak).
**MUST NOT:** Drain to zero during normal playback.

---

### INV-P9-STEADY-006: Realtime Throughput Maintained

**Classification:** CONTRACT
**Owner:** ProgramOutput, MpegTSOutputSink
**Enforcement:** Post-Attach / Steady-State

Output rate MUST match configured frame rate within tolerance. Over any 10-second window, frame count MUST equal `target_fps × 10 ± 1`. PTS advancement MUST remain bounded to MasterClock with no cumulative drift beyond 100ms.

**MUST:** Emit at target FPS ± 1%.
**MUST:** Keep `|master_clock_elapsed - pts_elapsed| < 100ms`.
**MUST NOT:** Drop frames to catch up.
**MUST NOT:** Speed up or slow down adaptively.

---

### INV-P9-STEADY-007: Producer CT Authoritative

**Classification:** CONTRACT
**Owner:** MpegTSOutputSink
**Enforcement:** Post-Attach / Steady-State

Muxer MUST use producer-provided CT. No local CT counters. No CT resets. Producer computes CT via TimelineController; muxer is a pass-through.

**MUST:** Use `audio_frame.pts_us` and `video_frame.ct_us` directly.
**MUST NOT:** Maintain local `audio_ct_us = 0`.
**MUST NOT:** Reset CT on attach.
**MUST NOT:** Ignore producer-provided timestamps.

---

### INV-P9-STEADY-008: No Silence Injection After Attach

**Classification:** CONTRACT
**Owner:** MpegTSOutputSink
**Enforcement:** Post-Attach / Steady-State

Silence injection MUST be disabled when steady-state begins. Producer audio is the ONLY audio source.

**Relationship to LAW-OUTPUT-LIVENESS:** When audio queue is empty, transport MUST continue (video proceeds alone). TS emission can never be gated on audio availability. PCR advances with video packets; late joiners remain discoverable. A/V sync is a content-plane concern, not a transport-plane concern.

**MUST:** Disable silence injection on steady-state entry.
**MUST:** Continue video emission when audio unavailable (LAW-OUTPUT-LIVENESS).
**MUST NOT:** Inject silence during steady-state.
**MUST NOT:** Fabricate audio packets.
**MUST NOT:** Stall TS emission waiting for audio.

---

## B) PHASE 9 CONTRACTS

### Contract: Producer ↔ Output

**Authority:** Output owns pacing after attach.

**Allowed Behavior:**

| Actor | Allowed |
|-------|---------|
| Producer | Decode when buffer has capacity |
| Producer | Block at decode gate when full |
| Producer | Resume when one slot frees |
| Producer | Yield CPU when blocked |
| Output | Pull frames at PCR-paced rate |
| Output | Wait for CT before dequeue |
| Output | Stall when no frames available |

**Forbidden Behavior:**

| Actor | Forbidden |
|-------|-----------|
| Producer | Decode ahead unboundedly |
| Producer | Free-run after attach |
| Producer | Use hysteresis gating |
| Producer | Push when buffer full |
| Output | Drain buffer as fast as possible |
| Output | Drop frames to catch up |
| Output | Speed up or slow down |
| Output | Maintain local CT counter |

**Protocol:**

```
Post-Attach Steady-State Loop:

Producer:
  while (!stop) {
    WaitForSlot();           // Block at capacity, resume on 1 slot free
    frame = Decode();
    frame.ct = TC.Admit();   // CT from TimelineController
    Push(frame);
  }

Output:
  while (!stop) {
    frame = Peek();
    WaitUntil(wall_clock >= frame.ct);
    Dequeue();
    Encode(frame);
  }
```

---

### Contract: TimelineController ↔ Output

**Authority:** TimelineController owns CT assignment. Output owns emission timing.

**Allowed Behavior:**

| Actor | Allowed |
|-------|---------|
| TimelineController | Assign CT on AdmitFrame |
| TimelineController | Maintain monotonic CT |
| TimelineController | Advance CT cursor per frame |
| Output | Read frame.ct for pacing |
| Output | Wait for wall_clock >= ct |
| Output | Emit when ct reached |

**Forbidden Behavior:**

| Actor | Forbidden |
|-------|-----------|
| TimelineController | Modify CT based on output state |
| TimelineController | Read output buffer depth |
| TimelineController | Gate admission on output |
| Output | Modify frame.ct |
| Output | Assign CT |
| Output | Compute CT from wall clock |
| Output | Reset CT on attach |

**Boundary:**

TimelineController's responsibility ends when CT is assigned. Output's responsibility begins when it reads CT for pacing. The boundary is the frame struct: `frame.ct_us` is written by TimelineController, read by Output.

---

## C) PHASE 9 IMPLEMENTATION TASKS

### P0: Blocking Tasks

| ID | Component | Change | Acceptance Condition |
|----|-----------|--------|---------------------|
| P9-CORE-001 | MpegTSOutputSink | Disable silence injection on steady-state entry | No silence frames emitted after attach; log confirms `silence_injection_disabled=true` |
| P9-CORE-002 | MpegTSOutputSink | Implement PCR-paced mux loop | Mux waits for `wall_clock >= frame.ct` before dequeue; no burst consumption |
| P9-CORE-003 | FileProducer | Enforce slot-based decode gating | Producer blocks at capacity, resumes on 1 slot free; no hysteresis |
| P9-CORE-004 | FileProducer | Symmetric A/V backpressure | When video blocked, audio also blocked (and vice versa); A/V delta ≤ 1 frame |
| P9-CORE-005 | ProgramOutput | Enforce INV-P9-STEADY-004 | Log violation when pad emitted with depth ≥ 10; counter incremented |
| P9-CORE-006 | MpegTSOutputSink | Remove local CT counters | Muxer uses only producer-provided `pts_us`; no `audio_ct_us = 0` initialization |

### P1: Optional Tasks

| ID | Component | Change | Acceptance Condition |
|----|-----------|--------|---------------------|
| P9-OPT-001 | FrameRingBuffer | Add equilibrium monitoring | Log warning when depth outside [1, 2N] for > 1 second |
| P9-OPT-002 | MetricsExporter | Add steady-state metrics | `retrovue_steady_state_active` gauge, `retrovue_mux_stall_count` counter |
| P9-OPT-003 | PlayoutEngine | Add steady-state entry log | Log `INV-P9-STEADY-STATE: entered` when conditions met |

---

## D) PHASE 9 TESTS

### For INV-P9-STEADY-001: Output Owns Pacing Authority

**TEST-P9-STEADY-001-A: Mux Waits For CT**

Given: Steady-state playout active
When: Frame with `ct_us = now + 100ms` pushed to buffer
Then: Mux does not dequeue until wall_clock reaches ct_us
And: Frame emission timestamp matches ct_us ± 1ms

**TEST-P9-STEADY-001-B: No Burst Consumption**

Given: Buffer filled with 10 frames
When: Steady-state playout for 10 seconds
Then: Output rate matches target FPS exactly
And: No burst consumption (max 1 frame per period)

---

### For INV-P9-STEADY-002: Producer Pull-Only After Attach

**TEST-P9-STEADY-002-A: Slot-Based Blocking**

Given: Buffer at capacity
When: Producer attempts decode
Then: Producer thread blocks
And: Producer resumes when exactly 1 slot frees

**TEST-P9-STEADY-002-B: No Hysteresis**

Given: Buffer at capacity, producer blocked
When: Consumer dequeues 1 frame
Then: Producer immediately resumes (not waiting for low-water)
And: Buffer refills to capacity

---

### For INV-P9-STEADY-003: Audio Advances With Video

**TEST-P9-STEADY-003-A: Symmetric Backpressure**

Given: Video buffer full, audio buffer has capacity
When: Measured over 10 seconds
Then: `|audio_frames_produced - video_frames_produced| ≤ 1`
And: Neither stream runs ahead

**TEST-P9-STEADY-003-B: Coordinated Stall**

Given: Video blocked at decode gate
When: Audio decode attempted
Then: Audio also blocks
And: Both resume together when capacity available

---

### For INV-P9-STEADY-004: No Pad While Depth High

**TEST-P9-STEADY-004-A: Violation Detection**

Given: Buffer depth = 15 frames
When: ProgramOutput emits pad frame
Then: Log contains `INV-P9-STEADY-004 VIOLATION`
And: `pad_while_depth_high_` counter incremented

---

### For INV-P9-STEADY-005: Buffer Equilibrium Sustained

**TEST-P9-STEADY-005-A: 60-Second Stability**

Given: Channel playing for 60 seconds
When: Buffer depth sampled every second
Then: All samples in range [1, 2N]
And: No monotonic growth or drain

---

### For INV-P9-STEADY-006: Realtime Throughput Maintained

**TEST-P9-STEADY-006-A: Frame Rate Accuracy**

Given: Channel playing for 60 seconds at 30fps
When: Frame output counted
Then: Total frames = 1800 ± 1
And: No underrun events

**TEST-P9-STEADY-006-B: PTS Bounded To Clock**

Given: Channel playing for 60 seconds
When: Final PTS compared to MasterClock elapsed
Then: `|pts_elapsed - clock_elapsed| < 100ms`

---

### For INV-P9-STEADY-007: Producer CT Authoritative

**TEST-P9-STEADY-007-A: No CT Reset**

Given: Producer CT at 3,600,000,000 µs (1 hour)
When: Output attach occurs
Then: First muxed frame PTS = 3,600,000,000 µs (not 0)
And: No `audio_ct_us = 0` in logs

---

### For INV-P9-STEADY-008: No Silence Injection After Attach

**TEST-P9-STEADY-008-A: Silence Disabled**

Given: Steady-state playout active
When: Audio queue temporarily empty
Then: Mux loop stalls (video also stalls)
And: No silence frames injected
And: Log confirms `silence_injection_disabled=true`

---

## E) EXPLICIT NON-GOALS (OUT OF SCOPE)

### Deferred to Phase 10 / Phase 13

| Item | Reason | Future Phase | Related Invariant |
|------|--------|--------------|-------------------|
| Adaptive bitrate | Quality optimization | Phase 13 | — |
| Quality degradation under load | Graceful degradation | Phase 13 | INV-P13-GRACEFUL-DEGRADATION |
| Network congestion handling | Sink responsibility | Phase 13 | INV-P13-SINK-CONGESTION |
| Multi-channel resource balancing | Core responsibility | Phase 10+ | INV-CORE-RESOURCE-BALANCE |
| Encoder tuning for latency | Quality optimization | Phase 13 | INV-P13-ENCODER-TUNE |
| Buffer size auto-tuning | Optimization | Phase 13 | INV-P13-BUFFER-TUNE |

### Explicitly NOT Addressed

| Item | Reason |
|------|--------|
| Switching semantics | Frozen per Phase 8 |
| Bootstrap timing | Frozen per Output Bootstrap |
| PCR ownership at startup | Frozen per Output Bootstrap |
| Timeline semantics | Frozen per Phase 8 |
| CT/MT mapping | Frozen per Phase 8 |
| Segment commit rules | Frozen per Phase 8 |

---

## Invariant Summary Table

| ID | Owner | Phase | One-Line |
|----|-------|-------|----------|
| INV-P9-STEADY-001 | ProgramOutput, MpegTSOutputSink | Post-Attach | Output owns pacing authority |
| INV-P9-STEADY-002 | FileProducer | Post-Attach | Producer pull-only after attach |
| INV-P9-STEADY-003 | FileProducer, MpegTSOutputSink | Post-Attach | Audio advances with video |
| INV-P9-STEADY-004 | ProgramOutput | Post-Attach | No pad while depth high |
| INV-P9-STEADY-005 | FrameRingBuffer, ProgramOutput | Post-Attach | Buffer equilibrium sustained |
| INV-P9-STEADY-006 | ProgramOutput, MpegTSOutputSink | Post-Attach | Realtime throughput maintained |
| INV-P9-STEADY-007 | MpegTSOutputSink | Post-Attach | Producer CT authoritative |
| INV-P9-STEADY-008 | MpegTSOutputSink | Post-Attach | No silence injection after attach |

---

## Exit Criteria

Phase 9 Steady-State Correctness is complete when:

1. All P0 tasks implemented
2. All tests pass
3. 60-second continuous playout without pad takeover
4. 60-second continuous playout without runaway backpressure
5. Continuous real-time output maintained for 10 minutes
6. No Phase 8 regressions

---

## Lock Conditions

This contract MUST NOT be modified after implementation begins except to:
- Fix ambiguities
- Add clarifying notes
- Correct typos

Behavioral changes require a new contract version.
