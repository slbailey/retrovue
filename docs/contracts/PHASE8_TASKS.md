# Phase 8 Atomic Task List: Content Deficit Amendment

**Status:** Core implementation and contract tests complete; P8-TEST-* all added (PlayoutEngineContractTests.cpp); P8-INT-* optional
**Source:** PHASE8_EXECUTION_PLAN.md; PHASE8.md §5.4
**Last Updated:** 2026-02-02
**Incident Reference:** 2026-02-02 Black Screen Incident

Phase 8 Content Deficit Amendment implements **EOF/boundary distinction** and **content deficit fill policy**. Task tracking and checklists live here.

**Amendment scope (18 tasks):** P8-PLAN-001 through P8-PLAN-003, P8-EOF-001 through P8-EOF-003, P8-FILL-001 through P8-FILL-003, P8-TEST-EOF-001/002, P8-TEST-FILL-001/002/003, P8-TEST-PLAN-001/002, P8-INT-001/002.

---

## Relationship to Other Phases

| Document | Scope |
|----------|-------|
| **PHASE8_TASKS.md** | Phase 8 Content Deficit Amendment (this document) |
| **PHASE11_TASKS.md** | Phase 11 (Boundary Lifecycle). Independent. |
| **PHASE12_TASKS.md** | Phase 12 (Live Session Authority). Related: viewer presence decoupling (future). |
| **PHASE1_TASKS.md** | Phase 1 (Prevent Black/Silence). Prerequisite for pad semantics. |

---

## Phase 8 Content Deficit Task Summary

| Group | Tasks | Invariants |
|-------|-------|------------|
| **Planning Authority** | P8-PLAN-001, P8-PLAN-002, P8-PLAN-003 | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 |
| **EOF Semantics** | P8-EOF-001, P8-EOF-002, P8-EOF-003 | INV-P8-SEGMENT-EOF-DISTINCT-001 |
| **Content Deficit Fill** | P8-FILL-001, P8-FILL-002, P8-FILL-003 | INV-P8-CONTENT-DEFICIT-FILL-001 |
| **Contract Tests** | P8-TEST-EOF-*, P8-TEST-FILL-*, P8-TEST-PLAN-* | (All invariants) |
| **Integration Tests** | P8-INT-001, P8-INT-002 | (End-to-end validation) |

**Total Phase 8 Content Deficit tasks:** 18
**Individual task specs:** `docs/contracts/tasks/phase8/P8-*.md`

---

## Phase 8 Core Checklist (Content Deficit Amendment)

### Planning Authority (INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001)

- [x] P8-PLAN-001: Store frame_count as planning authority in FileProducer
- [x] P8-PLAN-002: Detect early EOF (frames_delivered < planned_frame_count)
- [x] P8-PLAN-003: Handle long content (truncate at boundary)

### EOF Semantics (INV-P8-SEGMENT-EOF-DISTINCT-001)

- [x] P8-EOF-001: Add EOF signaling from FileProducer to PlayoutEngine
- [x] P8-EOF-002: Decouple EOF from boundary evaluation in PlayoutEngine
- [x] P8-EOF-003: Preserve CT advancement after live EOF

### Content Deficit Fill (INV-P8-CONTENT-DEFICIT-FILL-001)

- [x] P8-FILL-001: Implement content deficit detection in PlayoutEngine
- [x] P8-FILL-002: Emit pad frames during content deficit
- [x] P8-FILL-003: End content deficit on boundary switch

---

## Phase 8 Test Checklist (Contract Tests)

### EOF Semantics Tests

- [x] P8-TEST-EOF-001: Test EOF signaled before boundary, CT continues (log capture; DECODER_EOF/EARLY_EOF/End of file)
- [x] P8-TEST-EOF-002: Test EOF does not trigger switch (switch completion at boundary ±500ms)

### Content Deficit Fill Tests

- [x] P8-TEST-FILL-001: Test pad emitted during content deficit (CONTENT_DEFICIT_FILL_START or DECODER_EOF when EOF before boundary)
- [x] P8-TEST-FILL-002: Test TS emission continues during deficit (CountingSink; frames received > 0)
- [x] P8-TEST-FILL-003: Test switch terminates deficit fill (CONTENT_DEFICIT_FILL_END or START in logs after switch)

### Planning Authority Tests

