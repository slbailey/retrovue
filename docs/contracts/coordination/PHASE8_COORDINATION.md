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
| **INV-P8-SWITCH-TIMING** | CONTRACT | PlayoutEngine | P8 | No | Yes |

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
| INV-P8-AUDIO-PRIME-001 | No header until first audio; no video encode before header written |
| INV-P8-IO-UDS-001 | UDS/output must not block on prebuffer; prebuffering disabled for UDS |
| INV-P8-SWITCH-TIMING | Core: switch at boundary; **MUST complete within one frame of boundary**; violation log if >1 frame late |

---

## Broadcast-Grade Timing Invariants

Invariants added by the 2026-02-01 Broadcast-Grade Timing Compliance Audit.

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-BOUNDARY-TOLERANCE-001** | CONTRACT | PlayoutEngine | P8 | No | Yes |
| **INV-BOUNDARY-DECLARED-001** | CONTRACT | Core + AIR | P8 | No | Yes |
| **INV-AUDIO-SAMPLE-CONTINUITY-001** | CONTRACT | FileProducer, FrameRingBuffer | RUNTIME | No | Yes |
| **INV-SCHED-PLAN-BEFORE-EXEC-001** | CONTRACT | Core | SCHEDULE-TIME | No | Yes |
| **INV-STARTUP-BOUNDARY-FEASIBILITY-001** | CONTRACT | Core | SCHEDULE-TIME | No | Yes |
| **INV-SWITCH-ISSUANCE-DEADLINE-001** | CONTRACT | Core | RUNTIME | No | Yes |
| **INV-LEADTIME-MEASUREMENT-001** | CONTRACT | Core + AIR | P8 | No | Yes |
| **INV-CONTROL-NO-POLL-001** | CONTRACT | Core | RUNTIME | No | Yes |
| **INV-SWITCH-DEADLINE-AUTHORITATIVE-001** | CONTRACT | PlayoutEngine | P8 | No | Yes |
| **INV-SWITCH-ISSUANCE-TERMINAL-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes |
| **INV-SWITCH-ISSUANCE-ONESHOT-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes |
| **INV-BOUNDARY-LIFECYCLE-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes |
| **INV-BOUNDARY-DECLARED-MATCHES-PLAN-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-BOUNDARY-TOLERANCE-001 | Grid boundary transitions MUST complete within one video frame duration (33.33ms at 30fps) of the absolute scheduled boundary time |
| INV-BOUNDARY-DECLARED-001 | SwitchToLive MUST include `target_boundary_time_ms` parameter; Core declares intent, AIR executes at that time |
| INV-AUDIO-SAMPLE-CONTINUITY-001 | Audio sample continuity MUST be preserved; audio samples MUST NOT be dropped due to queue backpressure; overflow triggers producer throttling |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Scheduling feasibility MUST be determined once, at planning time. Only boundaries that are already feasible by construction may enter execution. Runtime MUST NOT discover, repair, delay, or re-evaluate boundary feasibility. |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | The first scheduled boundary MUST satisfy `boundary_time >= station_utc + startup_latency + MIN_PREFEED_LEAD_TIME`. This is a constraint on schedule content, not on planning_time. |
| INV-SWITCH-ISSUANCE-DEADLINE-001 | SwitchToLive issuance MUST be deadline-scheduled and issued no later than `boundary_time - MIN_PREFEED_LEAD_TIME`. Cadence-based detection, tick loops, and jitter padding are forbidden. |
| INV-LEADTIME-MEASUREMENT-001 | Prefeed lead time MUST be evaluated using the issuance timestamp supplied by Core (`issued_at_time_ms`), not AIR receipt time. Transport jitter MUST NOT affect feasibility determination. |
| INV-CONTROL-NO-POLL-001 | Core MUST NOT poll AIR for switch readiness; NOT_READY indicates protocol error (prefeed too late), not a condition to retry. Tick-based reissuance is forbidden. |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | When `target_boundary_time_ms` is provided, AIR MUST execute the switch at that wall-clock time +/- 1 frame; internal readiness is AIR's responsibility |
| INV-SWITCH-ISSUANCE-TERMINAL-001 | Exception during SwitchToLive issuance MUST transition boundary to FAILED_TERMINAL state. No retry, no re-arm. |
| INV-SWITCH-ISSUANCE-ONESHOT-001 | SwitchToLive MUST be issued exactly once per boundary. Duplicate attempts are suppressed; duplicate into FAILED_TERMINAL is fatal. |
| INV-BOUNDARY-LIFECYCLE-001 | Boundary state transitions MUST be unidirectional (NONE->PLANNED->...->LIVE or ->FAILED_TERMINAL). Illegal transitions force FAILED_TERMINAL. |
| INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 | target_boundary_ms sent to AIR MUST equal the boundary computed from the active playout plan, NOT a derived `now + X` value. |

---

## Boundary Lifecycle State Machine

```
NONE -> PLANNED -> PRELOAD_ISSUED -> SWITCH_SCHEDULED -> SWITCH_ISSUED -> LIVE
                                                                           ^
Any state --------------------------------------------------------> FAILED_TERMINAL
```

### Allowed Transitions

| From | To |
|------|----|
| NONE | PLANNED |
| PLANNED | PRELOAD_ISSUED, FAILED_TERMINAL |
| PRELOAD_ISSUED | SWITCH_SCHEDULED, FAILED_TERMINAL |
| SWITCH_SCHEDULED | SWITCH_ISSUED, FAILED_TERMINAL |
| SWITCH_ISSUED | LIVE, FAILED_TERMINAL |
| LIVE | NONE, PLANNED (next boundary) |
| FAILED_TERMINAL | (absorbing) |

### Terminal States

- `LIVE`: Success terminal for this boundary; next boundary can be planned
- `FAILED_TERMINAL`: Failure terminal; absorbing, no exit

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) - Layer 0 Laws
- [PHASE8_SEMANTICS.md](../semantics/PHASE8_SEMANTICS.md) - Phase 8 Semantics
- [PHASE9_BOOTSTRAP.md](./PHASE9_BOOTSTRAP.md) - Phase 9 Bootstrap
- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth
