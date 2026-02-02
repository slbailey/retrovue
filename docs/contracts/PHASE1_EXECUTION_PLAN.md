# Phase 1 Execution Plan: Prevent Black/Silence

**Status:** ✅ Complete
**Source:** ENFORCEMENT_ROADMAP.md Phase 1 rules
**Last Updated:** 2026-02-01

Checklist grouped by subsystem. Status derived from Canonical Rule Ledger and test file analysis.

---

## ProgramOutput

| Rule ID | Test Exists? | Log Exists? | Status |
|---------|--------------|-------------|--------|
| **LAW-OUTPUT-LIVENESS** | Yes | Yes | ✅ Verified (P1-PO-004) |
| **INV-STARVATION-FAILSAFE-001** | Yes | Yes | ✅ Test added (P1-PO-001) |
| **INV-P10-SINK-GATE** | Yes | Yes | ✅ Both added (P1-PO-002, P1-PO-003) |
| **INV-AIR-CONTENT-BEFORE-PAD** | Yes | Yes | ✅ Verified + test added (P1-PO-005) |

### Tests to Add — ProgramOutput

**TEST-INV-STARVATION-FAILSAFE-001**
```
Given: Buffer empty for >1 frame duration
When: Render loop iterates
Then: Pad frame emitted within 100ms (bounded time)
Assert: Pad emission timestamp - starvation detection timestamp ≤ 100ms
```

**TEST-INV-P10-SINK-GATE**
```
Given: ProgramOutput started, no sink attached
When: Frame arrives in buffer with valid CT
Then: Frame is NOT consumed from buffer
Assert: Buffer depth unchanged; no ConsumeVideo call
```

### Logs to Add — ProgramOutput

**INV-P10-SINK-GATE violation log:**
```
[ProgramOutput] INV-P10-SINK-GATE: Frame CT=%ld not consumed - no sink attached
```

---

## EncoderPipeline

| Rule ID | Test Exists? | Log Exists? | Status |
|---------|--------------|-------------|--------|
| **LAW-AUDIO-FORMAT** | Yes | Yes | ✅ Test + log added (P1-EP-001, P1-EP-002) |
| **INV-AUDIO-HOUSE-FORMAT-001** | Yes | Yes | ✅ Test added (P1-EP-003) |
| **INV-ENCODER-NO-B-FRAMES-001** | Yes | Yes | ✅ Test added (P1-EP-004) |
| **INV-AIR-IDR-BEFORE-OUTPUT** | Yes | Yes | ✅ Verified (P1-EP-005) |

### Tests to Add — EncoderPipeline

**TEST-LAW-AUDIO-FORMAT**
```
Given: EncoderPipeline configured with house format (e.g., 48kHz stereo AAC)
When: Audio frame with non-house format (e.g., 44.1kHz) submitted
Then: Frame rejected with explicit error
Assert: EncodeAudio returns error code; no output packet produced
```

**TEST-INV-AUDIO-HOUSE-FORMAT-001-REJECTION**
```
Given: EncoderPipeline initialized
When: Audio with sample_rate != house_sample_rate submitted
Then: Encoder rejects frame and logs violation
Assert: Return value indicates rejection; log contains "INV-AUDIO-HOUSE-FORMAT-001"
```

**TEST-INV-ENCODER-NO-B-FRAMES-001**
```
Given: EncoderPipeline encoding video
When: 60 frames encoded (2 GOPs at gop_size=30)
Then: No output packet has AV_PICTURE_TYPE_B
Assert: All packets are I or P frames; codec_ctx->max_b_frames == 0
```

### Logs to Add — EncoderPipeline

**LAW-AUDIO-FORMAT violation log:**
```
[EncoderPipeline] LAW-AUDIO-FORMAT VIOLATION: Received format=%d Hz, expected house_format=%d Hz
```

---

## MpegTSOutputSink

| Rule ID | Test Exists? | Log Exists? | Status |
|---------|--------------|-------------|--------|
| **INV-P9-BOOT-LIVENESS** | Yes | Yes | ✅ Log added (P1-MS-001) |
| **INV-P9-AUDIO-LIVENESS** | Yes | Yes | ✅ Log added (P1-MS-002) |
| **LAW-VIDEO-DECODABILITY** | Yes | Yes | ✅ Verified (P1-MS-003) |
| **INV-P9-TS-EMISSION-LIVENESS** | Yes | Yes | ✅ Logs + test added (P1-MS-004, P1-MS-005, P1-MS-006, P1-MS-007) |

### Tests to Add — MpegTSOutputSink

- [x] `TEST_INV_P9_TS_EMISSION_LIVENESS_500ms` — First TS within 500ms of PCR-PACE init (P1-MS-007)

### Logs to Add — MpegTSOutputSink

