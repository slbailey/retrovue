# Layer 2 - Phase 8 Coordination Invariants

**Status:** Canonical
**Scope:** Write barriers, switch orchestration, segment commit, and timing coordination
**Authority:** Refines Layer 0 Laws and Layer 1 Semantics; does not override them

---

## Phase 8 Coordination Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-P8-007** | CONTRACT | TimelineController | P8 | Yes | No |
| **INV-P8-SWITCH-001** | CONTRACT | PlayoutEngine | P8 | Yes | No |
| **INV-P8-SHADOW-PACE** | CONTRACT | FileProducer | P8 | Yes | No |
| **INV-P8-AUDIO-GATE** | CONTRACT | FileProducer | P8 | Yes | No |
| **INV-P8-SEGMENT-COMMIT** | CONTRACT | TimelineController | P8 | Yes | No |
| **INV-P8-SEGMENT-COMMIT-EDGE** | CONTRACT | TimelineController | P8 | Yes | No |
| **INV-P8-SWITCH-ARMED** | CONTRACT | PlayoutEngine | P8 | Yes | No |
| **INV-P8-WRITE-BARRIER-DEFERRED** | CONTRACT | PlayoutEngine | P8 | Yes | No |
| **INV-P8-EOF-SWITCH** | CONTRACT | PlayoutEngine | P8 | Yes | No |
| **INV-P8-PREVIEW-EOF** | CONTRACT | PlayoutEngine | P8 | Yes | No |
| **INV-P8-SWITCHWATCHER-STOP-TARGET-001** | CONTRACT | PlayoutEngine | P8 | Yes | Yes |
| **INV-P8-SWITCHWATCHER-COMMITGEN-EDGE-SAFETY-002** | CONTRACT | PlayoutEngine | P8 | Yes | No |
| **INV-P8-COMMITGEN-RETIREMENT-SEMANTICS-003** | CONTRACT | PlayoutEngine | P8 | Yes | No |
| **INV-P8-SHADOW-FLUSH** | CONTRACT | FileProducer | P8 | Yes | No |
| **INV-P8-ZERO-FRAME-READY** | CONTRACT | FileProducer | P8 | Yes | No |
| **INV-P8-ZERO-FRAME-BOOTSTRAP** | CONTRACT | ProgramOutput | P8 | Yes | No |
| **INV-P8-AV-SYNC** | CONTRACT | FileProducer | P8 | Yes | No |
| **INV-P8-AUDIO-PRIME-001** | CONTRACT | MpegTSOutputSink | P8 | Yes | No |
| **INV-P8-IO-UDS-001** | CONTRACT | MpegTSOutputSink | P8 | No | No |
| **INV-P8-SWITCH-TIMING** | CONTRACT | AIR (PlayoutEngine) | P8 | No | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-007 | Write Barrier Finality - post-barrier writes = 0 |
| INV-P8-SWITCH-001 | Mapping pending BEFORE preview fills; write barrier on live before new segment |
| INV-P8-SHADOW-PACE | Shadow caches first frame, waits in place; no run-ahead decode |
| INV-P8-AUDIO-GATE | Audio gated only while shadow (and while mapping pending) |
| INV-P8-SEGMENT-COMMIT | First frame admitted -> segment commits, owns CT; old segment RequestStop |
| INV-P8-SEGMENT-COMMIT-EDGE | Generation counter per commit for multi-switch edge detection |
| INV-P8-SWITCH-ARMED | No LoadPreview while switch armed; FATAL if reset reached while armed |
| INV-P8-WRITE-BARRIER-DEFERRED | Write barrier on live waits until preview shadow ready |
| INV-P8-EOF-SWITCH | Live EOF -> switch completes immediately (no buffer depth wait) |
| INV-P8-PREVIEW-EOF | Preview EOF with frames -> complete with lower thresholds |
| INV-P8-SWITCHWATCHER-STOP-TARGET-001 | Switch machinery must not stop/disable successor as result of bookkeeping |
| INV-P8-SWITCHWATCHER-COMMITGEN-EDGE-SAFETY-002 | Post-swap commit-gen transitions must not retire successor |
| INV-P8-COMMITGEN-RETIREMENT-SEMANTICS-003 | Retirement ignores successor activation or same-segment bookkeeping |
| INV-P8-SHADOW-FLUSH | On leaving shadow: flush cached first frame to buffer immediately |
| INV-P8-ZERO-FRAME-READY | When frame_count=0, signal shadow_decode_ready immediately |
| INV-P8-ZERO-FRAME-BOOTSTRAP | When no_content_segment=true, bypass CONTENT-BEFORE-PAD gate |
| INV-P8-AV-SYNC | Audio gated until video locks mapping (no audio ahead of video at switch) |
| INV-P8-AUDIO-PRIME-001 | **AMENDED (Phase 9 supersedes):** Header written immediately; audio presence ensured by real audio OR injected silence (INV-P9-AUDIO-LIVENESS); video must not be encoded before header written. Original "no header until first audio" gate retired per Phase 9 broadcast-correctness requirements. |
| INV-P8-IO-UDS-001 | UDS/output must not block on prebuffer; prebuffering disabled for UDS |
| INV-P8-SWITCH-TIMING | AIR execution: given a declared boundary, switch **MUST complete within one frame of boundary**; violation log if >1 frame late. (Core declares boundary via INV-BOUNDARY-DECLARED-001) |

