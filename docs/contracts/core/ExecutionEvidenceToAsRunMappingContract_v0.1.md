# ExecutionEvidenceToAsRunMappingContract_v0.1

**Classification:** Contract (Core Execution Bridge)  
**Owner:** ChannelManager (Execution Recording Integration)  
**Enforcement Phase:** During Playout  
**Created:** 2026-02-13  
**Status:** Proposed

---

## 1. Purpose

This contract specifies the required transformation of execution evidence emitted by AIR into persisted As-Run log artifacts.

**Objectives:**
- **Execution authority** resides with AIR.
- **Persistence authority** resides with ChannelManager.
- **As-Run logs** reflect deterministic, fence-aligned execution truth only.
- **No inference or schedule reconstruction** occurs during this transformation.

*This contract governs the mapping logic only. It does not define artifact formats; see [AsRunLogArtifactContract (v0.2)](../artifacts/AsRunLogArtifactContract.md).*

---

## 2. Architectural Boundary

**Authority Separation:**

| Layer             | Authority                     |
|-------------------|------------------------------|
| Core Planning     | Transmission intent           |
| AIR               | Execution evidence emission   |
| ChannelManager    | As-Run persistence            |
| Reconciler        | Plan vs. actual comparison    |

- **AIR MUST NOT** write `.asrun` files directly.
- **ChannelManager MUST NOT** infer execution events from the schedule.
- **All As-Run entries MUST** originate from explicit execution evidence emitted by AIR.

---

## 3. Execution Evidence Types (AIR → ChannelManager)

AIR emits the following structured evidence types:

### 3.1 BlockStartEvidence

*Emitted when a block becomes active (swap into live producer).*

**Required fields:**
- `block_id`
- `actual_start_utc`
- `swap_tick`
- `fence_tick`
- `primed_success`
- `block_start_display_time`

---

### 3.2 SegmentStartEvidence

*Emitted when a scheduled segment begins emitting frames.*

**Required fields:**
- `event_id`
- `block_id`
- `actual_start_utc`
- `display_time`

---

### 3.3 SegmentEndEvidence

*Emitted when a scheduled segment stops emitting frames.*

**Required fields:**
- `event_id`
- `block_id`
- `actual_duration_ms`
- `status` (One of: `AIRED`, `TRUNCATED`, `SHORT`, `SKIPPED`, `SUBSTITUTED`, `ERROR`)
- `reason` (required if status ≠ AIRED)
- `fallback_frames_used`

---

### 3.4 BlockFenceEvidence

*Emitted when the fence tick fires and a block ends.*

**Required fields:**
- `block_id`
- `actual_end_utc`
- `swap_tick`
- `fence_tick`
- `truncated_by_fence`
- `early_exhaustion`
- `ct_at_fence_ms`
- `total_frames_emitted`

---

## 4. Mapping Rules

ChannelManager MUST transform execution evidence into `.asrun` entries as follows:

---

### MAP-001 — Block Start Mapping

`BlockStartEvidence` produces an entry with:

| Field    | Value                                  |
|----------|----------------------------------------|
| STATUS   | START                                  |
| TYPE     | BLOCK                                  |
| EVENT_ID | `<block_id>`                           |
| ACTUAL   | `<block_start_display_time>`           |
| DUR      | `00:00:00`                             |
| NOTES    | `swap_tick=<int> fence_tick=<int> primed_success=<Y|N>` |

---

### MAP-002 — Segment Lifecycle Mapping

A `SegmentStartEvidence` MUST be paired with exactly one `SegmentEndEvidence` with the same `event_id` before the block fence closes, unless MAP-FAIL-001 triggers. The pair produces one entry:

| Field    | Value                                                   |
|----------|---------------------------------------------------------|
| ACTUAL   | Start display time (from `SegmentStartEvidence`)        |
| DUR      | Actual duration (HH:MM:SS, from `SegmentEndEvidence`)   |
| STATUS   | Status (from `SegmentEndEvidence`)                      |
| TYPE     | Derived from TransmissionLog event_type                 |
| EVENT_ID | `event_id`                                              |
| NOTES    | `fallback_frames_used` and `reason` (if applicable)     |

> *Note:*  
> - No `.asrun` entry is produced until a `SegmentEndEvidence` is received.  
> - Multiple starts without ends are not permitted.

---

### MAP-003 — Fence Mapping

`BlockFenceEvidence` produces an entry with:

| Field    | Value                                                                         |
|----------|-------------------------------------------------------------------------------|
| STATUS   | FENCE                                                                         |
| TYPE     | BLOCK                                                                         |
| EVENT_ID | `<block_id>-FENCE`                                                            |
| ACTUAL   | Display time derived by ChannelManager from `actual_end_utc` using configured display TZ |
| DUR      | `00:00:00`                                                                    |
| NOTES    | `swap_tick=<int> fence_tick=<int> primed_success=<Y|N> truncated_by_fence=<Y|N> early_exhaustion=<Y|N>` |

---

### MAP-004 — No Inference Allowed

ChannelManager MUST NOT:
- Infer segment durations from schedule.
- Infer truncation or completion from fence events without explicit evidence.
- Emit entries not directly backed by AIR evidence.

_All `.asrun` entries MUST correspond exactly (1:1) with evidence events._

---

### MAP-005 — Ordering Guarantee

Entries in `.asrun` MUST appear in execution order:
- Block `START` **before** segment entries.
- Block `FENCE` **after** all segment entries for that block.

---

### MAP-006 — Sidecar Consistency

For each line in `.asrun`, a corresponding `.asrun.jsonl` sidecar entry must be generated containing:

- `event_id`
- `block_id`
- `actual_start_utc`
- `actual_duration_ms`
- `status`
- `reason`
- `swap_tick` (for fence)
- `fence_tick` (for fence)

---

## 5. Failure Handling

### MAP-FAIL-001 — Missing SegmentEndEvidence

If a segment starts, but no `SegmentEndEvidence` is received before the block fence:
- ChannelManager emits a `TRUNCATED` segment entry at fence time.
- `reason` MUST be `FENCE_TERMINATION`.

---

### MAP-FAIL-002 — Missing BlockFenceEvidence

If playout stops unexpectedly, without `BlockFenceEvidence`:
- ChannelManager emits a final **ERROR** entry:

| Field   | Value                |
|---------|----------------------|
| STATUS  | ERROR                |
| TYPE    | BLOCK                |
| reason  | CHANNEL_TERMINATED   |

- File MUST remain append-only.

---

## 6. Required Tests

- BlockStartEvidence mapping test
- Segment lifecycle mapping test
- Fence evidence mapping test
- Missing SegmentEnd → TRUNCATED test
- Crash mid-block → ERROR test
- Sidecar consistency test
- Order preservation test

---

## 7. Relationship to Other Contracts

- **TransmissionLogArtifactContract_v0.1:**  
  Defines scheduled intent and stable EVENT_IDs.

- **AsRunLogArtifactContract (v0.2):**  
  [docs/contracts/artifacts/AsRunLogArtifactContract.md](../artifacts/AsRunLogArtifactContract.md) — file format and persistence invariants.

- **INV-BLOCK-WALLCLOCK-FENCE-001:**  
  Governs timing authority for BlockFenceEvidence.

- **INV-BLOCK-LOOKAHEAD-PRIMING:**  
  Defines and supplies the `primed_success` field.

---

**This contract bridges AIR execution evidence to persistent As-Run artifacts, without leakage of scheduling or inference.**