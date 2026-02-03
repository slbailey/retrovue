# Layer 2 - Phase 9 Output Bootstrap Invariants

**Status:** Canonical
**Scope:** Output bootstrap after segment commit, sink liveness, audio liveness, PCR ownership
**Authority:** Refines Layer 0 Laws; does not override Phase 8 semantics

Phase 8 is **frozen**. This contract does not modify timeline semantics, segment commit rules, or CT/MT invariants.

---

## Phase 9 Coordination Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-P9-FLUSH** | CONTRACT | FileProducer | P9 | Yes | No |
| **INV-P9-BOOTSTRAP-READY** | CONTRACT | PlayoutEngine | P9 | Yes | Yes |
| **INV-P9-NO-DEADLOCK** | CONTRACT | ProgramOutput | P9 | Yes | No |
| **INV-P9-WRITE-BARRIER-SYMMETRIC** | CONTRACT | PlayoutEngine | P9 | Yes | No |
| **INV-P9-BOOT-LIVENESS** | CONTRACT | MpegTSOutputSink | P9 | Yes | No |
| **INV-P9-AUDIO-LIVENESS** | CONTRACT | MpegTSOutputSink | P9 | Yes | No |
| **INV-P9-PCR-AUDIO-MASTER** | CONTRACT | MpegTSOutputSink | P9 | Yes | No |
| **INV-P9-TS-EMISSION-LIVENESS** | CONTRACT | MpegTSOutputSink | P9 | No | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P9-FLUSH | Cached shadow frame pushed to buffer synchronously when shadow disabled |
| INV-P9-BOOTSTRAP-READY | Readiness = commit detected AND >=1 video frame, not deep buffering |
| INV-P9-NO-DEADLOCK | Output routing must not wait on conditions requiring output routing |
| INV-P9-WRITE-BARRIER-SYMMETRIC | When write barrier set, audio and video suppressed symmetrically |
| INV-P9-BOOT-LIVENESS | Newly attached sink emits decodable TS within bounded time |
| INV-P9-AUDIO-LIVENESS | From header written, output contains continuous monotonic audio PTS |
| INV-P9-PCR-AUDIO-MASTER | Audio owns PCR at startup |
| INV-P9-TS-EMISSION-LIVENESS | First decodable TS packet MUST be emitted within 500ms of PCR-PACE timing initialization |

---

## Detailed Invariant Definitions

### INV-P9-FLUSH

**When shadow mode is disabled, the cached first frame MUST be pushed to the buffer synchronously before returning control to orchestration.**

This ensures that when segment commit occurs, the buffer contains at least one video frame immediately.

**Enforcement:** FileProducer::SetShadowDecodeMode(false) calls FlushCachedFrameToBuffer() synchronously.

---

### INV-P9-BOOTSTRAP-READY

**Readiness for output routing requires commit detected AND >=1 video frame, not deep buffering.**

Readiness Policy:
| Condition | Old Policy | Phase 9 Policy |
|-----------|------------|----------------|
| Video depth | >= 2 frames | >= 1 frame (the committed first frame) |
| Audio depth | >= 5 frames | >= 1 frame (or 0 if audio not yet decoded) |
| Segment committed | Not checked | **Required** (generation advanced) |

**Audio zero-frame acceptability:** Zero audio frames is acceptable during bootstrap and must not suppress routing.

---

### INV-P9-NO-DEADLOCK

**Output routing must not wait for conditions that require output routing to satisfy (circular dependency is forbidden).**

If Phase 9 invariants are violated:
- Switch watcher times out (10 seconds) despite valid commit
- Output stalls on black/old content despite new segment owning CT
- Logs show "Readiness NOT passed" with video_depth=0 after commit

---

### INV-P9-WRITE-BARRIER-SYMMETRIC

**When a write barrier is set on a producer, both audio and video must be suppressed symmetrically.**

