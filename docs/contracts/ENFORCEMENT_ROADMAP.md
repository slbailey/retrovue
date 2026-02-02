# Three-Phase Enforcement Roadmap

**Status:** Approved
**Source:** Canonical Rule Ledger coverage gaps and operational criticality
**Last Updated:** 2026-02-01

Based on Canonical Rule Ledger coverage gaps and operational criticality.

---

## Phase 1 — Prevent Black/Silence

Rules that must be enforced immediately to prevent viewer-visible failures.

| Rule ID | Justification |
|---------|---------------|
| **LAW-OUTPUT-LIVENESS** | Core guarantee: output never blocks; no content → pad. Violation = black screen. |
| **LAW-VIDEO-DECODABILITY** | Every segment starts with IDR. Violation = decoder fails to render until next keyframe. |
| **INV-AIR-IDR-BEFORE-OUTPUT** | No packets until IDR produced. Violation = garbage frames on tune-in. |
| **INV-AIR-CONTENT-BEFORE-PAD** | Pad only after real content. Violation = pad loop with no escape. |
| **INV-STARVATION-FAILSAFE-001** | Starvation → pad within bounded time. Violation = indefinite freeze then crash. |
| **INV-P9-BOOTSTRAP-READY** | Readiness = commit + ≥1 frame. Violation = premature LIVE with empty buffer. |
| **INV-P9-BOOT-LIVENESS** | Newly attached sink emits decodable TS. Violation = viewer connects, sees nothing. |
| **INV-P10-SINK-GATE** | No consumption before sink attached. Violation = frames lost, viewer sees gap. |
| **INV-P8-ZERO-FRAME-BOOTSTRAP** | Zero-frame segment bypasses content gate. Violation = deadlock waiting for impossible frame. |
| **INV-ENCODER-NO-B-FRAMES-001** | No B-frames in output. Violation = decoder stalls on missing reference frames. |
| **LAW-AUDIO-FORMAT** | House format enforced at encoder. Violation = audio encode failure mid-stream. |
| **INV-AUDIO-HOUSE-FORMAT-001** | Reject non-house audio. Violation = encoder crash or garbled audio. |
| **INV-P9-AUDIO-LIVENESS** | Continuous monotonic audio PTS from header. Violation = audio drops to silence. |
| **INV-P9-TS-EMISSION-LIVENESS** | First TS within 500ms of PCR-PACE init. Violation = viewer connects, waits 5+ seconds. |
| **INV-P10-AUDIO-VIDEO-GATE** | Audio queued within 100ms of video epoch. Violation = mux blocked, no TS bytes flow. |

---

## Phase 2 — Stabilize Long-Running Playout

Rules that prevent drift, resource exhaustion, and operational degradation over hours/days.

| Rule ID | Justification |
|---------|---------------|
| **LAW-CLOCK** | MasterClock is sole time authority. Violation = drift accumulates over hours. |
| **LAW-TIMELINE** | TimelineController owns CT mapping. Violation = CT divergence between components. |
| **INV-FRAME-003** | CT = epoch + (frame_index × frame_duration). Violation = progressive timing drift. |
| **INV-P10-FRAME-INDEXED-EXECUTION** | Progress by frame index, not elapsed time. Violation = 0.1% error compounds over days. |
| **INV-PACING-ENFORCEMENT-002** | Freeze-then-pad, no drops, no catch-up. Violation = timing instability after starvation. |
| **INV-P10-BUFFER-EQUILIBRIUM** | Buffer oscillates around target. Violation = memory exhaustion or starvation. |
| **INV-P10-PRODUCER-THROTTLE** | Decode rate governed by consumer. Violation = unbounded buffer growth. |
| **INV-P10-BACKPRESSURE-SYMMETRIC** | A/V throttled together. Violation = progressive A/V desync. |
| **RULE-P10-DECODE-GATE** | Slot-based blocking at decode. Violation = buffer overflow crash. |
| **INV-LIFECYCLE-IDEMPOTENT-001** | Start/Stop idempotent. Violation = resource leak on restart. |
| **INV-TEARDOWN-BOUNDED-001** | Teardown within timeout. Violation = orphan threads, file handle leaks. |
| **INV-CONFIG-IMMUTABLE-001** | No config change after construction. Violation = undefined state mid-session. |
| **INV-SINK-FAULT-LATCH-001** | Fault persists until reset. Violation = silent recovery masks recurring errors. |
| **INV-NETWORK-BACKPRESSURE-DROP-001** | Network full → drop, not block. Violation = timing loop blocked by slow client. |
| **INV-ENCODER-GOP-FIXED-001** | Fixed GOP, no adaptive sizing. Violation = unpredictable segment boundaries. |
| **INV-ENCODER-BITRATE-BOUNDED-001** | Bitrate within ±10%. Violation = muxer buffer overflow on spikes. |
| **LAW-SWITCHING** | No gaps, no PTS regression at switch. Violation = glitch every segment boundary. |
| **INV-SWITCH-READINESS** | Switch when video≥2, sink attached, format locked. Violation = glitch on every switch. |
| **INV-SWITCH-SUCCESSOR-EMISSION** | Switch complete when real successor frame emitted. Violation = stale frame lingers. |
| **LAW-RUNTIME-AUDIO-AUTHORITY** | Producer audio ≥90% rate or auto-downgrade. Violation = indefinite mux stall. |

