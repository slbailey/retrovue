# Phase 9 Execution Plan: Steady-State Playout Correctness

**Document Type:** Implementation Plan
**Phase:** 9
**Owner:** AIR Team
**Prerequisites:** Phase 8 (COMPLETE), Output Bootstrap (COMPLETE)
**Governing Document:** PHASE9_STEADY_STATE_CORRECTNESS.md

---

## 1. Execution Strategy

### 1.1 High-Level Approach

Phase 9 enforcement establishes **output-driven pacing** as the authoritative flow control mechanism after output attach. The implementation follows three principles:

1. **Output owns pacing:** After attach, the mux loop pulls frames at PCR-paced rate. Producers yield to downstream capacity.

2. **Slot-based gating:** Producers block at capacity, resume when one slot frees. No hysteresis. No low-water drain.

3. **Symmetric A/V:** Audio and video advance together. Neither stream runs ahead during backpressure.

### 1.2 Where Pacing Authority Is Checked

| Entry Point | Check Required | Action |
|-------------|----------------|--------|
| MpegTSOutputSink mux loop | Wall clock vs frame CT | Wait until `clock >= ct` before dequeue |
| FileProducer decode gate | Buffer capacity | Block at capacity, resume on 1 slot free |
| ProgramOutput render loop | Sink attachment | Gate frame consumption until sink attached |
| FileProducer A/V loop | Symmetric backpressure | Block both streams when either blocked |

### 1.3 Steady-State Flow Coordination

```
Output Attach Complete
       │
       ▼
┌──────────────────┐
│ Check steady-    │
│ state entry      │
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
  Entry     Skip
  Conditions  │
  Met         │
    │         ▼
    ▼      Continue
 Disable   Bootstrap
 Silence     │
    │        │
    ▼        │
 Enable    ◄─┘
 PCR-Paced
 Mux Loop
    │
    ▼
┌─────────────────────┐
│ Steady-State Loop:  │
│ • Peek frame CT     │
│ • Wait for clock    │
│ • Dequeue + encode  │
│ • Audio ≤ video CT  │
└─────────────────────┘
```

---

## 2. State & Data Model Changes

### 2.1 MpegTSOutputSink Additions

| Field | Type | Purpose | Invariant |
|-------|------|---------|-----------|
| `steady_state_entered_` | `bool` | Steady-state pacing active | INV-P9-STEADY-001 |
| `silence_injection_disabled_` | `bool` | No fabricated audio | INV-P9-STEADY-008 |
| `pcr_paced_active_` | `bool` | Mux is time-driven | INV-P9-STEADY-001 |

### 2.2 FileProducer Additions

| Field | Type | Purpose | Invariant |
|-------|------|---------|-----------|
| `slot_gating_active_` | `bool` | Slot-based decode gating | INV-P9-STEADY-002 |
| `av_symmetric_block_` | `std::atomic<bool>` | A/V blocked together | INV-P9-STEADY-003 |

### 2.3 ProgramOutput Additions

| Field | Type | Purpose | Invariant |
|-------|------|---------|-----------|
| `pad_while_depth_high_` | `int64_t` | Violation counter | INV-P9-STEADY-004 |
| `last_equilibrium_check_` | `time_point` | Monitoring timestamp | INV-P9-STEADY-005 |

### 2.4 Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `kSteadyStateMinDepth` | `1` | Lower equilibrium bound |
| `kSteadyStateMaxDepth` | `2 * kTargetDepth` | Upper equilibrium bound |
| `kPadViolationDepthThreshold` | `10` | INV-P9-STEADY-004 trigger |
| `kEquilibriumSampleInterval` | `1000ms` | Monitoring period |

### 2.5 No Schema Changes Required

Phase 9 is purely runtime state. No database migrations or persistent storage changes.

---

## 3. Task Breakdown (Ordered)