The audio push retry loop must check `writes_disabled_` to prevent audio from bypassing the barrier while video is blocked.

---

### INV-P9-BOOT-LIVENESS

**A newly attached sink must emit a decodable transport stream within a bounded time, even if audio is not yet available.**

This invariant alone explains:
- VLC not starting (no PAT/PMT emitted)
- Audio priming stalls (video blocked waiting for audio)
- Late perceived switches (output withheld despite timeline transfer)

Implementation: The MPEG-TS header (`avformat_write_header`) is written immediately in `EncoderPipeline::open()`, not deferred until first audio frame arrives.

---

### INV-P9-AUDIO-LIVENESS

**From the moment the MPEG-TS header (PAT/PMT) is written and the sink is considered "attached / live", the output MUST contain continuous, monotonically increasing audio PTS with correct pacing even if decoded audio is not yet available.**

If no real audio frames are available, the system MUST inject PCM silence frames so that:
1. Audio timestamps advance without gaps
2. Sample counts match the configured sample rate
3. Audio PTS remains contiguous when real audio begins
4. Video timing is not delayed or gated to wait for audio

**Log signatures:**
```
INV-P9-AUDIO-LIVENESS: injecting_silence started
INV-P9-AUDIO-LIVENESS: injecting_silence ended (real_audio_ready=true)
```

---

### INV-P9-PCR-AUDIO-MASTER

**At output startup (after TS header write and before steady-state):**

- Audio MUST be the PCR master
- Audio PTS MUST start at 0 (or <= 1 frame duration)
- Video PTS MUST be derived relative to audio
- Mux MUST NOT initialize audio timing from video
- If no real audio is available, injected silence is authoritative

**Violations cause VLC to stall indefinitely.**

**Forbidden Pattern:**
```
X REMOVE this behavior:
[MpegTSOutputSink] Audio CT initialized from video
```

---

### INV-P9-TS-EMISSION-LIVENESS

**First decodable TS packet MUST be emitted within 500ms of PCR-PACE timing initialization.**

Derives from: INV-P9-BOOT-LIVENESS (adds specific deadline to "bounded time")

---

## Testable Guarantees

### G9-001: First Frame Available at Commit

**Given:** Preview producer in shadow mode with cached first frame
**When:** SetShadowDecodeMode(false) is called
**Then:** Preview ring buffer contains >=1 video frame before the call returns

### G9-002: Readiness Satisfied Immediately After Commit

**Given:** Segment commit detected (generation advanced)
**And:** Preview buffer has >=1 video frame
**Then:** Readiness check passes within one poll cycle (<=50ms)

### G9-003: No Deadlock on Switch

**Given:** Preview producer reaches shadow decode ready
**When:** SwitchToLive is invoked
**Then:** Output routing completes within 500ms (not 10s timeout)

### G9-004: Output Transition Occurs

**Given:** Switch completes per G9-003
**Then:** Consumer (EncoderPipeline/OutputBus) receives frames from preview buffer, not live buffer

---

## Relation to Phase 8

| Concern | Phase 8 | Phase 9 |
|---------|---------|---------|
| Timeline authority | Owns CT/MT | Does not modify |
| Segment commit | Edge-detected | Consumes signal |
| Old segment closure | Force-stop at commit | Does not modify |
| First frame routing | - | Ensures routable |
| Buffer readiness | - | Defines policy |
| Output transition | - | Unlocks routing |

Phase 9 is strictly **downstream** of Phase 8. It consumes commit signals and ensures they result in observable output.

---

## Phase 9 Status: LOCKED

**Phase 9 is complete and frozen as of this commit.**

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

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) - Layer 0 Laws
- [PHASE8_COORDINATION.md](./PHASE8_COORDINATION.md) - Phase 8 Coordination
- [PHASE10_FLOW_CONTROL.md](./PHASE10_FLOW_CONTROL.md) - Phase 10 Flow Control
- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth
