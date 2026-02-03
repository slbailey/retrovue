# Phase 8 Execution Plan: Content Deficit Amendment

**Document Type:** Implementation Plan
**Phase:** 8 (Amendment)
**Owner:** Core Team
**Prerequisites:** Phase 8 baseline (timeline semantics, switch coordination)
**Governing Document:** PHASE8.md §5.4
**Incident Reference:** 2026-02-02 Black Screen Incident (Decoder EOF → False Viewer Disconnect)

---

## 1. Executive Summary

### 1.1 Incident Background

Production incident (2026-02-02): A channel experienced a black screen despite an active viewer. Root cause analysis revealed a cascade failure:

```
Decoder EOF (content shorter than planned)
       ↓
No frames produced
       ↓
Buffer empty
       ↓
Pad black emitted
       ↓
Output stall (no TS packets)
       ↓
HTTP timeout
       ↓
False viewer disconnect detected
       ↓
Teardown initiated
       ↓
Black screen persists
```

The semantic root cause: **decoder EOF was conflated with segment end**, and there was no policy for handling content shorter than the planned frame_count.

### 1.2 Amendment Scope

This amendment adds three invariants to Phase 8 (already documented in PHASE8.md §5.4) and specifies implementation tasks to enforce them:

| Invariant | Purpose |
|-----------|---------|
| **INV-P8-SEGMENT-EOF-DISTINCT-001** | Decoder EOF ≠ segment end; schedule is authoritative |
| **INV-P8-CONTENT-DEFICIT-FILL-001** | Gap between EOF and boundary filled with pad |
| **INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001** | frame_count is planning authority; shorter content handled by fill |

### 1.3 Failure Modes Prevented

| Failure Mode | Invariant | How Prevented |
|--------------|-----------|---------------|
| Black screen on content deficit | INV-P8-CONTENT-DEFICIT-FILL-001 | Pad fills gap; output never stalls |
| Timeline corruption on EOF | INV-P8-SEGMENT-EOF-DISTINCT-001 | CT continues advancing; boundary remains authoritative |
| False viewer disconnect | INV-P8-CONTENT-DEFICIT-FILL-001 | TS cadence preserved; HTTP never times out |
| Schedule drift on short content | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | Boundary time unchanged; next segment starts on time |

---

## 2. Authority Model

### 2.1 EOF vs Boundary Authority

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
│   LAW-CLOCK   │    │ LAW-SWITCHING │    │ Decoder EOF   │
│               │    │               │    │               │
│ WHEN boundary │    │ WHEN switch   │    │ Content-level │
│ occurs        │    │ executes      │    │ event         │
│               │    │               │    │               │
│ [AUTHORITY]   │    │ [AUTHORITY]   │    │ [EVENT]       │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └──────────┬──────────┘                     │
                   │                                │
                   ▼                                ▼
          Boundary is scheduled              EOF triggers fill,
          at wall-clock time                 not boundary advance
