# Phase 1 Atomic Task List

**Status:** ✅ Complete
**Source:** PHASE1_EXECUTION_PLAN.md
**Last Updated:** 2026-02-01

One task = one rule = one responsibility.

---

## ProgramOutput

| Task ID | Rule ID | Type | File(s) to Modify | Done Criteria |
|---------|---------|------|-------------------|---------------|
| **P1-PO-001** | INV-STARVATION-FAILSAFE-001 | TEST | `pkg/air/tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp` | Test asserts pad frame emitted within 100ms of buffer starvation detection. |
| **P1-PO-002** | INV-P10-SINK-GATE | TEST | `pkg/air/tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp` | Test asserts buffer depth unchanged when no sink attached and frame CT arrives. |
| **P1-PO-003** | INV-P10-SINK-GATE | LOG | `pkg/air/src/renderer/ProgramOutput.cpp` | Log emitted with CT value when frame not consumed due to missing sink. |
| **P1-PO-004** | LAW-OUTPUT-LIVENESS | VERIFY | `pkg/air/tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp` | Confirmed: existing test explicitly asserts "never blocks; no content → pad". |
| **P1-PO-005** | INV-AIR-CONTENT-BEFORE-PAD | VERIFY+TEST | (none) → `PacingInvariantContractTests.cpp` if FAIL | Verify coverage; if FAIL add test (gate blocks pad when empty; pad after first real frame). |

### ProgramOutput Checklist

- [x] P1-PO-001: Add TEST for INV-STARVATION-FAILSAFE-001
- [x] P1-PO-002: Add TEST for INV-P10-SINK-GATE
- [x] P1-PO-003: Add LOG for INV-P10-SINK-GATE
- [x] P1-PO-004: VERIFY LAW-OUTPUT-LIVENESS test assertion
- [x] P1-PO-005: VERIFY INV-AIR-CONTENT-BEFORE-PAD; if FAIL add TEST in same task

---

## EncoderPipeline

| Task ID | Rule ID | Type | File(s) to Modify | Done Criteria |
|---------|---------|------|-------------------|---------------|
| **P1-EP-001** | LAW-AUDIO-FORMAT | TEST | `pkg/air/tests/contracts/MpegTSPlayoutSink/MpegTSPlayoutSinkContractTests.cpp` | Test asserts non-house audio format rejected with error code, no output packet produced. |
| **P1-EP-002** | LAW-AUDIO-FORMAT | LOG | `pkg/air/src/playout_sinks/mpegts/EncoderPipeline.cpp` | Log emitted with received vs expected format when non-house audio rejected. |
| **P1-EP-003** | INV-AUDIO-HOUSE-FORMAT-001 | TEST | `pkg/air/tests/contracts/MpegTSPlayoutSink/MpegTSPlayoutSinkContractTests.cpp` | Test asserts explicit rejection path when sample_rate != house_sample_rate. |
| **P1-EP-004** | INV-ENCODER-NO-B-FRAMES-001 | TEST | `pkg/air/tests/contracts/MpegTSPlayoutSink/MpegTSPlayoutSinkContractTests.cpp` | Test asserts 60 encoded frames contain zero AV_PICTURE_TYPE_B packets. |
| **P1-EP-005** | INV-AIR-IDR-BEFORE-OUTPUT | VERIFY | `pkg/air/tests/contracts/MpegTSPlayoutSink/MpegTSPlayoutSinkContractTests.cpp` | Confirmed: test covers IDR gate reset on segment switch. |

### EncoderPipeline Checklist

- [x] P1-EP-001: Add TEST for LAW-AUDIO-FORMAT
- [x] P1-EP-002: Add LOG for LAW-AUDIO-FORMAT
- [x] P1-EP-003: Add TEST for INV-AUDIO-HOUSE-FORMAT-001 rejection
- [x] P1-EP-004: Add TEST for INV-ENCODER-NO-B-FRAMES-001
- [x] P1-EP-005: VERIFY INV-AIR-IDR-BEFORE-OUTPUT gate reset test

---

## MpegTSOutputSink