---

## AIR-Only Timing Invariant (Retained)

This invariant is AIR-internal and remains in Phase 8 Coordination.

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-AUDIO-SAMPLE-CONTINUITY-001** | CONTRACT | FileProducer, FrameRingBuffer | RUNTIME | No | Yes |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-AUDIO-SAMPLE-CONTINUITY-001 | Audio sample continuity MUST be preserved; audio samples MUST NOT be dropped due to queue backpressure; overflow triggers producer throttling |

---

## Boundary Lifecycle and Protocol Invariants (Moved)

The following invariants have been moved to Core contracts where they belong:

**Location:** [/pkg/core/docs/contracts/lifecycle/BOUNDARY_LIFECYCLE.md](../../../pkg/core/docs/contracts/lifecycle/BOUNDARY_LIFECYCLE.md)

Moved invariants:
- INV-BOUNDARY-TOLERANCE-001 (Protocol)
- INV-BOUNDARY-DECLARED-001 (Protocol)
- INV-SCHED-PLAN-BEFORE-EXEC-001 (Core planning)
- INV-STARTUP-BOUNDARY-FEASIBILITY-001 (Core planning)
- INV-SWITCH-ISSUANCE-DEADLINE-001 (Core issuance)
- INV-LEADTIME-MEASUREMENT-001 (Protocol)
- INV-CONTROL-NO-POLL-001 (Protocol)
- INV-SWITCH-DEADLINE-AUTHORITATIVE-001 (Protocol)
- INV-SWITCH-ISSUANCE-TERMINAL-001 (Core issuance)
- INV-SWITCH-ISSUANCE-ONESHOT-001 (Core issuance)
- INV-BOUNDARY-LIFECYCLE-001 (Core lifecycle)
- INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 (Core planning)
- Boundary Lifecycle State Machine (Core lifecycle)

AIR does not define, plan, or manage boundary lifecycle states. AIR receives boundary declarations via Protocol and executes them.

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) - Layer 0 Laws
- [PHASE8_SEMANTICS.md](../semantics/PHASE8_SEMANTICS.md) - Phase 8 Semantics
- [PHASE9_BOOTSTRAP.md](./PHASE9_BOOTSTRAP.md) - Phase 9 Bootstrap
- [BOUNDARY_LIFECYCLE.md](../../../pkg/core/docs/contracts/lifecycle/BOUNDARY_LIFECYCLE.md) - Core boundary lifecycle (moved)
- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth
