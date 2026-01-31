# Phase 9 — Output Bootstrap After Segment Commit

_Related: [Phase 8 Overview](Phase8-Overview.md) · [Phase8-3 Preview/SwitchToLive](Phase8-3-PreviewSwitchToLive.md) · [OutputSwitchingContract](OutputSwitchingContract.md) · [PlayoutInvariants-BroadcastGradeGuarantees](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)_

**Principle:** After a segment commits and takes timeline ownership (Phase 8), there must be a deterministic path from commit to observable output. Phase 9 defines the minimal bootstrap required to break the readiness deadlock and route the first frame. **Authoritative definition of output liveness and timeline laws lives in [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md).**

Phase 8 is **frozen**. This contract does not modify timeline semantics, segment commit rules, or CT/MT invariants.

---

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)).

---

## 1. Purpose

Phase 8 solved timeline correctness: CT and MT lock together on first preview frame, segment commit is explicit and edge-detected, and the old segment is hard-closed at commit.

However, Phase 8 does not address **output routing**. The switch watcher gates output on buffer readiness, but buffer readiness requires frames to be written, and frames can only be written after shadow mode is disabled. This creates a bootstrap deadlock:

```
┌─────────────────────────────────────────────────────────┐
│  Segment commits (Phase 8)                              │
│       ↓                                                 │
│  Output routing waits for buffer depth ≥ N              │
│       ↓                                                 │
│  Buffer depth is 0 (no frames written yet)              │
│       ↓                                                 │
│  Producer thread is waking up / racing with watcher     │
│       ↓                                                 │
│  DEADLOCK: authority transferred, output withheld       │
└─────────────────────────────────────────────────────────┘
```

**Phase 9 scope:** Break this deadlock by ensuring at least one routable frame exists at the moment output routing decisions are made.

---

## 2. Inputs (Signals from Phase 8)

Phase 9 receives the following signals from Phase 8 (read-only, not modified):

| Signal | Source | Meaning |
|--------|--------|---------|
| `segment_commit_generation` | TimelineController | Increments when a segment commits (mapping locks) |
| `HasSegmentCommitted()` | TimelineController | True if a segment has committed (state-based) |
| `GetActiveSegmentId()` | TimelineController | ID of the segment that owns CT |
| Shadow decode ready | FileProducer | First frame decoded and cached in shadow mode |
| Cached first frame | FileProducer | The decoded frame held during shadow mode |

Phase 9 **must not** modify TimelineController semantics or add new timeline invariants.

---

## 3. Required Outcomes

### 3.1 First Frame Must Be Routable at Commit

When a segment commits (first preview frame locks the mapping via AdmitFrame), the buffer **must** contain at least one video frame.

This is achieved by one of:
- **(A)** Flushing the cached shadow frame to the buffer synchronously during SetShadowDecodeMode(false), before returning to the switch orchestration code.
- **(B)** Counting the cached frame as "available" in readiness checks, even if not yet in the ring buffer.

Option (A) is preferred because it maintains the invariant that buffer depth accurately reflects routable frames.

### 3.2 Readiness Policy

The switch watcher's readiness check must be satisfiable **immediately** after segment commit:

| Condition | Old Policy | Phase 9 Policy |
|-----------|------------|----------------|
| Video depth | ≥ 2 frames | ≥ 1 frame (the committed first frame) |
| Audio depth | ≥ 5 frames | ≥ 1 frame (or 0 if audio not yet decoded) |
| Segment committed | Not checked | **Required** (generation advanced) |

The key change: readiness is gated on **commit + minimal frames**, not **deep buffering**.

**Audio zero-frame acceptability:** Zero audio frames is acceptable during bootstrap and must not suppress routing. Audio will catch up after the first video frame is routed. This prevents re-introducing an audio depth gate that would restore the deadlock.

### 3.3 Output Routing Unlocked at Commit

Once segment commit is detected (generation counter advanced), output routing **may** proceed with:
- At least 1 video frame in the preview buffer
- Audio frames optional (some A/V desync acceptable on switch boundary)

The old producer is already force-stopped at commit (Phase 8 INV-P8-SEGMENT-COMMIT-EDGE). Output must transition to the new buffer without waiting for deep fill.

---

## 4. Non-Goals (Explicitly Out of Scope)

Phase 9 does **not** address:

- **Timeline semantics** — CT/MT mapping is frozen per Phase 8
- **Segment commit rules** — Generation counter behavior is frozen
- **Deep buffering policy** — Target depths for steady-state playback are separate from bootstrap
- **Audio/video sync guarantees** — Momentary desync on switch boundary is acceptable
- **Multi-switch cascades** — Each switch is independent; Phase 9 applies per-switch
- **EOF handling** — Covered by INV-P8-EOF-SWITCH, INV-P8-PREVIEW-EOF

---

## 5. Failure Modes

### 5.1 Allowed to Block

- Waiting for shadow decode ready (first frame not yet decoded)
- Waiting for segment mapping to become pending (orchestration ordering)

### 5.2 Must NOT Block

- **Output routing after commit** — If commit happened and ≥1 video frame exists, routing must proceed
- **Readiness check on buffer depth alone** — Depth check must not ignore commit state
- **Producer thread wakeup race** — The flush must be synchronous, not dependent on producer thread scheduling

### 5.3 Failure Manifestation

If Phase 9 invariants are violated:
- Switch watcher times out (10 seconds) despite valid commit
- Output stalls on black/old content despite new segment owning CT
- Logs show "Readiness NOT passed" with video_depth=0 after commit

### 5.4 Logging Guidance

After commit, readiness logs should include both commit generation and buffer depth:
```
[SwitchWatcher] Readiness check: commit_gen=2, video_depth=1, audio_depth=0 → READY (bootstrap)
```
This aids debugging by making the bootstrap vs. steady-state distinction visible.

---

## 6. Testable Guarantees

### G9-001: First Frame Available at Commit

**Given:** Preview producer in shadow mode with cached first frame
**When:** SetShadowDecodeMode(false) is called
**Then:** Preview ring buffer contains ≥1 video frame before the call returns

### G9-002: Readiness Satisfied Immediately After Commit

**Given:** Segment commit detected (generation advanced)
**And:** Preview buffer has ≥1 video frame
**Then:** Readiness check passes within one poll cycle (≤50ms)

### G9-003: No Deadlock on Switch

**Given:** Preview producer reaches shadow decode ready
**When:** SwitchToLive is invoked
**Then:** Output routing completes within 500ms (not 10s timeout)

### G9-004: Output Transition Occurs

**Given:** Switch completes per G9-003
**Then:** Consumer (EncoderPipeline/OutputBus) receives frames from preview buffer, not live buffer

---

## 7. Acceptable Solution Shapes

### Shape A: Synchronous Flush (Recommended)

```
SwitchToLive():
  1. SetWriteBarrier on live producer
  2. BeginSegmentFromPreview()
  3. SetShadowDecodeMode(false)
  4. FlushCachedFrameToBuffer()  ← NEW: pushes cached frame through AdmitFrame
  5. Watcher detects commit + depth≥1 → completes
```

The flush is synchronous: when step 4 returns, the buffer has ≥1 frame. The watcher's next poll sees both commit and depth satisfied.

**Ownership:** The flush is owned by the producer (`FileProducer::FlushCachedFrameToBuffer()`), not the watcher or orchestrator. This keeps ownership clean, testability localized, and orchestration free of media semantics. The orchestrator calls into the producer; it does not manipulate buffers directly.

### Shape B: Relaxed Readiness Threshold

```
Watcher readiness check:
  IF commit_gen > last_seen_gen AND video_depth >= 1:
    → READY (bootstrap mode)
  ELSE IF video_depth >= 2 AND audio_depth >= 5:
    → READY (steady-state mode)
```

This allows immediate routing on commit with minimal buffering, then steady-state requires deeper buffers.

### Shape C: Commit-Triggered Routing

```
Watcher loop:
  IF commit_gen > last_seen_gen:
    → Immediately begin routing (trust that AdmitFrame put a frame in buffer)
    → Close old producer
    → Let steady-state buffering handle the rest
```

This trusts Phase 8's guarantee that commit only happens when a frame is admitted.

---

## 8. Relation to Phase 8

| Concern | Phase 8 | Phase 9 |
|---------|---------|---------|
| Timeline authority | ✓ Owns CT/MT | Does not modify |
| Segment commit | ✓ Edge-detected | Consumes signal |
| Old segment closure | ✓ Force-stop at commit | Does not modify |
| First frame routing | — | ✓ Ensures routable |
| Buffer readiness | — | ✓ Defines policy |
| Output transition | — | ✓ Unlocks routing |

Phase 9 is strictly **downstream** of Phase 8. It consumes commit signals and ensures they result in observable output.

---

## 9. Exit Criteria

Phase 9 is complete when:

1. **No readiness deadlock**: SwitchToLive completes in <500ms, not 10s timeout
2. **First frame routable**: Buffer depth ≥1 immediately after SetShadowDecodeMode(false)
3. **Output transitions**: Consumer receives frames from new segment after commit
4. **Multi-switch stable**: 2nd, 3rd, Nth switches behave identically to 1st
5. **No Phase 8 regressions**: Timeline semantics unchanged, commit edge detection unchanged