| Task ID | Rule ID | Type | File(s) to Modify | Done Criteria |
|---------|---------|------|-------------------|---------------|
| **P1-MS-001** | INV-P9-BOOT-LIVENESS | LOG | `pkg/air/src/output/MpegTSOutputSink.cpp` | Log emitted with wall_time and latency_ms when first decodable TS packet sent. |
| **P1-MS-002** | INV-P9-AUDIO-LIVENESS | LOG | `pkg/air/src/output/MpegTSOutputSink.cpp` | Log emitted with first_audio_pts and header_write_time when audio stream goes live. |
| **P1-MS-003** | LAW-VIDEO-DECODABILITY | VERIFY | `pkg/air/tests/contracts/Phase84PersistentMpegTsMuxTests.cpp` | Confirmed: test asserts IDR present at segment boundary, TS valid with 0x47 sync. |
| **P1-MS-004** | INV-P9-TS-EMISSION-LIVENESS | LOG | `pkg/air/src/output/MpegTSOutputSink.cpp` | Log `INV-P9-TS-EMISSION-LIVENESS: PCR-PACE initialized, deadline=500ms` emitted when PCR timing starts. |
| **P1-MS-005** | INV-P9-TS-EMISSION-LIVENESS | LOG | `pkg/air/src/output/MpegTSOutputSink.cpp` | Log `INV-P9-TS-EMISSION-LIVENESS: First TS emitted at {X}ms (OK)` emitted when first TS written within deadline. |
| **P1-MS-006** | INV-P9-TS-EMISSION-LIVENESS | LOG | `pkg/air/src/output/MpegTSOutputSink.cpp` | Log `INV-P9-TS-EMISSION-LIVENESS VIOLATION: No TS after {X}ms, blocking_reason={...}, vq={N}, aq={M}` when 500ms exceeded. |
| **P1-MS-007** | INV-P9-TS-EMISSION-LIVENESS | TEST | `pkg/air/tests/contracts/Phase9OutputBootstrapTests.cpp` | Test asserts first TS bytes emitted within 500ms of PCR-PACE init. |

### MpegTSOutputSink Checklist

- [x] P1-MS-001: Add LOG for INV-P9-BOOT-LIVENESS
- [x] P1-MS-002: Add LOG for INV-P9-AUDIO-LIVENESS
- [x] P1-MS-003: VERIFY LAW-VIDEO-DECODABILITY IDR-first test
- [x] P1-MS-004: Add LOG for INV-P9-TS-EMISSION-LIVENESS PCR-PACE init
- [x] P1-MS-005: Add LOG for INV-P9-TS-EMISSION-LIVENESS success
- [x] P1-MS-006: Add LOG for INV-P9-TS-EMISSION-LIVENESS violation
- [x] P1-MS-007: Add TEST for INV-P9-TS-EMISSION-LIVENESS 500ms bound

---

## PlayoutEngine

| Task ID | Rule ID | Type | File(s) to Modify | Done Criteria |create 
|---------|---------|------|-------------------|---------------|
| **P1-PE-001** | INV-P8-ZERO-FRAME-BOOTSTRAP | LOG | `pkg/air/src/runtime/PlayoutEngine.cpp` | Log emitted when zero-frame segment detected and CONTENT-BEFORE-PAD gate bypassed. |
| **P1-PE-002** | INV-P9-BOOTSTRAP-READY | VERIFY | `pkg/air/tests/contracts/Phase9OutputBootstrapTests.cpp` | Confirmed: G9_002 test asserts readiness = commit + ≥1 video frame. |

### PlayoutEngine Checklist

- [x] P1-PE-001: Add LOG for INV-P8-ZERO-FRAME-BOOTSTRAP
- [x] P1-PE-002: VERIFY INV-P9-BOOTSTRAP-READY test (G9_002)

---

## FileProducer

| Task ID | Rule ID | Type | File(s) to Modify | Done Criteria |
|---------|---------|------|-------------------|---------------|
| **P1-FP-001** | INV-P10-AUDIO-VIDEO-GATE | LOG | `pkg/air/src/producers/file/FileProducer.cpp` | Log `INV-P10-AUDIO-VIDEO-GATE: Video epoch set, awaiting first audio (deadline=100ms)` at VIDEO_EPOCH_SET. |
| **P1-FP-002** | INV-P10-AUDIO-VIDEO-GATE | LOG | `pkg/air/src/producers/file/FileProducer.cpp` | Log `INV-P10-AUDIO-VIDEO-GATE: First audio queued at {X}ms after video epoch` when audio arrives within deadline. |
| **P1-FP-003** | INV-P10-AUDIO-VIDEO-GATE | LOG | `pkg/air/src/producers/file/FileProducer.cpp` | Log `INV-P10-AUDIO-VIDEO-GATE VIOLATION: No audio after {X}ms (deadline=100ms), aq=0` when 100ms exceeded. |
| **P1-FP-004** | INV-P10-AUDIO-VIDEO-GATE | TEST | `pkg/air/tests/contracts/Phase10PipelineFlowControlTests.cpp` | Test asserts first audio frame queued within 100ms of VIDEO_EPOCH_SET. |

### FileProducer Checklist

- [x] P1-FP-001: Add LOG for INV-P10-AUDIO-VIDEO-GATE video epoch start
- [x] P1-FP-002: Add LOG for INV-P10-AUDIO-VIDEO-GATE success
- [x] P1-FP-003: Add LOG for INV-P10-AUDIO-VIDEO-GATE violation
- [x] P1-FP-004: Add TEST for INV-P10-AUDIO-VIDEO-GATE 100ms bound

---

## Summary

| Type | Count | Task IDs |
|------|-------|----------|
| **TEST** | 8 | P1-PO-001, P1-PO-002, P1-PO-005, P1-EP-001, P1-EP-003, P1-EP-004, P1-MS-007, P1-FP-004 |
| **LOG** | 11 | P1-PO-003, P1-EP-002, P1-MS-001, P1-MS-002, P1-MS-004, P1-MS-005, P1-MS-006, P1-PE-001, P1-FP-001, P1-FP-002, P1-FP-003 |
| **VERIFY** | 5 | P1-PO-004, P1-PO-005, P1-EP-005, P1-MS-003, P1-PE-002 |
| **Total** | 23 | — |

---

## Dependency Order

No dependencies between tasks — all are independent and can be executed in parallel.

**Recommended execution order by subsystem:**
1. VERIFY tasks first (confirm existing coverage)
2. LOG tasks second (low risk, high observability value)
3. TEST tasks last (require more implementation effort)

---

## Task State Tracking

When completing a task:

1. Check the box in the subsystem checklist above
2. Add completion date and commit hash below
3. Update PHASE1_EXECUTION_PLAN.md checklist

### Completed Tasks

| Task ID | Completed | Commit |
|---------|-----------|--------|
| P1-PO-001 | 2026-02-01 | 2853a5a |
| P1-PO-002 | 2026-02-01 | 2853a5a |
| P1-PO-003 | 2026-02-01 | 2853a5a |
| P1-PO-004 | 2026-02-01 | 2853a5a |
| P1-PO-005 | 2026-02-01 | 2853a5a |
| P1-EP-001 | 2026-02-01 | 6423dc7 |
| P1-EP-002 | 2026-02-01 | 6423dc7 |
| P1-EP-003 | 2026-02-01 | 6423dc7 |
| P1-EP-004 | 2026-02-01 | 6423dc7 |
| P1-EP-005 | 2026-02-01 | 6423dc7 |
| P1-MS-001 | 2026-02-01 | 820c7d5 |
| P1-MS-002 | 2026-02-01 | 820c7d5 |
| P1-MS-003 | 2026-02-01 | 820c7d5 |
| P1-MS-004 | 2026-02-01 | local |
| P1-MS-005 | 2026-02-01 | local |
| P1-MS-006 | 2026-02-01 | local |
| P1-MS-007 | 2026-02-01 | local |
| P1-PE-001 | 2026-02-01 | 9dab4cd |
| P1-PE-002 | 2026-02-01 | 9dab4cd |
| P1-FP-001 | 2026-02-01 | local |
| P1-FP-002 | 2026-02-01 | local |
| P1-FP-003 | 2026-02-01 | local |
| P1-FP-004 | 2026-02-01 | local |

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE1_EXECUTION_PLAN.md` | Detailed execution context |
| `docs/contracts/ENFORCEMENT_ROADMAP.md` | Phase 1 rule selection rationale |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions |

---

## Post-Phase 1: Broadcast-Grade Timing Audit (2026-02-01)

A formal audit on 2026-02-01 identified broadcast-grade timing violations. This resulted in:

### Critical: Authority Hierarchy Established (LAW-AUTHORITY-HIERARCHY)

The audit identified a fundamental contradiction between clock-based rules and frame-based rules. This has been resolved by establishing an explicit authority hierarchy:

```
LAW-AUTHORITY-HIERARCHY (Supreme)
"Clock authority supersedes frame completion for switch execution."