| Task ID | Purpose | Files | Invariants | Blocked By |
|---------|---------|-------|------------|------------|
| **Core Implementation** |||||
| P9-CORE-001 | Add steady-state entry detection | `MpegTSOutputSink.cpp` | INV-P9-STEADY-001 | — |
| P9-CORE-002 | Implement PCR-paced mux loop | `MpegTSOutputSink.cpp` | INV-P9-STEADY-001 | P9-CORE-001 |
| P9-CORE-003 | Disable silence injection on entry | `MpegTSOutputSink.cpp` | INV-P9-STEADY-008 | P9-CORE-001 |
| P9-CORE-004 | Remove local CT counters in mux | `MpegTSOutputSink.cpp` | INV-P9-STEADY-007 | P9-CORE-002 |
| P9-CORE-005 | Implement slot-based decode gating | `FileProducer.cpp` | INV-P9-STEADY-002 | — |
| P9-CORE-006 | Implement symmetric A/V backpressure | `FileProducer.cpp` | INV-P9-STEADY-003 | P9-CORE-005 |
| P9-CORE-007 | Add pad-while-depth-high violation | `ProgramOutput.cpp` | INV-P9-STEADY-004 | — |
| P9-CORE-008 | Add equilibrium monitoring | `FrameRingBuffer.cpp`, `ProgramOutput.cpp` | INV-P9-STEADY-005 | — |
| **Test Implementation** |||||
| P9-TEST-001 | Test: mux waits for CT | `SteadyStateContractTests.cpp` | INV-P9-STEADY-001 | P9-CORE-002 |
| P9-TEST-002 | Test: no burst consumption | `SteadyStateContractTests.cpp` | INV-P9-STEADY-001 | P9-CORE-002 |
| P9-TEST-003 | Test: slot-based blocking | `SteadyStateContractTests.cpp` | INV-P9-STEADY-002 | P9-CORE-005 |
| P9-TEST-004 | Test: no hysteresis | `SteadyStateContractTests.cpp` | INV-P9-STEADY-002 | P9-CORE-005 |
| P9-TEST-005 | Test: symmetric backpressure | `SteadyStateContractTests.cpp` | INV-P9-STEADY-003 | P9-CORE-006 |
| P9-TEST-006 | Test: coordinated stall | `SteadyStateContractTests.cpp` | INV-P9-STEADY-003 | P9-CORE-006 |
| P9-TEST-007 | Test: pad violation detection | `SteadyStateContractTests.cpp` | INV-P9-STEADY-004 | P9-CORE-007 |
| P9-TEST-008 | Test: buffer equilibrium 60s | `SteadyStateContractTests.cpp` | INV-P9-STEADY-005 | P9-CORE-008 |
| P9-TEST-009 | Test: frame rate accuracy | `SteadyStateContractTests.cpp` | INV-P9-STEADY-006 | P9-CORE-002 |
| P9-TEST-010 | Test: PTS bounded to clock | `SteadyStateContractTests.cpp` | INV-P9-STEADY-006 | P9-CORE-002 |
| P9-TEST-011 | Test: no CT reset on attach | `SteadyStateContractTests.cpp` | INV-P9-STEADY-007 | P9-CORE-004 |
| P9-TEST-012 | Test: silence disabled | `SteadyStateContractTests.cpp` | INV-P9-STEADY-008 | P9-CORE-003 |
| **Optional Tasks** |||||
| P9-OPT-001 | Add equilibrium warning log | `FrameRingBuffer.cpp` | INV-P9-STEADY-005 | P9-CORE-008 |
| P9-OPT-002 | Add steady-state metrics | `MetricsExporter.cpp` | — | P9-CORE-001 |
| P9-OPT-003 | Add steady-state entry log | `PlayoutEngine.cpp` | — | P9-CORE-001 |

### 3.1 Dependency Graph

```
┌───────────────────────────────────────────────────────────────────┐
│                      MpegTSOutputSink Branch                      │
└───────────────────────────────────────────────────────────────────┘

P9-CORE-001 (Steady-state entry detection)
      │
      ├──────────────────────────────┐
      ▼                              ▼
P9-CORE-002 (PCR-paced mux)    P9-CORE-003 (Disable silence)
      │                              │
      ├──────────┐                   ▼
      ▼          ▼             P9-TEST-012
P9-CORE-004   P9-TEST-001
(No local CT) P9-TEST-002
      │       P9-TEST-009
      ▼       P9-TEST-010
P9-TEST-011

┌───────────────────────────────────────────────────────────────────┐
│                       FileProducer Branch                         │
└───────────────────────────────────────────────────────────────────┘

P9-CORE-005 (Slot-based decode gating)
      │
      ├──────────────────────────────┐
      ▼                              ▼
P9-CORE-006 (Symmetric A/V)    P9-TEST-003
      │                        P9-TEST-004
      ▼
P9-TEST-005
P9-TEST-006

┌───────────────────────────────────────────────────────────────────┐
│                       ProgramOutput Branch                        │
└───────────────────────────────────────────────────────────────────┘

P9-CORE-007 (Pad violation) ──► P9-TEST-007

P9-CORE-008 (Equilibrium) ──► P9-TEST-008 ──► P9-OPT-001
```

