# Runway Readiness Contract — v0.1

**Status:** Contract
**Version:** 0.1

**Classification:** Contract (Output-Runway Execution Readiness)
**Authority Level:** Core (Runtime)
**Governs:** Material readiness invariants for uninterrupted playout execution
**Out of Scope:** AIR frame-level buffering, Horizon planning depth, Traffic Manager logic, CI enforcement

---

## 1. Scope

This contract defines the conditions under which a channel's playout output possesses sufficient prepared material ahead of the current playhead to sustain uninterrupted execution.

It applies to all channels during active playout (at least one viewer connected and AIR emitting bytes). It does not apply to channels with no active playout session.

Runway readiness is evaluated continuously during execution. It is independent of how far ahead the Horizon has planned — horizon depth is a planning concern; runway is an execution-readiness concern.

---

## 2. Definitions

### READY segment

A segment whose underlying material (asset data, offsets, metadata) has been fully resolved and is available for immediate execution by AIR without further preparation by Core.

### QUEUED block

A block in the TransmissionLog whose constituent segments have all been resolved but which has not yet begun execution. A QUEUED block contains only READY segments.

### PRIMED material

The set of all READY segments and QUEUED blocks ahead of the current playhead that are available for execution. PRIMED material is the supply from which runway is measured.

### RUNWAY

The cumulative wall-clock duration (in milliseconds and equivalent frames at the channel's frame rate) of PRIMED non-recovery material ahead of the current playhead. Runway is a scalar measurement, not a data structure.

### PRELOAD_BUDGET

A per-channel configuration value (in milliseconds) defining the minimum acceptable runway during steady-state execution. PRELOAD_BUDGET is set per channel and may vary across channels. It represents the operator's tolerance for how thin the runway may become before execution is considered at risk.

### RECOVERY segment

A segment injected at runtime to maintain continuous output when planned material is not READY. Recovery segments are not part of the original TransmissionLog plan. They are classifiable under AsRun reconciliation (see AsRunReconciliationContract, `RUNTIME_RECOVERY`).

### Planned PAD

A segment explicitly scheduled in the TransmissionLog as traffic fill (e.g., interstitial, filler, station ID). Planned PAD is part of the editorial plan, not a runtime recovery action.

---

## 3. Invariants

### INV-RUNWAY-001 — Runway Sufficiency

At all times during steady-state execution, the cumulative duration of READY non-recovery segments ahead of the current playhead must be greater than or equal to `PRELOAD_BUDGET`.

```
runway_ms >= preload_budget_ms
```

A runway that falls below `PRELOAD_BUDGET` indicates that execution readiness has degraded and recovery may be required.

---

### INV-RUNWAY-002 — No Fence Without Ready Successor

At any fence boundary between planned segments, the successor segment must already be READY before the predecessor completes execution.

**Exception:** If the successor is explicitly classified as runtime recovery, it is exempt from this requirement (recovery segments are reactive by nature).

A fence boundary where the successor is not READY and is not runtime recovery constitutes a readiness violation.

---

### INV-RUNWAY-003 — Planned PAD Does Not Satisfy Readiness

Planned PAD contributes to measured runway duration (it is PRIMED material if READY). However, the presence of planned PAD does not relax the requirement that the next non-PAD segment beyond it be READY before the PAD begins execution.

Specifically: if the sequence ahead of the playhead is `[PAD_A, SEGMENT_B]`, then `SEGMENT_B` must be READY before `PAD_A` begins execution.

---

### INV-RUNWAY-004 — Runtime Recovery Classification

If runway drops below `PRELOAD_BUDGET` and a recovery segment is executed to maintain continuous output, this event must be classifiable as runtime recovery under AsRun reconciliation.

Recovery segments are not planned material. Their presence in the as-run record indicates an operational degradation, not a planning fault, unless the cause is traceable to a planning defect (see Section 5).

---

### INV-RUNWAY-005 — Horizon Independence

Runway enforcement is independent of Horizon planning depth.

A Horizon may plan days ahead; runway measures only the READY material immediately ahead of the playhead. A deep Horizon does not guarantee sufficient runway. A shallow Horizon does not inherently violate runway requirements if the material within it is READY and meets `PRELOAD_BUDGET`.

---

## 4. Non-Goals

This contract does **not**:

- Define CI enforcement or automated testing gates for runway readiness.
- Govern Traffic Manager logic, filler selection, or interstitial scheduling.
- Require changes to HorizonManager or Horizon planning depth.
- Prescribe how PRELOAD_BUDGET values are chosen or tuned.
- Define the mechanism by which segments become READY (that is a Core pipeline concern).
- Govern AIR-internal buffering or frame-level pacing (AIR owns its own buffer contracts).
- Define the procedure for recovery segment injection (only the classification outcome).

---

## 5. Failure Classification

When runway invariants are violated, the failure must be classifiable into one of two categories:

### Operational Degradation

Runway fell below `PRELOAD_BUDGET` due to transient conditions (e.g., slow asset resolution, I/O delay, resource contention). The planning pipeline produced a valid plan; execution readiness could not keep pace.

**Characteristics:**
- TransmissionLog is well-formed and locked.
- Planned segments exist but were not READY in time.
- Recovery segments may have been injected.
- Classifiable as `RUNTIME_RECOVERY` under AsRun reconciliation.

### Planning Fault

Runway fell below `PRELOAD_BUDGET` because the planning pipeline failed to produce sufficient material. The plan itself is deficient — there is nothing to make READY.

**Characteristics:**
- TransmissionLog has gaps, or insufficient entries to cover the required runway.
- No amount of faster asset resolution would have prevented the shortfall.
- Classifiable as a planning defect; may co-occur with `MISSING_BLOCK` under AsRun reconciliation.

The distinction matters: operational degradation is a runtime concern; planning faults are pipeline defects that must be addressed upstream.

---

## 6. Enforcement

- Runway readiness is evaluated during active playout by Core runtime components.
- Violations of INV-RUNWAY-001 through INV-RUNWAY-003 are observable conditions, not necessarily fatal errors — they trigger recovery, not crashes.
- INV-RUNWAY-004 ensures that recovery actions are recorded and classifiable.
- INV-RUNWAY-005 ensures that runway and Horizon remain decoupled concerns.
- Core owns runway readiness. AIR owns frame-level buffering. These are separate enforcement domains.