┌─────────────────────────────────────────────────────────────────┐
│ 1. Clock (LAW-CLOCK)        → WHEN transitions occur [AUTHORITY]│
│ 2. Frame (LAW-FRAME-EXEC)   → HOW precisely cuts happen [EXEC]  │
│ 3. Content (INV-SEGMENT-*)  → WHETHER sufficient [VALIDATION]   │
│                               (clock does NOT wait)             │
└─────────────────────────────────────────────────────────────────┘
```

**Anti-Pattern (BUG):** Code that waits for frame completion before executing a clock-scheduled switch.

**Correct Pattern:** Schedule switch at clock time. If content isn't ready, use safety rails (pad/silence). Never delay the clock.

### Rules Downgraded from Authority to Execution

| Rule ID | Old Interpretation | New Interpretation |
|---------|-------------------|-------------------|
| **LAW-FRAME-EXECUTION** | "Frame index is execution authority" | Governs execution precision (HOW), not timing (WHEN). Subordinate to LAW-CLOCK. |
| **INV-FRAME-001** | "Boundaries are frame-indexed, not time-based" | Frame-indexed for execution precision. Does not delay clock-scheduled transitions. |
| **INV-FRAME-003** | "CT derives from frame index" | CT derivation within segment. Frame completion does not gate switch execution. |

### Rules Demoted to Diagnostic Goals

| Rule ID | Superseded By | Reason |
|---------|---------------|--------|
| **INV-SWITCH-READINESS** | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Switch completes at declared boundary time, not when readiness conditions met |
| **INV-SWITCH-SUCCESSOR-EMISSION** | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Switch completes at declared boundary time, not when successor frame emitted |

### Amendments to Existing Rules

| Rule ID | Amendment |
|---------|-----------|
| **LAW-SWITCHING** | Added: "Transitions MUST complete within one video frame duration of scheduled absolute boundary time." |
| **INV-P10-BACKPRESSURE-SYMMETRIC** | Added: "Audio samples MUST NOT be dropped due to queue backpressure." |
| **INV-P8-SWITCH-TIMING** | Promoted to Layer 2 Coordination; strengthened to require completion within 1 frame |
| **INV-OUTPUT-READY-BEFORE-LIVE** | Clarified: "observable" includes safety rail output (pad frames) |

### New Phase 11 Tasks

Implementation is tracked in **CANONICAL_RULE_LEDGER.md § Phased Implementation Plan**.

| Phase | Tasks | New Invariants |
|-------|-------|----------------|
| **11A** | P11A-001 through P11A-005 | INV-AUDIO-SAMPLE-CONTINUITY-001 |
| **11B** | P11B-001 through P11B-006 | INV-BOUNDARY-TOLERANCE-001 (observability) |
| **11C** | P11C-001 through P11C-005 | INV-BOUNDARY-DECLARED-001 |
| **11D** | P11D-001 through P11D-008 | INV-SWITCH-DEADLINE-AUTHORITATIVE-001, INV-CONTROL-NO-POLL-001 |
| **11E** | P11E-001 through P11E-005 | (Core prefeed contract) |

**Total new tasks:** 29
**Estimated effort:** 13-19 days
