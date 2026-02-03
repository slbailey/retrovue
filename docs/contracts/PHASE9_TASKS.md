# Phase 9 Atomic Task List

**Status:** COMPLETE — All tasks implemented
**Source:** PHASE9_EXECUTION_PLAN.md; PHASE9_STEADY_STATE_CORRECTNESS.md
**Last Updated:** 2026-02-02

Phase 9 implements **steady-state playout correctness** with output-driven pacing. Task tracking and checklists live here. Phase 9 depends on Phase 8 (COMPLETE) and Output Bootstrap (COMPLETE).

---

## Relationship to Other Phases

| Document | Scope |
|----------|--------|
| **PHASE8_TASKS.md** | Phase 8 (Timeline/Switch). Prerequisite; complete. |
| **PHASE9_TASKS.md** | Phase 9 tasks (P9-CORE-*, P9-TEST-*, P9-OPT-*). Steady-state correctness. |
| **PHASE10 contracts** | Related: `INV-P10-PIPELINE-FLOW-CONTROL.md`. Steady-state flow. |

---

## Phase 9 Task Summary

| Group | Tasks | Invariants |
|-------|-------|------------|
| **Core** | P9-CORE-001 through P9-CORE-008 | INV-P9-STEADY-001 through INV-P9-STEADY-008 |
| **Test** | P9-TEST-001 through P9-TEST-012 | (Contract tests for above invariants) |
| **Optional** | P9-OPT-001 through P9-OPT-003 | (Monitoring, metrics, logging) |

**Total Phase 9 tasks:** 23
**Individual task specs:** `docs/contracts/tasks/phase9/P9-*.md`

---

## Phase 9 Core Checklist (Steady-State Pacing)

- [x] P9-CORE-001: Add steady-state entry detection (`steady_state_entered_`, `pcr_paced_active_`)
- [x] P9-CORE-002: Implement PCR-paced mux loop (wait for `wall_clock >= frame.ct`)
- [x] P9-CORE-003: Disable silence injection on steady-state entry (`silence_injection_disabled_`)
- [x] P9-CORE-004: Remove local CT counters in mux (use only producer-provided CT)
- [x] P9-CORE-005: Implement slot-based decode gating (block at capacity, resume on 1 slot free)
- [x] P9-CORE-006: Implement symmetric A/V backpressure (both blocked together)
- [x] P9-CORE-007: Add pad-while-depth-high violation detection (INV-P9-STEADY-004)
- [x] P9-CORE-008: Add equilibrium monitoring (depth in [1, 2N])

---

## Phase 9 Test Checklist (Contract Tests)

### INV-P9-STEADY-001: Output Owns Pacing Authority
- [x] P9-TEST-001: Mux waits for CT before dequeue
- [x] P9-TEST-002: No burst consumption (max 1 frame per period)

### INV-P9-STEADY-002: Producer Pull-Only After Attach
- [x] P9-TEST-003: Slot-based blocking (blocks at capacity)
- [x] P9-TEST-004: No hysteresis (resumes on 1 slot free)

### INV-P9-STEADY-003: Audio Advances With Video
- [x] P9-TEST-005: Symmetric backpressure (A/V delta ≤ 1 frame)
- [x] P9-TEST-006: Coordinated stall (both blocked together)

### INV-P9-STEADY-004: No Pad While Depth High
- [x] P9-TEST-007: Violation detection (log + counter on pad with depth ≥ 10)

### INV-P9-STEADY-005: Buffer Equilibrium Sustained
- [x] P9-TEST-008: 60-second stability (depth in [1, 2N])

### INV-P9-STEADY-006: Realtime Throughput Maintained
- [x] P9-TEST-009: Frame rate accuracy (60s at 30fps = 1800 ± 1 frames)
- [x] P9-TEST-010: PTS bounded to clock (delta < 100ms)

### INV-P9-STEADY-007: Producer CT Authoritative
- [x] P9-TEST-011: No CT reset on attach (CT preserved from producer)

### INV-P9-STEADY-008: No Silence Injection After Attach
- [x] P9-TEST-012: Silence disabled (mux stalls when audio empty)

---

## Phase 9 Optional Checklist