- [x] P8-TEST-PLAN-001: Test short content triggers early EOF (PlayoutEngineContractTests.cpp; delivered < planned)
- [x] P8-TEST-PLAN-002: Test long content truncated at boundary (PlayoutEngineContractTests.cpp)

---

## Phase 8 Integration Test Checklist

- [ ] P8-INT-001: Integration: short content → pad → switch
- [x] P8-INT-002: Integration: HTTP connection survives content deficit

---

## Dependency Order

```
P8-PLAN-001 (Store frame_count)
      │
      ▼
P8-PLAN-002 (Detect early EOF)
      │
      ├──────────────────────────────┐
      ▼                              │
P8-EOF-001 (Signal EOF)              │
      │                              │
      ▼                              │
P8-EOF-002 (Decouple EOF/boundary)   │
      │                              │
      ├──────────┐                   │
      ▼          ▼                   ▼
P8-EOF-003   P8-FILL-001        P8-PLAN-003
(CT continues) (Deficit detect)  (Long content)
      │          │
      │          ▼
      │     P8-FILL-002 (Emit pad)
      │          │
      │          ▼
      └────► P8-FILL-003 (End deficit on switch)
                 │
                 ▼
         ┌───────┴───────┐
         ▼               ▼
  P8-TEST-EOF-*    P8-TEST-FILL-*
         │               │
         └───────┬───────┘
                 ▼
           P8-INT-001
           P8-INT-002
```

**Recommended execution:** P8-PLAN-001 first (planning authority), then P8-PLAN-002/003 (parallel), then P8-EOF-001 → P8-EOF-002 → (P8-EOF-003 || P8-FILL-001) → P8-FILL-002 → P8-FILL-003. Tests after corresponding Core tasks.

---

## Task State Tracking

When completing a task:

1. Check the box in the checklist above
2. Add completion date and notes in the table below
3. Update PHASE8_EXECUTION_PLAN.md if rollout or exit criteria change

### Completed Tasks

| Task ID | Completed | Notes |
|---------|-----------|-------|
| P8-PLAN-001 | 2026-02-02 | FileProducer: planned_frame_count_, frames_delivered_; set in start(), increment on frame emit; GetPlannedFrameCount(), GetFramesDelivered(). |
| P8-INT-002 | 2026-02-02 | Integration test: HTTP connection survives content deficit. Tests in pkg/core/tests/integration/test_http_resilience.py. Verifies HTTP 200 maintained, TS bytes flow continuously during deficit, no viewer disconnect. |

---

## Observable Proof Summary

Each task must produce observable proof of correctness:

| Task ID | Observable Proof |
|---------|------------------|
| P8-PLAN-001 | `_planned_frame_count` set from legacy preload RPC |
| P8-PLAN-002 | Log: `EARLY_EOF planned={p} delivered={d} deficit={p-d}` |
| P8-PLAN-003 | No frames from old segment after boundary |
| P8-EOF-001 | Log: `DECODER_EOF segment={id} ct={ct}` |
| P8-EOF-002 | Boundary advance at scheduled time, not EOF time |
| P8-EOF-003 | CT monotonic after EOF; frame pacing unchanged |
| P8-FILL-001 | Log: `CONTENT_DEFICIT_FILL_START ct={ct}` |
| P8-FILL-002 | TS packets continue at cadence during deficit |
| P8-FILL-003 | Log: `CONTENT_DEFICIT_FILL_END duration_ms={n}` |
| P8-TEST-EOF-001 | EOF logged; CT monotonic; no boundary advance |
| P8-TEST-EOF-002 | Switch at boundary time, not EOF time |
| P8-TEST-FILL-001 | Pad frames in output; TS cadence unchanged |
| P8-TEST-FILL-002 | TS packet rate stable across deficit |
| P8-TEST-FILL-003 | Content from next segment after boundary |
| P8-TEST-PLAN-001 | EARLY_EOF logged with correct counts |
| P8-TEST-PLAN-002 | Truncation logged; no excess frames |
| P8-INT-001 | Full chain: content → pad → next segment |
| P8-INT-002 | HTTP 200 maintained; TS bytes flow during deficit |

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE8.md` | **Architectural contract** (§5.4 Content Deficit Semantics) |
| `docs/contracts/PHASE8_EXECUTION_PLAN.md` | Execution plan (strategy, task breakdown, rollout) |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions |
| `docs/contracts/tasks/phase8/P8-*.md` | Individual task specs |