---

## 10. Invariants (Phase 9 Only)

These invariants are **new** to Phase 9 and do not modify Phase 8:

### 10.1 Bootstrap Invariants

- **INV-P9-FLUSH**: The cached shadow frame must be pushed to the buffer synchronously when shadow mode is disabled, before returning control to orchestration.

- **INV-P9-BOOTSTRAP-READY**: Readiness for output routing requires commit detected AND ≥1 video frame, not deep buffering.

- **INV-P9-NO-DEADLOCK**: Output routing must not wait for conditions that require output routing to satisfy (circular dependency is forbidden).

### 10.2 Output Timing Invariants

- **INV-P9-A-OUTPUT-SAFETY**: No audio or video frame may be emitted to any sink before its CT. Producers may decode early and buffers may fill early, but release to output must be gated by CT.

- **INV-P9-B-OUTPUT-LIVENESS**: A frame whose CT has arrived must eventually be emitted (or explicitly dropped). Audio frames must be processed even when video buffer is empty.

### 10.3 Write Barrier Invariants

- **INV-P9-WRITE-BARRIER-SYMMETRIC**: When a write barrier is set on a producer, both audio and video must be suppressed symmetrically. The audio push retry loop must check `writes_disabled_` to prevent audio from bypassing the barrier while video is blocked.

### 10.4 Sink Bootstrap Invariants

- **INV-P9-BOOT-LIVENESS**: A newly attached sink must emit a decodable transport stream within a bounded time, even if audio is not yet available.

  This invariant alone explains:
  - VLC not starting (no PAT/PMT emitted)
  - Audio priming stalls (video blocked waiting for audio)
  - Late perceived switches (output withheld despite timeline transfer)

  Implementation: The MPEG-TS header (`avformat_write_header`) is written immediately in `EncoderPipeline::open()`, not deferred until first audio frame arrives.

### 10.5 Audio Liveness Invariant (HARD)

- **INV-P9-AUDIO-LIVENESS**: From the moment the MPEG-TS header (PAT/PMT) is written and the sink is considered "attached / live", the output **must** contain continuous, monotonically increasing audio PTS with correct pacing even if decoded audio is not yet available.

  If no real audio frames are available, the system **MUST** inject PCM silence frames (or equivalent codec-silence) so that:

  1. Audio timestamps advance without gaps
  2. Sample counts match the configured sample rate
  3. Audio PTS remains contiguous when real audio begins
  4. Video timing is not delayed or gated to wait for audio

  **Ownership:** This invariant is output-layer owned (mux/sink), not producer-owned. Producers remain time-blind.

  **VLC Compliance:** VLC must begin playback promptly against the emitted TS once headers are written. The stream must be standards-tolerant without requiring client-side configuration changes.

  **Implementation Requirements:**
  - When the sink attaches and TS header is written, begin mux loop immediately
  - If the audio queue is empty, synthesize silence audio frames of the configured format (sample_rate/channels), sized to the pipeline's normal audio frame size (1024 samples)
  - Assign PTS such that audio is continuous and monotonic, based on the same clock domain used by the mux/video CT
  - Do not create discontinuities when switching from injected silence to real audio frames
  - Do not delay video or block output waiting for audio

  **Logging:**
  ```
  INV-P9-AUDIO-LIVENESS: injecting_silence started
  INV-P9-AUDIO-LIVENESS: injecting_silence ended (real_audio_ready=true)
  ```

  **Metrics:**
  - `retrovue_audio_silence_frames_injected_total` (counter)
  - `retrovue_audio_silence_injection_active` (gauge: 0 or 1)

---

## 11. INV-P9-AUDIO-LIVENESS Required Tests

The following tests **must** pass to satisfy INV-P9-AUDIO-LIVENESS. Tests are located in `tests/contracts/Phase9AudioLivenessTests.cpp`.

### TEST-P9-AUDIO-LIVENESS-001: header-to-audio-liveness

**Given:** Channel started and sink attached
**And:** Decoded audio is not available for N video frames (empty audio queue)
**When:** Header is written and video frames are encoded
**Then:** Mux emits TS packets that include audio PES with PTS advancing monotonically (no stall)
**And:** Audio output begins within 500ms wall-clock of header write

### TEST-P9-AUDIO-LIVENESS-002: silence-to-real-audio-contiguity

**Given:** Sink is injecting silence for at least 100ms
**When:** Real audio frames begin arriving
**Then:** Audio PTS is contiguous across the transition
**And:** No backward PTS jump occurs
**And:** No large gap beyond 1 frame duration (≤ 1024 samples / 48000 Hz ≈ 21.3ms)