**INV-P9-BOOT-LIVENESS log:**
```
[MpegTSOutputSink] INV-P9-BOOT-LIVENESS: First decodable TS emitted at wall_time=%ld, latency_ms=%d
```

**INV-P9-AUDIO-LIVENESS log:**
```
[MpegTSOutputSink] INV-P9-AUDIO-LIVENESS: Audio stream live, first_audio_pts=%ld, header_write_time=%ld
```

**INV-P9-TS-EMISSION-LIVENESS logs (P1-MS-004, P1-MS-005, P1-MS-006):**
- PCR-PACE init: `INV-P9-TS-EMISSION-LIVENESS: PCR-PACE initialized, deadline=500ms`
- Success: `INV-P9-TS-EMISSION-LIVENESS: First TS emitted at %dms (OK)`
- Violation: `INV-P9-TS-EMISSION-LIVENESS VIOLATION: No TS after %dms, blocking_reason=%s, vq=%d, aq=%d`

---

## PlayoutEngine / Bootstrap

| Rule ID | Test Exists? | Log Exists? | Status |
|---------|--------------|-------------|--------|
| **INV-P9-BOOTSTRAP-READY** | Yes | Yes | ✅ Verified (P1-PE-002) |
| **INV-P8-ZERO-FRAME-BOOTSTRAP** | Yes | Yes | ✅ Log added (P1-PE-001) |

### Tests to Add — PlayoutEngine

None required — tests exist.

### Logs to Add — PlayoutEngine

**INV-P8-ZERO-FRAME-BOOTSTRAP log:**
```
[PlayoutEngine] INV-P8-ZERO-FRAME-BOOTSTRAP: Zero-frame segment detected, CONTENT-BEFORE-PAD gate bypassed
```

---

## Summary Checklist

### Tests Added (5) ✅

- [x] `TEST-INV-STARVATION-FAILSAFE-001` — ProgramOutput starvation → pad within bounded time
- [x] `TEST-INV-P10-SINK-GATE` — No consumption before sink attached
- [x] `TEST-LAW-AUDIO-FORMAT` — Non-house audio rejected at encoder
- [x] `TEST-INV-AUDIO-HOUSE-FORMAT-001-REJECTION` — Explicit rejection path tested
- [x] `TEST-INV-ENCODER-NO-B-FRAMES-001` — No B-frames in output

### Logs Added (5) ✅

- [x] `INV-P10-SINK-GATE` — Log when frame not consumed due to no sink
- [x] `LAW-AUDIO-FORMAT` — Log when non-house format rejected
- [x] `INV-P9-BOOT-LIVENESS` — Log first decodable TS emission with latency
- [x] `INV-P9-AUDIO-LIVENESS` — Log audio stream liveness confirmation
- [x] `INV-P8-ZERO-FRAME-BOOTSTRAP` — Log zero-frame segment gate bypass

### Tests Verified (5) ✅

- [x] `LAW-OUTPUT-LIVENESS` — Confirm "never blocks" assertion exists
- [x] `INV-AIR-CONTENT-BEFORE-PAD` — Confirm gate logic tested (Phase10PipelineFlowControlTests)
- [x] `INV-AIR-IDR-BEFORE-OUTPUT` — Confirm gate reset on switch tested
- [x] `LAW-VIDEO-DECODABILITY` — Confirm IDR-first at segment boundary tested
- [x] `INV-P9-BOOTSTRAP-READY` — Confirm G9_002 covers commit + ≥1 frame

---

## File Locations for Implementation

| Subsystem | Test File | Source File for Logs |
|-----------|-----------|---------------------|
| ProgramOutput | `pkg/air/tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp` | `pkg/air/src/renderer/ProgramOutput.cpp` |
| EncoderPipeline | `pkg/air/tests/contracts/MpegTSPlayoutSink/MpegTSPlayoutSinkContractTests.cpp` | `pkg/air/src/playout_sinks/mpegts/EncoderPipeline.cpp` |
| MpegTSOutputSink | `pkg/air/tests/contracts/Phase9OutputBootstrapTests.cpp` | `pkg/air/src/output/MpegTSOutputSink.cpp` |
| PlayoutEngine | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` | `pkg/air/src/runtime/PlayoutEngine.cpp` |
| FileProducer | `pkg/air/tests/contracts/Phase10PipelineFlowControlTests.cpp` | `pkg/air/src/producers/file/FileProducer.cpp` |

---

## Completion Criteria

Phase 1 is complete when:

1. ✅ All 5 tests added and passing
2. ✅ All 5 logs instrumented and emitting
3. ✅ All 5 verification items confirmed
4. Zero Phase 1 rule violations in CI

**Status:** Phase 1 implementation complete (2026-02-01).

**Release Gate:** Any Phase 1 violation is a release blocker.

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/ENFORCEMENT_ROADMAP.md` | Source of Phase 1 rule list |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions |
| `docs/contracts/GAP_REMEDIATION_PLAN.md` | Detailed remediation context |

