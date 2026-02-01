# Phase 1 Atomic Task List

**Status:** Actionable
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
| **P1-PO-005** | INV-AIR-CONTENT-BEFORE-PAD | VERIFY | `pkg/air/tests/contracts/Phase10PipelineFlowControlTests.cpp` | Confirmed: test covers CONTENT-BEFORE-PAD gate logic prevents premature pad. |

### ProgramOutput Checklist

- [ ] P1-PO-001: Add TEST for INV-STARVATION-FAILSAFE-001
- [ ] P1-PO-002: Add TEST for INV-P10-SINK-GATE
- [ ] P1-PO-003: Add LOG for INV-P10-SINK-GATE
- [ ] P1-PO-004: VERIFY LAW-OUTPUT-LIVENESS test assertion
- [ ] P1-PO-005: VERIFY INV-AIR-CONTENT-BEFORE-PAD test coverage

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

- [ ] P1-EP-001: Add TEST for LAW-AUDIO-FORMAT
- [ ] P1-EP-002: Add LOG for LAW-AUDIO-FORMAT
- [ ] P1-EP-003: Add TEST for INV-AUDIO-HOUSE-FORMAT-001 rejection
- [ ] P1-EP-004: Add TEST for INV-ENCODER-NO-B-FRAMES-001
- [ ] P1-EP-005: VERIFY INV-AIR-IDR-BEFORE-OUTPUT gate reset test

---

## MpegTSOutputSink

| Task ID | Rule ID | Type | File(s) to Modify | Done Criteria |
|---------|---------|------|-------------------|---------------|
| **P1-MS-001** | INV-P9-BOOT-LIVENESS | LOG | `pkg/air/src/output/MpegTSOutputSink.cpp` | Log emitted with wall_time and latency_ms when first decodable TS packet sent. |
| **P1-MS-002** | INV-P9-AUDIO-LIVENESS | LOG | `pkg/air/src/output/MpegTSOutputSink.cpp` | Log emitted with first_audio_pts and header_write_time when audio stream goes live. |
| **P1-MS-003** | LAW-VIDEO-DECODABILITY | VERIFY | `pkg/air/tests/contracts/Phase84PersistentMpegTsMuxTests.cpp` | Confirmed: test asserts IDR present at segment boundary, TS valid with 0x47 sync. |

### MpegTSOutputSink Checklist

- [ ] P1-MS-001: Add LOG for INV-P9-BOOT-LIVENESS
- [ ] P1-MS-002: Add LOG for INV-P9-AUDIO-LIVENESS
- [ ] P1-MS-003: VERIFY LAW-VIDEO-DECODABILITY IDR-first test

---

## PlayoutEngine

| Task ID | Rule ID | Type | File(s) to Modify | Done Criteria |
|---------|---------|------|-------------------|---------------|
| **P1-PE-001** | INV-P8-ZERO-FRAME-BOOTSTRAP | LOG | `pkg/air/src/runtime/PlayoutEngine.cpp` | Log emitted when zero-frame segment detected and CONTENT-BEFORE-PAD gate bypassed. |
| **P1-PE-002** | INV-P9-BOOTSTRAP-READY | VERIFY | `pkg/air/tests/contracts/Phase9OutputBootstrapTests.cpp` | Confirmed: G9_002 test asserts readiness = commit + ≥1 video frame. |

### PlayoutEngine Checklist

- [ ] P1-PE-001: Add LOG for INV-P8-ZERO-FRAME-BOOTSTRAP
- [ ] P1-PE-002: VERIFY INV-P9-BOOTSTRAP-READY test (G9_002)

---

## Summary

| Type | Count | Task IDs |
|------|-------|----------|
| **TEST** | 5 | P1-PO-001, P1-PO-002, P1-EP-001, P1-EP-003, P1-EP-004 |
| **LOG** | 5 | P1-PO-003, P1-EP-002, P1-MS-001, P1-MS-002, P1-PE-001 |
| **VERIFY** | 5 | P1-PO-004, P1-PO-005, P1-EP-005, P1-MS-003, P1-PE-002 |
| **Total** | 15 | — |

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
| — | — | — |

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE1_EXECUTION_PLAN.md` | Detailed execution context |
| `docs/contracts/ENFORCEMENT_ROADMAP.md` | Phase 1 rule selection rationale |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions |
