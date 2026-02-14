# AirExecutionEvidenceInterfaceContract_v0.1

**Classification:** Contract (AIR ↔ Core Interface)  
**Owner:** AIR (Emitter) + ChannelManager (Receiver)  
**Enforcement Phase:** During Playout  
**Created:** 2026-02-13  
**Status:** Proposed  

---

## 1. Purpose

This contract specifies the **wire-level interface** by which AIR emits *authoritative execution evidence* to Core runtime (`ChannelManager`).

**It ensures:**
- **Execution truth** originates in AIR.
- **ChannelManager persists As-Run artifacts** from explicit evidence (no inference).
- Evidence is **machine-parseable, ordered, crash-resilient, and idempotent**.

**Contractual Dependencies:**  
- [ExecutionEvidenceToAsRunMappingContract_v0.1](../core/ExecutionEvidenceToAsRunMappingContract_v0.1.md)  
- [AsRunLogArtifactContract (v0.2)](../artifacts/AsRunLogArtifactContract.md)  
- [TransmissionLogArtifactContract_v0.1](../core/TransmissionLogArtifactContract_v0.1.md)  

> :information_source:  
> *This contract governs the “on-the-wire” shape, not how AIR’s internals produce evidence.*

---

## 2. Transport Requirements

- **Evidence MUST be emitted as a byte stream** of UTF-8 encoded JSON objects.
    - Each object is a single line of *newline-delimited JSON (“JSONL”)* (`\n` delimiter).
    - Each line MUST contain a **complete JSON object** (no multi-line records).

- **Transport-agnostic:**  
  Examples include:
  - Dedicated `stdout` stream  
  - Named pipe (FIFO)  
  - Unix domain socket  
  - TCP stream  
  - gRPC streaming (yielding line-by-line JSONL)  

---

## 3. Stream Separation

- Evidence MUST NOT be mixed/interleaved with:
  - Human logs
  - Diagnostics
  - Banner text
  - ffmpeg logs
  - Metrics

- **Evidence MUST be emitted on a dedicated, evidence-only stream/channel** read by ChannelManager.

---

## 4. Evidence Envelope Schema

Each evidence line MUST be a valid JSON object (**EvidenceEnvelope**) with the following required fields:

```json
{
  "schema_version": 1,
  "event_type": "BLOCK_START",
  "channel_id": "classic-1",
  "playout_session_id": "PS-20260213-classic-1-0001",
  "sequence": 42,
  "event_id": "EVID-<uuid-or-stable-id>",
  "emitted_utc": "2026-02-13T15:00:00.123Z",
  "payload": { ... }
}
```