- [x] P9-OPT-001: Add equilibrium warning log (depth outside [1, 2N] for > 1s)
- [x] P9-OPT-002: Add steady-state metrics (`retrovue_steady_state_active`, etc.)
- [x] P9-OPT-003: Add steady-state entry log (`INV-P9-STEADY-STATE: entered`)

---

## Dependency Order

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

**Recommended execution:**
1. Start P9-CORE-001, P9-CORE-005, P9-CORE-007, P9-CORE-008 in parallel (no dependencies)
2. After P9-CORE-001: start P9-CORE-002 and P9-CORE-003 in parallel
3. After P9-CORE-002: start P9-CORE-004
4. After P9-CORE-005: start P9-CORE-006
5. Run tests after corresponding Core tasks complete

**Critical path:** P9-CORE-001 → P9-CORE-002 → P9-CORE-004 → P9-TEST-011

---

## Task State Tracking

When completing a task:

1. Check the box in the checklist above
2. Add completion date and commit hash in the table below
3. Update PHASE9_EXECUTION_PLAN.md if rollout or exit criteria change

### Completed Tasks

| Task ID | Completed | Notes |
|---------|-----------|--------|
| P9-CORE-001 | 2026-02-03 | Steady-state entry detection in MpegTSOutputSink |
| P9-CORE-002 | 2026-02-03 | PCR-paced mux loop in MuxLoop() |
| P9-CORE-003 | 2026-02-03 | Silence injection disabled on steady-state entry |
| P9-CORE-004 | 2026-02-03 | Producer CT authoritative mode in EncoderPipeline |
| P9-CORE-005 | 2026-02-03 | Slot-based decode gating in FileProducer |
| P9-CORE-006 | 2026-02-03 | Symmetric A/V backpressure in FileProducer |
| P9-CORE-007 | 2026-02-03 | Pad-while-depth-high violation in ProgramOutput |
| P9-CORE-008 | 2026-02-03 | Equilibrium monitoring in ProgramOutput |
| P9-TEST-001 | 2026-02-03 | Phase9OutputBootstrapTests.cpp |
| P9-TEST-002 | 2026-02-03 | Phase9OutputBootstrapTests.cpp |
| P9-TEST-003 | 2026-02-03 | Phase9SymmetricBackpressureTests.cpp |
| P9-TEST-004 | 2026-02-03 | Phase9SymmetricBackpressureTests.cpp |
| P9-TEST-005 | 2026-02-03 | Phase9SymmetricBackpressureTests.cpp |
| P9-TEST-006 | 2026-02-03 | Phase9SymmetricBackpressureTests.cpp |
| P9-TEST-007 | 2026-02-03 | Phase9NoPadWhileDepthHighTests.cpp |
| P9-TEST-008 | 2026-02-03 | Phase9BufferEquilibriumTests.cpp |
| P9-TEST-009 | 2026-02-03 | Phase10PipelineFlowControlTests.cpp |
| P9-TEST-010 | 2026-02-03 | Phase10PipelineFlowControlTests.cpp |
| P9-TEST-011 | 2026-02-03 | Phase9OutputBootstrapTests.cpp |
| P9-TEST-012 | 2026-02-03 | Phase9SteadyStateSilenceTests.cpp |
| P9-OPT-001 | 2026-02-03 | Equilibrium warning log in ProgramOutput |
| P9-OPT-002 | 2026-02-03 | Steady-state metrics in MetricsExporter |
| P9-OPT-003 | 2026-02-03 | Steady-state entry log in MpegTSOutputSink |

---

## Exit Criteria

Phase 9 is complete when:

1. All P9-CORE-* tasks implemented
2. All P9-TEST-* tests pass
3. 60-second continuous playout without pad takeover
4. 60-second continuous playout without runaway backpressure
5. 10-minute continuous real-time output
6. No Phase 8 regressions

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE9_STEADY_STATE_CORRECTNESS.md` | **Architectural contract** (invariants, contracts, tests) |
| `docs/contracts/PHASE9_EXECUTION_PLAN.md` | Phase 9 execution plan (strategy, task breakdown, rollout) |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions |
| `docs/contracts/tasks/phase9/P9-*.md` | Individual task specs |