```

**Key Insight:** Decoder EOF is an **event** within the segment, not a **boundary**. The scheduled segment end time remains authoritative; EOF simply triggers the content deficit fill policy.

### 2.2 Timeline Continuity Rule

> **CT must advance at real-time cadence for the full scheduled duration of a segment, regardless of content availability.**

This sentence explains why everything else exists. The schedule defines segment duration; content availability does not shorten it. If content ends early, the timeline continues; fill preserves output liveness until the boundary.

### 2.3 Content Deficit Fill Policy

When live decoder reaches EOF before the scheduled segment end:

1. **Detect:** FileProducer signals EOF to PlayoutEngine
2. **Continue CT:** TimelineController continues advancing CT at real-time cadence
3. **Fill:** ProgramOutput emits frames using a deterministic fill strategy at configured fps; pad (black + silence) is the guaranteed fallback
4. **Log:** CONTENT_DEFICIT_FILL logged with deficit duration
5. **Switch:** At boundary, SwitchToLive executes normally (fill → next segment)

The fill policy preserves:
- CT monotonicity (INV-P8-002)
- Output liveness (LAW-OUTPUT-LIVENESS, INV-P8-OUTPUT-001)
- TS cadence (no HTTP timeout)
- Boundary timing (LAW-SWITCHING)

---

## 3. State & Data Model Changes

### 3.1 FileProducer (AIR)

| Field | Type | Purpose |
|-------|------|---------|
| `_eof_signaled` | `bool` | True when decoder reaches EOF; prevents re-signaling |
| `_planned_frame_count` | `int64` | frame_count from LoadPreview; planning authority |
| `_frames_delivered` | `int64` | Actual frames delivered to buffer |

### 3.2 PlayoutEngine (AIR)

| Field | Type | Purpose |
|-------|------|---------|
| `_content_deficit_active` | `bool` | True when filling gap between EOF and boundary |
| `_deficit_start_ct` | `int64` | CT when deficit fill began (for logging/metrics) |

### 3.3 Metrics

| Metric | Type | Purpose |
|--------|------|---------|
| `retrovue_air_content_deficit_total` | Counter | How often content deficit fill triggered |
| `retrovue_air_content_deficit_duration_ms` | Histogram | Duration of deficit fill periods |
| `retrovue_air_decoder_eof_total` | Counter | Total decoder EOF events |
| `retrovue_air_decoder_eof_vs_boundary_ms` | Histogram | Time between EOF and boundary (negative = early) |

---

## 4. Task Breakdown (Ordered)

### 4.1 Core Implementation Tasks

| Task ID | Purpose | Component(s) | Invariant(s) | Failure Mode Prevented | Observable Proof |
|---------|---------|--------------|--------------|------------------------|------------------|
| **P8-EOF-001** | Add EOF signaling from FileProducer to PlayoutEngine | AIR: FileProducer, PlayoutEngine | INV-P8-SEGMENT-EOF-DISTINCT-001 | Timeline corruption on EOF | Log: `DECODER_EOF segment={id} ct={ct} frames_delivered={n}` |
| **P8-EOF-002** | Decouple EOF from boundary evaluation in PlayoutEngine | AIR: PlayoutEngine | INV-P8-SEGMENT-EOF-DISTINCT-001 | EOF triggers premature switch | Absence of boundary advance on EOF; boundary still at scheduled time |
| **P8-EOF-003** | Preserve CT advancement after live EOF | AIR: TimelineController | INV-P8-SEGMENT-EOF-DISTINCT-001 | CT stalls on EOF | Log: CT monotonic after EOF; Metric: frame pacing unchanged |
| **P8-FILL-001** | Implement content deficit detection in PlayoutEngine | AIR: PlayoutEngine | INV-P8-CONTENT-DEFICIT-FILL-001 | Black screen without pad | Log: `CONTENT_DEFICIT_FILL_START ct={ct} boundary={boundary_ct}` |
| **P8-FILL-002** | Emit pad frames during content deficit | AIR: ProgramOutput | INV-P8-CONTENT-DEFICIT-FILL-001 | Output stalls; TS gaps | TS packets continue at cadence; HTTP connection maintained |
| **P8-FILL-003** | End content deficit on boundary switch | AIR: PlayoutEngine | INV-P8-CONTENT-DEFICIT-FILL-001 | Pad continues into next segment | Log: `CONTENT_DEFICIT_FILL_END duration_ms={n}`; switch proceeds normally |
| **P8-PLAN-001** | Store frame_count as planning authority in FileProducer | AIR: FileProducer | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | Frame count computed locally | `_planned_frame_count` set from LoadPreview; used for deficit detection |
| **P8-PLAN-002** | Detect early EOF (frames_delivered < planned_frame_count) | AIR: FileProducer | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | Short content not detected | Log: `EARLY_EOF planned={p} delivered={d} deficit={p-d}` |
| **P8-PLAN-003** | Handle long content (frames_delivered ≥ planned_frame_count) | AIR: FileProducer | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | Content plays past boundary | Truncation at boundary; schedule remains authoritative |

### 4.2 Contract Test Tasks

| Task ID | Purpose | File | Invariant(s) | Observable Proof |
|---------|---------|------|--------------|------------------|
| **P8-TEST-EOF-001** | Test: EOF signaled before boundary, CT continues | `test_content_deficit.cpp` | INV-P8-SEGMENT-EOF-DISTINCT-001 | EOF event logged; CT monotonic; no boundary advance |
| **P8-TEST-EOF-002** | Test: EOF does not trigger switch | `test_content_deficit.cpp` | INV-P8-SEGMENT-EOF-DISTINCT-001 | Switch at boundary time, not EOF time |
| **P8-TEST-FILL-001** | Test: Pad emitted during content deficit | `test_content_deficit.cpp` | INV-P8-CONTENT-DEFICIT-FILL-001 | Pad frames in output; TS cadence unchanged |
| **P8-TEST-FILL-002** | Test: TS emission continues during deficit | `test_content_deficit.cpp` | INV-P8-CONTENT-DEFICIT-FILL-001 | TS packet rate stable across deficit |
| **P8-TEST-FILL-003** | Test: Switch terminates deficit fill | `test_content_deficit.cpp` | INV-P8-CONTENT-DEFICIT-FILL-001 | Content from next segment after boundary |
| **P8-TEST-PLAN-001** | Test: Short content triggers early EOF | `test_content_deficit.cpp` | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | EARLY_EOF logged with correct counts |
| **P8-TEST-PLAN-002** | Test: Long content truncated at boundary | `test_content_deficit.cpp` | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | No frames from old segment after boundary |

### 4.3 Integration Test Tasks

| Task ID | Purpose | File | Failure Mode | Observable Proof |
|---------|---------|------|--------------|------------------|
| **P8-INT-001** | Integration: Short content → pad → switch | `test_playout_integration.cpp` | Black screen incident | Full playout chain: content → pad → next segment |
| **P8-INT-002** | Integration: HTTP connection survives content deficit | `test_http_resilience.py` | False viewer disconnect | HTTP 200 maintained; TS bytes flow during deficit |

---

## 5. Dependency Graph

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

### 5.1 Recommended Execution Order

| Step | Task ID(s) | Purpose |
|------|------------|---------|
| 1 | P8-PLAN-001 | Store planning authority |
| 2 | P8-PLAN-002, P8-PLAN-003 | Detect early/long content (parallel) |
| 3 | P8-EOF-001 | Signal EOF from producer |
| 4 | P8-EOF-002 | Decouple EOF from boundary |
| 5 | P8-EOF-003, P8-FILL-001 | CT continuation and deficit detection (parallel) |
| 6 | P8-FILL-002 | Pad emission during deficit |
| 7 | P8-FILL-003 | Deficit end on switch |
| 8 | P8-TEST-* | Contract tests |
| 9 | P8-INT-* | Integration tests |

---

## 6. Logging Requirements

### 6.1 Required Logs

| Log Level | Event | Format | Invariant |
|-----------|-------|--------|-----------|
| INFO | Decoder EOF | `DECODER_EOF segment={id} ct={ct} frames_delivered={n} planned={p}` | INV-P8-SEGMENT-EOF-DISTINCT-001 |
| INFO | Early EOF detected | `EARLY_EOF segment={id} planned={p} delivered={d} deficit_frames={p-d}` | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 |
| INFO | Content deficit fill start | `CONTENT_DEFICIT_FILL_START segment={id} ct={ct} boundary_ct={b} gap_ms={g}` | INV-P8-CONTENT-DEFICIT-FILL-001 |
| INFO | Content deficit fill end | `CONTENT_DEFICIT_FILL_END segment={id} duration_ms={d}` | INV-P8-CONTENT-DEFICIT-FILL-001 |
| WARNING | Long content truncated | `CONTENT_TRUNCATED segment={id} planned={p} available={a} excess_frames={a-p}` | INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 |
| DEBUG | Pad frame emitted during deficit | `DEFICIT_PAD_FRAME ct={ct}` | INV-P8-CONTENT-DEFICIT-FILL-001 |

### 6.2 Absence Evidence

The following should **NOT** appear in logs after this amendment:

| Anti-Pattern | Meaning |
|--------------|---------|
| `BOUNDARY_ADVANCED` immediately after `DECODER_EOF` | EOF conflated with boundary |
| HTTP timeout during segment | Output stalled; deficit not filled |
| `VIEWER_DISCONNECT` during content deficit | False disconnect; fill not preserving TS cadence |

---

## 7. Rollout & Safety Plan

### 7.1 Deployment Strategy

**Phased rollout:**

1. **Phase A:** Deploy with enhanced logging only (no behavior change)
2. **Phase B:** Enable deficit fill on test channels (via config flag)
3. **Phase C:** Enable globally with metrics collection
4. **Phase D:** Remove feature flag; Content Deficit Amendment is default

### 7.2 Regression Detection

**Indicators of regression:**
- `content_deficit_duration_ms` P99 exceeding segment duration (fill never ends)
- `decoder_eof_total` without corresponding `content_deficit_fill_start` (fill not triggered)
- HTTP timeouts during segments with logged EOF events

**Automated checks:**
- Contract tests in CI (P8-TEST-*)
- Integration test: short content file → verify pad → verify switch

---

## 8. Explicit Non-Goals

| Non-Goal | Rationale |
|----------|-----------|
| Viewer presence decoupling | Phase 12 scope; see INV-VIEWER-PRESENCE-DECOUPLED-001 proposal |
| Dynamic content deficit repair | Out of scope; deficit is filled, not repaired |
| Alerting on content length mismatch | Operational tooling; not in Phase 8 scope |
| Changing Phase 8 timeline semantics | Forbidden by constraints; this is additive |
| Inferring or repairing schedule metadata | Phase 8 preserves timeline integrity in the presence of imperfect content; validation is a planning concern |

---

## 9. Summary

| Metric | Value |
|--------|-------|
| Core implementation tasks | 9 |
| Contract tests | 7 |
| Integration tests | 2 |
| Invariants enforced | 3 |
| New state fields | 5 |
| New metrics | 4 |

**Critical path:** P8-PLAN-001 ✅ → P8-PLAN-002 ✅ → P8-PLAN-003 ✅ → P8-EOF-001 ✅ → P8-EOF-002 ✅ → P8-EOF-003 ✅ → P8-FILL-001 ✅ → P8-FILL-002 ✅ → P8-FILL-003 ✅ → tests

**Exit criteria:** All contract tests pass; no black screen on content deficit; TS cadence preserved during deficit; no false viewer disconnects; decoder EOF logged distinctly from boundary.

---

## 10. Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE8.md` | Governing architectural contract (§5.4 Content Deficit Semantics) |
| `docs/contracts/PHASE8_TASKS.md` | Task checklist (P8-PLAN-001 complete 2026-02-02) |
| `docs/contracts/tasks/phase8/P8-*.md` | Individual task specs |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions |
| `docs/contracts/PHASE12.md` | Related: viewer presence decoupling (future) |