**Field requirements:**
- `schema_version` *(int)*: MUST be 1 for this contract version.
- `event_type` *(str)*: One of the enumerated [Event Types](#5-event-types-and-payload-schemas).
- `channel_id` *(str)*: Logical RetroVue channel identifier.
- `playout_session_id` *(str)*: Unique identifier for the AIR playout session.
- `sequence` *(int)*: Monotonically increasing per `(channel_id, playout_session_id)`, starting at 1.
- `event_id` *(str)*: Globally unique for idempotency (UUID or deterministic).
- `emitted_utc` *(str)*: RFC 3339 / ISO8601 UTC timestamp with Z.
- `payload` *(obj)*: **Event-specific fields** (see below).

---

## 5. Event Types and Payload Schemas

AIR MUST emit the following event types **with required per-type payload structure**:

---

### 5.1 `BLOCK_START`  
*Emitted once when a block becomes active (enters the live slot).*

```json
{
  "block_id": "BLK-001",
  "swap_tick": 900,
  "fence_tick": 900,
  "actual_start_utc": "2026-02-13T15:00:00.000Z",
  "primed_success": true
}
```

| Field            | Type      | Description                  |
|------------------|-----------|------------------------------|
| block_id         | string    | Block identifier             |
| swap_tick        | int       | Tick index of swap           |
| fence_tick       | int       | Tick index of fence          |
| actual_start_utc | UTC str   | Block actual start UTC       |
| primed_success   | bool      | Block successfully primed    |

---

### 5.2 `SEGMENT_START` *(Optional; if emitted, must be consistent)*  
*Emitted when a scheduled segment begins emitting frames.*

```json
{
  "block_id": "BLK-001",
  "event_id_ref": "EVT-0001",
  "actual_start_utc": "2026-02-13T15:00:00.000Z"
}
```

| Field            | Type      | Description                                             |
|------------------|-----------|---------------------------------------------------------|
| block_id         | string    | Block identifier                                        |
| event_id_ref     | string    | Transmission log EVENT_ID                               |
| actual_start_utc | UTC str   | Actual segment start UTC                                |

> **Note:**  
> `SEGMENT_START` is optional if `SEGMENT_END` (see below) always includes `actual_start_utc`.  
> If `SEGMENT_START` is present for an event, there MUST be a corresponding `SEGMENT_END`, unless [§7 Failure Semantics](#7-failure-semantics-crash--missing-evidence) applies.

---

### 5.3 `SEGMENT_END`  
*Emitted when a segment stops emitting frames, recording final outcome.*

```json
{
  "block_id": "BLK-001",
  "event_id_ref": "EVT-0001",
  "actual_start_utc": "2026-02-13T15:00:00.000Z", // Required unless SEGMENT_START emitted
  "actual_duration_ms": 1350000,
  "status": "AIRED",
  "reason": "NONE",
  "fallback_frames_used": 0
}
```

| Field                 | Type    | Required | Description                      |
|-----------------------|---------|----------|----------------------------------|
| block_id              | string  | yes      | Block identifier                 |
| event_id_ref          | string  | yes      | Transmission log EVENT_ID        |
| actual_start_utc      | UTC str | *see*    | Actual start; required unless SEGMENT_START is present |
| actual_duration_ms    | int     | yes      | Segment playout duration (ms)    |
| status                | string  | yes      | Execution status (see below)     |
| reason                | string  | yes      | Execution reason (see below)     |
| fallback_frames_used  | int     | yes      | Number of fallback frames used   |

*Status enum (must match [As-Run contract](../artifacts/AsRunLogArtifactContract.md)):*  
- `AIRED`, `TRUNCATED`, `SHORT`, `SKIPPED`, `SUBSTITUTED`, `ERROR`

*Reason enum (minimum set):*  
- `NONE`, `FENCE_TERMINATION`, `DECODE_ERROR`, `ASSET_MISSING`, `PIPELINE_ERROR`, `CHANNEL_TERMINATED`, `SUBSTITUTION_APPLIED`  
*(Extendable; must remain a string)*

---

### 5.4 `BLOCK_FENCE`  
*Emitted once when the block fence tick fires and the block ends.*

```json
{
  "block_id": "BLK-001",
  "swap_tick": 900,
  "fence_tick": 900,
  "actual_end_utc": "2026-02-13T15:30:00.000Z",
  "ct_at_fence_ms": 1798200,
  "total_frames_emitted": 54000,
  "truncated_by_fence": false,
  "early_exhaustion": false,
  "primed_success": true
}
```

| Field                | Type    | Description                       |
|----------------------|---------|-----------------------------------|
| block_id             | string  | Block identifier                  |
| swap_tick            | int     | Swap point tick                   |
| fence_tick           | int     | Fence point tick                  |
| actual_end_utc       | UTC str | Actual end UTC                    |
| ct_at_fence_ms       | int     | Channel time at fence (ms)        |
| total_frames_emitted | int     | Frames emitted in block           |
| truncated_by_fence   | bool    | Segment truncated by fence        |
| early_exhaustion     | bool    | Segment exhausted early           |
| primed_success       | bool    | Block was primed                  |

---

### 5.5 `CHANNEL_TERMINATED`  
*Emitted if AIR playout ends unexpectedly or intentionally—no further evidence will be sent.*

```json
{
  "termination_utc": "2026-02-13T15:12:34.000Z",
  "reason": "PIPELINE_ERROR",
  "detail": "optional short string"
}
```

| Field           | Type    | Required | Description                     |
|-----------------|---------|----------|---------------------------------|
| termination_utc | UTC str | yes      | Termination moment (wall UTC)   |
| reason          | string  | yes      | Reason (see prior enums)        |
| detail          | string  | opt      | Brief human detail              |

---

## 6. Ordering and Completeness Invariants

- **EVID-IF-001 — Monotonic ordering:**  
  For a given `(channel_id, playout_session_id)`, `sequence` increments strictly by 1.

- **EVID-IF-002 — Block lifecycle order:**  
  For each `block_id`:  
    - `BLOCK_START` before segment events  
    - `BLOCK_FENCE` after all segment ends (unless [§7](#7-failure-semantics-crash--missing-evidence) applies)

- **EVID-IF-003 — Idempotency key:**  
  `event_id` is globally unique for deduplication.

- **EVID-IF-004 — No mixed sessions:**  
  Evidence for distinct `playout_session_id` MUST NOT interleave on a single stream.

---

## 7. Failure Semantics (Crash / Missing Evidence)

- **EVID-FAIL-001 — Segment Open at Fence:**  
  If a segment starts but does not yield `SEGMENT_END` by `BLOCK_FENCE`, AIR MAY omit the segment end.  
  → ChannelManager MUST synthesize a `TRUNCATED` (`reason=FENCE_TERMINATION`) [per mapping contract](../core/ExecutionEvidenceToAsRunMappingContract_v0.1.md).

- **EVID-FAIL-002 — Abrupt Channel Termination:**  
  On unexpected AIR termination:  
    - If possible, emit `CHANNEL_TERMINATED`  
    - If not, ChannelManager MUST synthesize a terminal `.asrun` `ERROR` block line on stream EOF

---

## 8. Relationship to Other Contracts

- [ExecutionEvidenceToAsRunMappingContract_v0.1](../core/ExecutionEvidenceToAsRunMappingContract_v0.1.md):  
  **This contract is the sole evidence input.**

- [AsRunLogArtifactContract (v0.2)](../artifacts/AsRunLogArtifactContract.md):  
  **Evidence MUST be sufficient** to reconstruct `.asrun` file and sidecar **without editorial inference.**

- [TransmissionLogArtifactContract_v0.1](../core/TransmissionLogArtifactContract_v0.1.md):  
  `event_id_ref` values must match `EVENT_ID` in the day’s transmission log.

---

## 9. Required Tests

The following MUST be tested and referenced from repo contract-test suites:

- **Schema validation test:** Each evidence line parses as JSON; envelope fields/types correct.
- **Ordering test:** Stream sequence increments strictly; block lifecycle ordering enforced.
- **Idempotency/dedup test:** Receiver can ignore duplicate `event_id`.
- **Minimal completeness test:** A typical block with two segments is sufficient to emit evidence for all `.asrun` lines (START, 2 segments, FENCE).
- **Termination test:** `CHANNEL_TERMINATED` or stream EOF produces correct `.asrun` finalization.

---

## 10. Non-Goals

_This contract does not specify:_
- Internal AIR classes/generation logic
- How AIR computes fence tick or block priming
- How ChannelManager persists `.asrun` files (see artifact contract)
- Metrics or telemetry heartbeat protocols

---

**Addendum — Evidence Profile Selection:**  
You MAY choose a minimal interface (“Profile A”) omitting `SEGMENT_START`:
- **Profile A:** `BLOCK_START`, `SEGMENT_END` (with `actual_start_utc`), `BLOCK_FENCE`, `CHANNEL_TERMINATED`
- **Profile B:** explicit `SEGMENT_START` ↔ `SEGMENT_END` pairs

Either is valid; Profile A is less stateful for ChannelManager.
