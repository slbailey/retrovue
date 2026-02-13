# As-Run Reconciliation Contract — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Planning → Execution Fidelity)  
**Authority Level:** Core (Runtime)  
**Governs:** Reconciliation between TransmissionLog (plan) and AsRunLog (actual)  
**Out of Scope:** Horizon logic, seam validation (TransmissionLogSeamContract), frame-level AIR invariants

---

## 1. Scope

This contract governs reconciliation between:

- **TransmissionLog** — locked plan (what was intended to air)
- **AsRunLog** — actual execution record (what was recorded as aired)

It does **not** govern:

- Horizon management or horizon-backed schedule services
- Seam validation (covered by TransmissionLogSeamContract)
- Frame-level AIR invariants
- Segmentation or filler logic

Reconciliation is deterministic comparison of plan vs. actual. It produces a pass/fail report with classified outcomes. It does not define the procedure by which AsRunLog is produced or persisted.

---

## 2. Invariants

### INV-ASRUN-001 — Block Coverage

Each executed block in AsRunLog must correspond to **exactly one** TransmissionLogEntry by `block_id`.

**Violations:**

- **Missing planned block** — A TransmissionLog entry has no matching AsRunBlock (block was planned but not executed / not recorded).
- **Extra block** — An AsRunBlock has no matching TransmissionLogEntry (block_id not in plan), or the same block_id appears more than once in AsRunLog.
- **Duplicate block_id** — The same block_id appears more than once in AsRunLog.

---

### INV-ASRUN-002 — Block Timing Fidelity

For each block matched by `block_id`:

- `as_run.start_utc_ms == planned.start_utc_ms`
- `as_run.end_utc_ms == planned.end_utc_ms`

Strict equality unless the block or segment is explicitly classified as runtime recovery. Deviations indicate timing mismatch between plan and execution.

---

### INV-ASRUN-003 — Segment Sequence Integrity

Within each block:

The ordered sequence of segments must match exactly by:

- `segment_type`
- `asset_uri`
- `asset_start_offset_ms`
- `segment_duration_ms`

**Unless:** A segment is explicitly marked as runtime recovery. Runtime-recovery segments are excluded from sequence matching and are classified separately.

---

### INV-ASRUN-004 — No Phantom Segments

No segment may appear in AsRunLog that is not present in the planned TransmissionLog for that block, **unless** explicitly classified as runtime recovery.

Phantom segments are as-run segments that do not correspond to any planned segment in the correct position (or at all).

---

### INV-ASRUN-005 — Divergence Classification

If reconciliation fails (or if allowed deviations occur), the report **must** classify the outcome using exactly the following tags:

| Classification              | Meaning |
|----------------------------|--------|
| `MISSING_BLOCK`            | A planned block has no matching AsRunBlock. |
| `EXTRA_BLOCK`              | An AsRunBlock has no matching plan entry, or duplicate block_id in AsRunLog. |
| `BLOCK_TIME_MISMATCH`      | Block start_utc_ms or end_utc_ms does not match plan. |
| `SEGMENT_SEQUENCE_MISMATCH`| Segment order or identity (type/uri/offset/duration) does not match plan. |
| `PHANTOM_SEGMENT`          | As-run segment has no corresponding planned segment (and is not runtime recovery). |
| `RUNTIME_RECOVERY`         | Segment or block was explicitly marked as runtime recovery and allowed. |
| `RUNWAY_DEGRADATION`       | *(Optional.)* Runtime recovery segment was caused by runway insufficiency, not a planning fault. Implies `RUNTIME_RECOVERY`. |

`RUNWAY_DEGRADATION` is a sub-classification of `RUNTIME_RECOVERY`. It appears only when a runtime-recovery segment is explicitly marked as caused by runway insufficiency (i.e., the plan existed and was well-formed, but material was not READY in time). If present, `RUNTIME_RECOVERY` must also be present. `RUNWAY_DEGRADATION` does not alter the semantics of any other classification.

The contract defines these classification outcomes. It does not define the reconciliation procedure (order of checks, implementation details).

---

## 3. Enforcement

- Reconciliation is performed by a dedicated reconciler function.
- Inputs: TransmissionLog (or equivalent view), AsRunLog (or equivalent view).
- Output: A structured report (success, errors, classifications).
- No mutation of inputs. No dependency on HorizonManager or AIR.
- Reconciler does not auto-correct; it only reports.

---

## 4. Out of Scope (Explicit)

- HorizonManager behaviour
- AIR contracts or frame-level invariants
- Segmentation logic
- Filler logic
- Persistence layer for AsRunLog
- UI or traffic manager