---

## Post-Phase 1: Broadcast-Grade Timing Audit (2026-02-01)

Following Phase 1 completion, a formal audit identified broadcast-grade timing violations requiring additional invariants. This work is tracked as **Phase 11** (11A-11E).

### Critical: Authority Hierarchy Established (LAW-AUTHORITY-HIERARCHY)

The audit identified a fundamental contradiction between clock-based rules (LAW-CLOCK, LAW-SWITCHING) and frame-based rules (LAW-FRAME-EXECUTION, INV-FRAME-001, INV-FRAME-003). This has been **definitively resolved** by establishing an explicit authority hierarchy:

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAW-AUTHORITY-HIERARCHY                       │
│         "Clock authority supersedes frame completion"            │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   LAW-CLOCK   │    │ LAW-SWITCHING │    │LAW-FRAME-EXEC │
│ WHEN things   │    │ WHEN switch   │    │ HOW precisely │
│ happen        │    │ executes      │    │ cuts happen   │
│ [AUTHORITY]   │    │ [AUTHORITY]   │    │ [EXECUTION]   │
└───────────────┘    └───────────────┘    └───────────────┘
                              │
                              ▼
                    ┌───────────────┐
                    │INV-SEGMENT-   │
                    │CONTENT-001    │
                    │ WHETHER       │
                    │ sufficient    │
                    │ [VALIDATION]  │
                    │ (clock does   │
                    │  not wait)    │
                    └───────────────┘
```

**Key Principle:** If frame completion and clock deadline conflict, **clock wins**. Frame-based rules describe *how to execute* within a segment, not *whether to execute* a scheduled transition.

**Anti-Pattern (BUG):** Code that waits for frame completion before executing a clock-scheduled switch. This inverts the hierarchy and causes boundary timing violations.

**Correct Pattern:** Schedule switch at clock time. If content isn't ready, use safety rails (pad/silence). Never delay the clock.

### Rules Downgraded from Authority to Execution

| Rule ID | Old Interpretation | New Interpretation |
|---------|-------------------|-------------------|
| **LAW-FRAME-EXECUTION** | "Frame index is execution authority" | Governs execution precision (HOW), not timing (WHEN). Subordinate to LAW-CLOCK. |
| **INV-FRAME-001** | "Boundaries are frame-indexed, not time-based" | Frame-indexed for execution precision. Does not delay clock-scheduled transitions. |
| **INV-FRAME-003** | "CT derives from frame index" | CT derivation within segment. Frame completion does not gate switch execution. |

### Rules Demoted to Diagnostic Goals

The following rules were demoted from **completion gates** to **diagnostic goals** because they conflict with deadline-authoritative switching semantics:

| Rule ID | Old Role | New Role | Superseded By |
|---------|----------|----------|---------------|
| **INV-SWITCH-READINESS** | Completion gate | Diagnostic goal | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 |
| **INV-SWITCH-SUCCESSOR-EMISSION** | Completion gate | Diagnostic goal | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 |

**Impact:** These rules still exist and should still be logged/measured, but they no longer gate switch completion. Switches complete at the declared boundary time regardless of readiness state.

### New Invariants Added (Phase 11)

| Rule ID | Description | Phase |
|---------|-------------|-------|
| INV-BOUNDARY-TOLERANCE-001 | Grid transitions within 1 frame of boundary | 11B, 11D |
| INV-BOUNDARY-DECLARED-001 | SwitchToLive carries `target_boundary_time_ms` | 11C |
| INV-AUDIO-SAMPLE-CONTINUITY-001 | No audio drops under backpressure | 11A |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Scheduling feasibility at planning time, not runtime | 11D |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | First boundary must satisfy startup latency constraint | 11D |
| INV-SWITCH-ISSUANCE-DEADLINE-001 | Switch issuance deadline-scheduled, not cadence-detected | 11D |
| INV-CONTROL-NO-POLL-001 | No poll/retry for switch readiness | 11D, 11E |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Switch at declared time regardless of readiness | 11D |

### Phase 11 Implementation Plan

See **CANONICAL_RULE_LEDGER.md § Phased Implementation Plan** for full details.

| Phase | Goal | Dependencies | Risk |
|-------|------|--------------|------|
| **11A** | Audio sample continuity | None | Low |
| **11B** | Boundary timing observability | None | Very Low |
| **11C** | Declarative boundary protocol (proto) | None | Medium |
| **11D** | Deadline-authoritative switching | 11C | High |
| **11E** | Prefeed timing contract | 11D | Medium |

**Status:** Phase 11D closed 2026-02-02 (P11D-001 through P11D-012). See docs/contracts/tasks/phase11/README.md.

**Execution Order:**
1. Parallel: 11A + 11B + 11C
2. Sequential: 11D → 11E
