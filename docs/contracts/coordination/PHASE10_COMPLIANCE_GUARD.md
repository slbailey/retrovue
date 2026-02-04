# Phase 10 Compliance Guard

**Status:** FROZEN
**Effective:** 2026-02-04
**Authority:** Locks Phase 10 pressure model as canonical; no regressions permitted

This document is a **constitutional amendment** that freezes Phase 10 behavior.
Future changes MUST NOT violate these constraints without explicit doctrine revision.

**Scope boundary:** This guard applies to **steady-state playout only**. Phase 9 bootstrap semantics and Phase 12 teardown semantics are explicitly out of scope.

---

## Frozen Behaviors

The following behaviors are **locked** and MUST NOT be changed:

### 1. Pressure Terminates at Producer Decode Gate

| Frozen Behavior | Implementation |
|-----------------|----------------|
| Backpressure stops at decode | `FileProducer::WaitForDecodeReady()` |
| Slot-based gating (no hysteresis) | Block at capacity, unblock on one slot free |
| Symmetric A/V throttling | `CanPushAV()` checks both buffers |

### 2. Time Is Never Backpressured

| Frozen Behavior | Implementation |
|-----------------|----------------|
| CT always advances | MasterClock is non-negotiable |
| Missing frame → pad | `ProgramOutput::emit_pad_frame` path |
| No wait for producer | Immediate pad emission, no blocking |

### 3. Transport Absorbs Backpressure Locally

| Frozen Behavior | Implementation |
|-----------------|----------------|
| Non-blocking socket writes | `SocketSink::TryConsumeBytes()` with MSG_DONTWAIT |
| Drop on EAGAIN | Returns false, increments drop counter |
| No retries | Single attempt only |

### 4. OutputBus Is Lock-Free

| Frozen Behavior | Implementation |
|-----------------|----------------|
| Atomic sink pointer | `sink_.load(memory_order_acquire)` |
| No mutex on hot path | `RouteVideo()` / `RouteAudio()` |
| Legal discard when unattached | Counter increment only |

### 5. Buffer Equilibrium Is Observability-Only

| Frozen Behavior | Implementation |
|-----------------|----------------|
| Target N=3, range [1,6] | `ProgramOutput.h` constants |
| Periodic sampling | `CheckBufferEquilibrium()` every 1s |
| No active depth control | Emergent from matched rates |

### 6. Control-Plane Is Not Media (LAW-TS-DISCOVERABILITY)

| Frozen Behavior | Implementation |
|-----------------|----------------|
| PAT/PMT not subject to CT pacing | Control-plane cadence enforced in MuxLoop |
| Emission bounded by wall time (≤500ms) | `INV-TS-CONTROL-PLANE-CADENCE` |
| Media starvation does not block discovery | Muxer heartbeat when threshold exceeded |

**Forbidden (INV-TS-CONTROL-PLANE-CADENCE):** Control-plane emission MUST NOT wait on:
- `video_queue_` non-empty
- `audio_queue_` non-empty
- CT alignment (frame timing)
- Encoder packet availability
- Producer state (EOF, starvation, shadow mode)

**Phase 10 Compliance:** This does NOT violate Phase 10 pressure doctrine:
- No new thread — MuxLoop already runs
- No new queue — heartbeat uses existing muxer path
- No new timing authority — MuxLoop already tracks wall time for CT pacing
- No blocking — heartbeat emission is non-blocking
- No backpressure — control-plane is bounded, small

---

## Forbidden Patterns

The following patterns are **permanently forbidden** in Phase 10+ code:

### Queues and Buffers

| Pattern | Reason |
|---------|--------|
| ❌ New queues between producer and FrameRingBuffer | Violates single-buffer doctrine |
| ❌ Unbounded queues anywhere | Memory safety + latency |
| ❌ Hidden buffering that bypasses flow control | Breaks pressure routing |

### Backpressure

| Pattern | Reason |
|---------|--------|
| ❌ Backpressure signals outside decode gate | Violates RULE-P10-DECODE-GATE |
| ❌ OutputBus signaling "slow sink" upstream | Violates SS-002 |
| ❌ Transport affecting AIR timing | Violates LAW-OUTPUT-LIVENESS |

### Timing

| Pattern | Reason |
|---------|--------|
| ❌ Waiting for producer in render path | Violates pad-immediate rule |
| ❌ Timestamp nudging or repair | Violates INV-P10-PRODUCER-CT-AUTHORITATIVE |
| ❌ Adaptive speed-up / slow-down | Violates PCR pacing doctrine |
| ❌ "Just this once" waits | Slippery slope to blocking |

### Transport

| Pattern | Reason |
|---------|--------|
| ❌ Blocking socket writes | Violates SS-001 |
| ❌ Sleep-retry loops on EAGAIN | Violates SS-004 |
| ❌ Retries of any kind | Violates best-effort doctrine |

### Recovery

| Pattern | Reason |
|---------|--------|
| ❌ Frame dropping to "catch up" | Violates pad-only recovery |
| ❌ Coordinated drops | Violates pressure termination |
| ❌ Silent frame skipping | Violates audit visibility |

---

## Compliance Verification

### Code-Level Guards

```bash
# These patterns MUST NOT appear in new code:

# No blocking writes in transport
grep -r "BlockingWrite" pkg/air/src/output/  # MUST return 0 results

# No sleep in write callbacks
grep -r "sleep_for.*WriteToFdCallback" pkg/air/  # MUST return 0 results

# No hysteresis markers
grep -r "low.water\|high.water" pkg/air/src/producers/  # MUST return 0 results

# No logic may branch on successor emission generation (diagnostic-only)
grep -r "segment_commit_generation_" pkg/air/src | grep -v TimelineController  # MUST return 0 results

# EPOCH OWNERSHIP: Only PlayoutEngine may call reset/set epoch (exclude implementations in timing/)
grep -r "ResetEpochForNewSession\|TrySetEpochOnce" pkg/air/src/producers pkg/air/src/output pkg/air/src/renderer  # MUST return 0 results
grep -r "->ResetEpochForNewSession\|->TrySetEpochOnce" pkg/air/src/timing/TimelineController  # MUST return 0 results

# LAW-TS-DISCOVERABILITY: PAT/PMT must be emitted periodically for late-joiner support
# The resend_headers flag MUST be set in EncoderPipeline
grep -r "resend_headers" pkg/air/src/playout_sinks/mpegts/EncoderPipeline.cpp | wc -l  # MUST return >= 1
# avformat_write_header alone is insufficient (emits PAT/PMT only once)
# Verify the mpegts_flags are actually configured
grep -rE 'mpegts_flags.*resend_headers' pkg/air/src/playout_sinks/mpegts/  # MUST return >= 1

# INV-TS-CONTROL-PLANE-CADENCE: Control-plane MUST NOT be media-gated
# MuxLoop MUST cause muxer to emit control-plane even during media starvation
# Structural proof: MuxLoop must track time since last muxer output AND trigger heartbeat when threshold exceeded
grep -rE 'CONTROL.PLANE.CADENCE|control_plane_cadence|last_muxer_output|muxer_heartbeat' pkg/air/src/output/MpegTSOutputSink.cpp | wc -l  # MUST return >= 1 after implementation
# FORBIDDEN: MuxLoop waiting indefinitely for media without control-plane emission
# The media wait loop (sleep 1ms, retry) MUST be bounded by control-plane cadence check
grep -A10 'No video available.*wait briefly' pkg/air/src/output/MpegTSOutputSink.cpp | grep -E 'CONTROL.PLANE|cadence|heartbeat|500'  # MUST match after implementation
```

### Contract Tests

| Test | Verifies |
|------|----------|
| Phase10PipelineFlowControlTests | Slot-based gating |
| Phase9SymmetricBackpressureTests | A/V symmetric throttling |
| SinkLivenessContractTests | Non-blocking transport |

---

## Escape Hatches (NONE)

There are **no escape hatches** in Phase 10.

- No `#ifdef LEGACY_BLOCKING`
- No `if (emergency) wait()`
- No "temporary" violations

If a violation is necessary, it requires:
1. Explicit doctrine revision
2. Update to this guard document
3. New invariant ID documenting the exception

---

## Canonical References

| Document | Purpose |
|----------|---------|
| [PHASE10_PRESSURE_DOCTRINE.md](../PHASE10_PRESSURE_DOCTRINE.md) | What must happen under pressure |
| [PHASE10_FLOW_CONTROL.md](./PHASE10_FLOW_CONTROL.md) | Concrete implementation rules |
| [SOCKETSINK_CONTRACT.md](../components/SOCKETSINK_CONTRACT.md) | Transport contract |
| [OUTPUTBUS_CONTRACT.md](../components/OUTPUTBUS_CONTRACT.md) | Routing contract |
| [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) | Constitutional laws |

---

## Amendment History

| Date | Change | Author |
|------|--------|--------|
| 2026-02-04 | Initial freeze after elimination of: (1) `SocketSink::BlockingWrite()` sleep-retry loop, (2) hysteresis gating in FileProducer, (3) legacy `TsOutputSink` and `MpegTSPlayoutSink` dead code | Phase 10 Compliance Audit |