### TEST-P9-AUDIO-LIVENESS-003: VLC-decodable-smoke

**Given:** TS output captured for the first 2 seconds after header write
**When:** Analyzed with ffprobe (or equivalent parser)
**Then:** Both audio and video streams are present
**And:** Timestamps are present and monotonically increasing
**And:** No "missing audio" condition exists at stream start

---

## 12. INV-P9-PCR-AUDIO-MASTER (Bootstrap PCR Ownership)

At output startup (after TS header write and before steady-state):

- **Audio MUST be the PCR master**
- **Audio PTS MUST start at 0** (or ≤ 1 frame duration)
- **Video PTS MUST be derived relative to audio**
- **Mux MUST NOT initialize audio timing from video**
- **If no real audio is available, injected silence is authoritative**

**Violations cause VLC to stall indefinitely.**

This invariant applies only during startup bootstrap. Once steady-state is reached, normal PCR selection rules may resume.

### Forbidden Pattern

```
❌ REMOVE this behavior:
[MpegTSOutputSink] Audio CT initialized from video
```

The mux must never derive audio timing from video. Audio owns the timeline at startup.

### Required Behavior

```cpp
// Audio owns PCR at startup
audio_ct_us = 0;  // Audio starts at 0, NOT from video
// Silence injection advances audio CT from 0
// Video is encoded with its own PTS, but audio is PCR master
```

### Required Tests

Tests are located in `tests/contracts/Phase9OutputBootstrapTests.cpp`.

#### TEST-P9-PCR-AUDIO-MASTER-001: PCR from audio, audio PTS near zero

**Given:** Stream started with video-first frames
**When:** TS output is captured
**Then:** PCR originates from audio PID (or audio timeline)
**And:** Audio PTS starts ≤ 1 frame duration from 0 (≤ 1920 ticks at 90kHz for 1024 samples @ 48kHz)

#### TEST-P9-PCR-AUDIO-MASTER-002: Silence to real audio without PCR discontinuity

**Given:** Stream started with silence injection
**When:** Real audio frames begin arriving
**Then:** No PCR discontinuity occurs
**And:** Audio PTS remains monotonic

#### TEST-P9-VLC-STARTUP-SMOKE: No DTS warnings

**Given:** TS output captured for first 2 seconds
**When:** Analyzed with ffprobe
**Then:** Audio stream exists
**And:** Video stream exists
**And:** Timestamps are monotonic
**And:** No "non-monotonous DTS" warnings in ffprobe output

---

## 13. Phase 9 Status: LOCKED

**Phase 9 is complete and frozen as of this commit.**

### Invariant Summary

| Invariant | Description | Test Coverage |
|-----------|-------------|---------------|
| INV-P9-FLUSH | Shadow frame flushed synchronously | `INV_P9_FLUSH_Synchronous` |
| INV-P9-BOOTSTRAP-READY | Commit + 1 frame = ready | `G9_002`, `AudioZeroFrameAcceptable` |
| INV-P9-NO-DEADLOCK | No circular wait on output | `G9_003_NoDeadlockOnSwitch` |
| INV-P9-A-OUTPUT-SAFETY | No emission before CT | Implicit in CT tests |
| INV-P9-B-OUTPUT-LIVENESS | CT-arrived frames emitted | Audio liveness tests |
| INV-P9-WRITE-BARRIER-SYMMETRIC | Audio+video suppressed together | Audio liveness tests |
| INV-P9-BOOT-LIVENESS | TS decodable within bounded time | `G9_001`, `G9_004` |
| INV-P9-AUDIO-LIVENESS | Continuous audio PTS from header | `AUDIO_LIVENESS_001/002/003` |
| INV-P9-PCR-AUDIO-MASTER | Audio owns PCR at startup | `PCR_AUDIO_MASTER_001/002`, `VLC_STARTUP_SMOKE` |

### What Phase 9 Guarantees

1. Live/preview switching works correctly
2. TimelineController ownership transfers are correct
3. CT/MT mapping locks deterministically
4. Write barriers are symmetric across audio and video
5. Encoder boots correctly (TS header written, streams present)
6. PCR ownership is established (audio at startup)
7. Switch completes with contiguous PTS
8. VLC plays immediately without stall

### What Phase 9 Does NOT Guarantee

- Sustained realtime throughput (Phase 10)
- Long-running stability (Phase 10)
- Backpressure handling under load (Phase 10)
- Producer throttling vs consumer capacity (Phase 10)

### Lock Conditions

- All 13 Phase 9 tests pass
- No behavioral changes allowed unless a Phase 9 invariant is violated
- Phase 10 may not modify Phase 9 semantics
