# Transmission Log Seam Contract — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Planning Artifact Integrity)  
**Authority Level:** Core (Planning Pipeline)  
**Governs:** TransmissionLog seam invariants before execution eligibility  
**Out of Scope:** AIR frame-level seams, filler logic, segmentation logic

---

## 1. Scope

This contract applies to all TransmissionLog artifacts eligible for execution.

A TransmissionLog becomes execution-eligible when it is locked (e.g., via `lock_for_execution` or equivalent lifecycle transition). Invariants defined herein must hold for any TransmissionLog before it is marked execution-eligible. Violations indicate planning pipeline defects and must be rejected before execution.

---

## 2. Invariants

### INV-TL-SEAM-001 — Contiguous Boundaries

For all consecutive entries:

```
entry[i].end_utc_ms == entry[i+1].start_utc_ms
```

No wall-clock gaps or overlaps allowed. Each entry's end must exactly meet the next entry's start.

---

### INV-TL-SEAM-002 — Grid Duration Consistency

Each entry duration must equal:

```
grid_block_minutes × 60 × 1000
```

(expressed in milliseconds)

Unless explicitly overridden by a future contract version. Deviations indicate misalignment with the channel's grid configuration.

---

### INV-TL-SEAM-003 — Monotonic Ordering

Entries must be strictly increasing in time:

```
entry[i].start_utc_ms < entry[i].end_utc_ms
entry[i].end_utc_ms <= entry[i+1].start_utc_ms  (implied by INV-TL-SEAM-001)
```

Entries are ordered by `start_utc_ms`; no out-of-order or duplicate time ranges.

---

### INV-TL-SEAM-004 — Non-Zero Duration

For every entry:

```
end_utc_ms > start_utc_ms
```

No zero-duration or negative-duration entries.

---

## 3. Enforcement

- Validation is performed by a dedicated seam validator before a TransmissionLog is marked execution-eligible.
- Violations raise `TransmissionLogSeamError`.
- Core owns wall-clock seam integrity. AIR continues to own frame-level seam integrity.
