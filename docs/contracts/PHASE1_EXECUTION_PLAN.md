# Phase 1 Execution Plan: Prevent Black/Silence

**Status:** Actionable
**Source:** ENFORCEMENT_ROADMAP.md Phase 1 rules
**Last Updated:** 2026-02-01

Checklist grouped by subsystem. Status derived from Canonical Rule Ledger and test file analysis.

---

## ProgramOutput

| Rule ID | Test Exists? | Log Exists? | Action Required |
|---------|--------------|-------------|-----------------|
| **LAW-OUTPUT-LIVENESS** | Yes | Yes | **VERIFY** — Confirm test asserts "never blocks; no content → pad" explicitly |
| **INV-STARVATION-FAILSAFE-001** | No | Yes | **ADD TEST** |
| **INV-P10-SINK-GATE** | No | No | **ADD BOTH** |
| **INV-AIR-CONTENT-BEFORE-PAD** | Yes | Yes | **VERIFY** — Test exists in Phase10PipelineFlowControlTests |

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

| Rule ID | Test Exists? | Log Exists? | Action Required |
|---------|--------------|-------------|-----------------|
| **LAW-AUDIO-FORMAT** | No | No | **ADD TEST** |
| **INV-AUDIO-HOUSE-FORMAT-001** | Partial | Yes | **ADD TEST** — Test exists but only checks format acceptance, not rejection |
| **INV-ENCODER-NO-B-FRAMES-001** | No | Yes | **ADD TEST** |
| **INV-AIR-IDR-BEFORE-OUTPUT** | Yes | Yes | **VERIFY** — Confirm gate reset on switch is tested |

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

| Rule ID | Test Exists? | Log Exists? | Action Required |
|---------|--------------|-------------|-----------------|
| **INV-P9-BOOT-LIVENESS** | Yes | No | **ADD LOG** |
| **INV-P9-AUDIO-LIVENESS** | Yes | No | **ADD LOG** |
| **LAW-VIDEO-DECODABILITY** | Yes | Yes | **VERIFY** — Confirm IDR-first is tested at segment boundary |

### Tests to Add — MpegTSOutputSink

None required — tests exist.

### Logs to Add — MpegTSOutputSink

**INV-P9-BOOT-LIVENESS log:**
```
[MpegTSOutputSink] INV-P9-BOOT-LIVENESS: First decodable TS emitted at wall_time=%ld, latency_ms=%d
```

**INV-P9-AUDIO-LIVENESS log:**
```
[MpegTSOutputSink] INV-P9-AUDIO-LIVENESS: Audio stream live, first_audio_pts=%ld, header_write_time=%ld
```

---

## PlayoutEngine / Bootstrap

| Rule ID | Test Exists? | Log Exists? | Action Required |
|---------|--------------|-------------|-----------------|
| **INV-P9-BOOTSTRAP-READY** | Yes | Yes | **VERIFY** — G9_002 test exists in Phase9OutputBootstrapTests |
| **INV-P8-ZERO-FRAME-BOOTSTRAP** | Yes | No | **ADD LOG** |

### Tests to Add — PlayoutEngine

None required — tests exist.

### Logs to Add — PlayoutEngine

**INV-P8-ZERO-FRAME-BOOTSTRAP log:**
```
[PlayoutEngine] INV-P8-ZERO-FRAME-BOOTSTRAP: Zero-frame segment detected, CONTENT-BEFORE-PAD gate bypassed
```

---

## Summary Checklist

### Tests to Add (5)

- [ ] `TEST-INV-STARVATION-FAILSAFE-001` — ProgramOutput starvation → pad within bounded time
- [ ] `TEST-INV-P10-SINK-GATE` — No consumption before sink attached
- [ ] `TEST-LAW-AUDIO-FORMAT` — Non-house audio rejected at encoder
- [ ] `TEST-INV-AUDIO-HOUSE-FORMAT-001-REJECTION` — Explicit rejection path tested
- [ ] `TEST-INV-ENCODER-NO-B-FRAMES-001` — No B-frames in output

### Logs to Add (5)

- [ ] `INV-P10-SINK-GATE` — Log when frame not consumed due to no sink
- [ ] `LAW-AUDIO-FORMAT` — Log when non-house format rejected
- [ ] `INV-P9-BOOT-LIVENESS` — Log first decodable TS emission with latency
- [ ] `INV-P9-AUDIO-LIVENESS` — Log audio stream liveness confirmation
- [ ] `INV-P8-ZERO-FRAME-BOOTSTRAP` — Log zero-frame segment gate bypass

### Tests to Verify (5)

- [ ] `LAW-OUTPUT-LIVENESS` — Confirm "never blocks" assertion exists
- [ ] `INV-AIR-CONTENT-BEFORE-PAD` — Confirm gate logic tested (Phase10PipelineFlowControlTests)
- [ ] `INV-AIR-IDR-BEFORE-OUTPUT` — Confirm gate reset on switch tested
- [ ] `LAW-VIDEO-DECODABILITY` — Confirm IDR-first at segment boundary tested
- [ ] `INV-P9-BOOTSTRAP-READY` — Confirm G9_002 covers commit + ≥1 frame

---

## File Locations for Implementation

| Subsystem | Test File | Source File for Logs |
|-----------|-----------|---------------------|
| ProgramOutput | `pkg/air/tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp` | `pkg/air/src/renderer/ProgramOutput.cpp` |
| EncoderPipeline | `pkg/air/tests/contracts/MpegTSPlayoutSink/MpegTSPlayoutSinkContractTests.cpp` | `pkg/air/src/playout_sinks/mpegts/EncoderPipeline.cpp` |
| MpegTSOutputSink | `pkg/air/tests/contracts/Phase9OutputBootstrapTests.cpp` | `pkg/air/src/output/MpegTSOutputSink.cpp` |
| PlayoutEngine | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` | `pkg/air/src/runtime/PlayoutEngine.cpp` |

---

## Completion Criteria

Phase 1 is complete when:

1. All 5 tests added and passing
2. All 5 logs instrumented and emitting
3. All 5 verification items confirmed
4. Zero Phase 1 rule violations in CI

**Release Gate:** Any Phase 1 violation is a release blocker.

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/ENFORCEMENT_ROADMAP.md` | Source of Phase 1 rule list |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions |
| `docs/contracts/GAP_REMEDIATION_PLAN.md` | Detailed remediation context |