### 3.2 Critical Path

**Minimum path to functional steady-state:**

```
P9-CORE-001 → P9-CORE-002 → P9-CORE-003 → P9-CORE-004
     │
     └──► P9-CORE-005 → P9-CORE-006
```

**Parallelism opportunities:**
- P9-CORE-005 can start immediately (no dependencies)
- P9-CORE-007 can start immediately (no dependencies)
- P9-CORE-008 can start immediately (no dependencies)
- After P9-CORE-001: P9-CORE-002 and P9-CORE-003 can run in parallel
- After P9-CORE-005: P9-CORE-006 and P9-TEST-003/004 can run in parallel

---

## 4. Rollout & Safety Plan

### 4.1 Deployment Strategy

**Phased rollout:**

1. **Phase A:** Implement P9-CORE-001 through P9-CORE-008 with feature flag
2. **Phase B:** Enable on test channels with enhanced logging
3. **Phase C:** 10-minute stability test on test channels
4. **Phase D:** Enable globally; Phase 9 is default behavior

### 4.2 Required Logging

| Log Level | Event | Content |
|-----------|-------|---------|
| INFO | Steady-state entered | Channel ID, buffer depth, timestamp |
| INFO | Silence injection disabled | Channel ID, timestamp |
| INFO | PCR-paced mux active | Channel ID, timestamp |
| WARNING | Pad while depth high | Channel ID, depth, violation count |
| WARNING | Buffer outside equilibrium | Channel ID, depth, range, duration |
| DEBUG | Mux wait for CT | Frame CT, wall clock, delta |

### 4.3 Metrics

| Metric | Type | Purpose |
|--------|------|---------|
| `retrovue_steady_state_active` | Gauge | Whether steady-state is active |
| `retrovue_steady_state_duration_seconds` | Counter | Time in steady-state |
| `retrovue_mux_ct_wait_ms` | Histogram | Time mux waits for CT |
| `retrovue_pad_while_depth_high_total` | Counter | INV-P9-STEADY-004 violations |
| `retrovue_equilibrium_violations_total` | Counter | Depth outside [1, 2N] |
| `retrovue_decode_gate_blocks_total` | Counter | Producer blocked at capacity |

### 4.4 Regression Detection

**Indicators of regression:**
- `pad_while_depth_high_total` increasing (frames exist but not consumed)
- `equilibrium_violations_total` increasing (buffer drift)
- Audio underruns in VLC after attach
- Frame rate deviation > 1%

**Automated checks:**
- Contract tests in CI (P9-TEST-001 through P9-TEST-012)
- Integration test: 60-second playout, verify frame count = fps × 60 ± 1
- Integration test: 10-minute playout, verify no equilibrium violations

---

## 5. Explicit Non-Goals

Phase 9 execution plan **does not** address:

| Non-Goal | Rationale |
|----------|-----------|
| Phase 8 timing changes | Frozen per constraints |
| Output bootstrap changes | Frozen per Output Bootstrap contract |
| PCR ownership at startup | Frozen per Output Bootstrap contract |
| Adaptive bitrate | Deferred to Phase 13 |
| Quality degradation | Deferred to Phase 13 |
| Network congestion handling | Sink responsibility |
| Multi-channel resource balancing | Core responsibility |
| Buffer auto-tuning | Deferred to Phase 13 |

---

## 6. Summary

| Metric | Value |
|--------|-------|
| Core implementation tasks | 8 |
| Contract tests | 12 |
| Optional tasks | 3 |
| New runtime state fields | 7 |
| Invariants enforced | 8 |

**Critical path:** P9-CORE-001 → P9-CORE-002 → P9-CORE-004 (enables PCR-paced mux with producer CT)

**Parallel path:** P9-CORE-005 → P9-CORE-006 (enables slot-based symmetric backpressure)

**Exit criteria:** All contract tests pass; 60-second playout without pad takeover; 60-second playout without equilibrium violation; 10-minute playout stable; no Phase 8 regressions.

---

## 7. Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE9_STEADY_STATE_CORRECTNESS.md` | Governing architectural contract (invariants, contracts) |
| `docs/contracts/PHASE9_TASKS.md` | Phase 9 atomic task list and checklists |
| `docs/contracts/tasks/phase9/P9-*.md` | Individual task specs |
| `pkg/air/docs/contracts/coordination/Phase9-OutputBootstrap.md` | Related: output bootstrap (frozen) |
| `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md` | Related: steady-state flow control |
