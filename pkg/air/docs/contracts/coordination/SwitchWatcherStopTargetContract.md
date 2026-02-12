# Switch Watcher Stop-Target Contract

**ID:** INV-P8-SWITCHWATCHER-STOP-TARGET-001
**Status:** Canonical
**Owner:** PlayoutEngine (SwitchWatcher)
**Applies to:** Producer lifecycle during switch/preview transitions

**Related:** [LegacyPreviewSwitchModel (Retired model)](LegacyPreviewSwitchModel.md) · [PlayoutInvariants-BroadcastGradeGuarantees](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)

---

## 1. Invariant Definitions (Normative)

### INV-P8-SWITCHWATCHER-STOP-TARGET-001: Successor Protection (Primary)

**Statement:** Switch machinery MUST NOT stop, disable, or write-barrier the successor (new live) producer as a result of switch-completion or commit bookkeeping.

**Observable outcome:** After a successful switch, the successor producer continues emitting frames normally until an explicit stop or a subsequent switch.

### INV-P8-SWITCHWATCHER-COMMITGEN-EDGE-SAFETY-002: Post-Swap Commit-Gen Safety

**Statement:** Commit-generation transitions that occur after the producer swap MUST NOT trigger retirement actions against the successor producer.

**Rationale:** Post-swap commit-gen changes may represent successor activation or same-segment bookkeeping rather than a new segment requiring producer retirement.

### INV-P8-COMMITGEN-RETIREMENT-SEMANTICS-003: Retirement Decision Scope

**Statement:** Producer retirement decisions MUST be driven only by commit-generation transitions that indicate a producer should be retired, and MUST ignore commit-generation transitions that represent successor activation or same-segment lifecycle bookkeeping.

---

## 2. Allowed and Forbidden Behaviors (Normative)

### Forbidden

| Behavior | Why forbidden |
|----------|---------------|
| Retiring the currently-live producer due to switch-completion bookkeeping | Kills successor |
| Treating successor activation as a new segment requiring retirement | Same-segment lifecycle |
| Allowing post-swap commit edges to affect successor liveness | Causes continuity failure |

### Required

| Behavior | Why required |
|----------|--------------|
| Retirement actions apply only to the pre-swap producer | Preserves continuity |
| Successor liveness is independent of commit bookkeeping | Prevents pad storms |
| Successor emits continuously post-swap | Broadcast-grade continuity |

---

## 3. Observable Violation Signature

**Log pattern (violation):**
```
[TimelineController] ORCH-SWITCH-SUCCESSOR-OBSERVED: Segment N commit_gen=X (successor video emitted)
[FileProducer] Request stop (writes disabled)   ← within <100ms of above
```
Followed by successor emitting only a handful of frames instead of running continuously.

**Telemetry (violation):**
- Successor produces far fewer frames than expected before stopping
- Successor terminated with write-barrier reason
- Switch completes but output immediately starves

**Expected (correct):**
- Successor emits continuously until next switch or explicit stop
- Successor runs for at least 500ms (or until content EOF / next lifecycle event)
- No retirement action targets successor during switch completion

---

## 4. Contract Test Requirements

Tests MUST verify the invariant outcomes:

1. **Successor never retired by switch completion bookkeeping** — Successor must not receive stop/disable from switch machinery
2. **Retiring producer is the pre-swap live producer** — Retirement actions target the producer that was live before swap
3. **Successor continues producing across "successor activation" event** — Successor emits continuously for at least `min(500ms, fps × 0.5s)` or until next explicit lifecycle event
4. **No continuity failure signature** — No buffer-truly-empty / pad storm under the reproduced sequence

Tests should NOT hardcode implementation details (function names, counter values).

---

## 5. Implementation Notes (Non-Normative)

The invariants can be satisfied by several strategies:

**Strategy A: Bind retirement target before swap**
- Capture a reference to the retiring producer before the swap
- All retirement actions use the captured reference
- After swap, disable retirement-detection logic

**Strategy B: Advance edge-detection baseline after swap**
- After swap completes, update the baseline to include any successor-activation increments
- Prevents successor-activation from appearing as a retirement trigger

**Strategy C: Tag bookkeeping events by source**
- Distinguish segment-lock events from successor-activation events
- Only segment-lock events trigger retirement

---

## 6. Background (Non-Normative)

### Problem Statement

During producer switch, internal bookkeeping that confirms "successor is now active" was triggering retirement logic. Because the retirement target was resolved dynamically after the swap had already occurred, the retirement action targeted the successor instead of the retiring producer.

**Observed failure:**
- Successor produced only ~5 frames before being stopped
- Switch appeared to complete successfully, but output immediately starved
- Retirement action applied to wrong producer

### Root Cause

The switch watcher's retirement-detection logic used a dynamically-resolved reference that changed meaning after the swap. The successor-activation signal incremented the same counter used for retirement detection, causing the watcher to misinterpret it as "time to retire" and target the successor.

**Timeline of failure:**
1. Switch initiated, retirement target resolved as "live producer" (old)
2. Readiness achieved, swap executed: "live producer" now points to successor
3. Successor-activation bookkeeping increments counter
4. Watcher sees counter change, resolves retirement target as "live producer" (now successor)
5. Retirement action stops successor — catastrophic

### Confirmation: Where Commit-Gen Increments

The successor-activation signal (`RecordSuccessorEmissionDiagnostic` in `TimelineController.cpp`) increments `segment_commit_generation_`. This increment represents same-segment bookkeeping ("segment fully active"), not a new segment event. The switch watcher's edge detector treated this as a retirement trigger.

---

## 7. Owner Subsystem

**Owner:** PlayoutEngine (`pkg/air/src/runtime/PlayoutEngine.cpp`)

**Responsibilities:**
- Ensure retirement actions target the retiring producer
- Ensure successor-activation bookkeeping doesn't trigger retirement
- Ensure successor runs continuously after swap

**Non-owner subsystems:**
- TimelineController: May increment commit-gen on successor emission; switch logic must remain correct regardless
- FileProducer: Receives retirement actions; does not control targeting

---

## 8. Summary

Switch machinery must not stop, disable, or write-barrier the successor producer as a result of switch-completion or commit bookkeeping. Retirement actions must target the pre-swap producer. Successor liveness must be independent of commit bookkeeping.