---

## Phase 3 — Diagnostics and Operator Confidence

Rules that improve debugging, observability, and operational trust.

| Rule ID | Justification |
|---------|---------------|
| **LAW-OBS-001** | Intent evidence for every action. Enables "why did this happen" analysis. |
| **LAW-OBS-002** | Correlation IDs link related events. Enables tracing across components. |
| **LAW-OBS-003** | Result evidence for every action. Enables success/failure audit. |
| **LAW-OBS-004** | Timestamps on significant events. Enables latency analysis. |
| **LAW-OBS-005** | Phase/state transitions logged. Enables state machine reconstruction. |
| **INV-P8-WRITE-BARRIER-DIAG** | Log when frame dropped by write barrier. Isolates switch-time frame loss. |
| **INV-P8-AUDIO-PRIME-STALL** | Log if video waits too long for audio prime. Isolates bootstrap delays. |
| **INV-P10-FRAME-DROP-POLICY** | Log every drop with reason. Enables drop root cause analysis. |
| **INV-P10-PAD-REASON** | Classify pad by root cause. Distinguishes starvation types. |
| **INV-NO-PAD-WHILE-DEPTH-HIGH** | Log violation: pad with deep buffer. Catches logic bugs vs real starvation. |
| **INV-TIMING-DESYNC-LOG-001** | Log when >50ms behind schedule. Early warning of timing problems. |
| **INV-P8-SWITCH-TIMING** | Log if switch pending after boundary. Catches Core timing issues. |
| **INV-P8-012** | Deterministic replay verification. Enables reproducible debugging. |
| **INV-SINK-PRODUCER-THREAD-ISOLATION-001** | Log cross-thread blocking. Isolates deadlock sources. |
| **RULE-CORE-RUNTIME-READONLY** | Enforce read-only config at runtime. Prevents config corruption. |
| **RULE-CORE-PLAYLOG-AUTHORITY** | Only ScheduleService writes playlog. Prevents duplicate as-run records. |
| **RULE-CANONICAL-GATING** | Log non-canonical asset rejection. Audit trail for content approval. |
| **INV-P10-REALTIME-THROUGHPUT** | Log throughput deviation. Enables rate monitoring. |
| **INV-OUTPUT-READY-BEFORE-LIVE** | Log output pipeline readiness. Confirms clean startup sequence. |

---

## Summary

| Phase | Focus | Rule Count |
|-------|-------|------------|
| **Phase 1** | Prevent black/silence | 15 |
| **Phase 2** | Stabilize long-running | 20 |
| **Phase 3** | Diagnostics/confidence | 20 |

---

## Implementation Notes

### Phase 1 Completion Criteria
- All 13 rules have passing contract tests
- Zero tolerance: any Phase 1 violation is a release blocker

### Phase 2 Completion Criteria
- All 19 rules have passing contract tests
- 24-hour continuous playout without resource growth or drift

### Phase 3 Completion Criteria
- All 20 rules have log instrumentation
- Operator can diagnose any failure from logs alone without code inspection

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Source of truth for all rules |
| `docs/contracts/GAP_REMEDIATION_PLAN.md` | Detailed remediation actions per rule |
| `pkg/air/docs/contracts/PROPOSED-INVARIANTS-FROM-HARVEST.md` | Pending promotion invariants |
