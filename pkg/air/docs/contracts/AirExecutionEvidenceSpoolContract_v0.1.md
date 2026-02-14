# AirExecutionEvidenceSpoolContract_v0.1

**Classification:** Contract (AIR Durability Mechanism)  
**Owner:** AIR Runtime  
**Enforcement Phase:** During Playout Execution  
**Created:** 2026-02-13  
**Status:** Proposed

---

## Overview

> **Objective:**  
> Guarantee that AIR _never loses execution evidence:_  
> - Even if Core is down  
> - During network/outage events  
> - Across AIR restart or crash  
> - While mid-block

**Core** always controls ACK (evidence is not “committed” until Core persists it), but **AIR** never loses any evidence.  
Resume and replay is always deterministic and idempotent.

---

## 1. Purpose

Define a _durable, crash-resilient evidence spooling mechanism_ that guarantees every execution evidence event produced by AIR (see contracts below) is locally preserved until acked by Core.

**This contract covers:**
- What is spooled
- Where it’s stored
- Spool persistence and replay discipline
- Retention, compaction, and failure handling

**Related contracts:**
- [ExecutionEvidenceGrpcInterfaceContract_v0.1](../../docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md)
- [AirExecutionEvidenceEmitterContract_v0.1](./AirExecutionEvidenceEmitterContract_v0.1.md)

AIR MUST persist all evidence required by these contracts until Core’s durable ACK.

---

## 2. Storage Location

- Spool files **per channel:**  
  ```
  /opt/retrovue/data/logs/evidence_spool/{channel_id}/
  ```
- **Per playout session:**  
  ```
  /opt/retrovue/data/logs/evidence_spool/{channel_id}/{playout_session_id}.spool.jsonl
  ```
- Format: `JSONL` (one JSON object per line, for v0.1)

> _Binary/protobuf may be introduced in a later version. For v0.1, human-debbugable JSONL is used._

---

## 3. Spool Record Format

- Each line: **one full JSON object** representing a `EvidenceFromAir` protobuf message.

**Required fields:**  
- `schema_version`
- `channel_id`
- `playout_session_id`
- `sequence`
- `event_uuid`
- `emitted_utc`
- `payload_type` _(string)_
- `payload` _(object)_

**Example:**
```json
{
  "schema_version": 1,
  "channel_id": "classic-1",
  "playout_session_id": "PS-20260213-classic-1-0001",
  "sequence": 42,
  "event_uuid": "...",
  "emitted_utc": "...",
  "payload_type": "BLOCK_FENCE",
  "payload": { ... }
}
```

---

## 4. Spool Invariants

### SP-001 — Append Only  
Spool files MUST be strictly append-only. Existing records are **never** modified in place.

### SP-002 — Flush Discipline  
Each appended record MUST be _flushed to disk_ before it is considered “spooled”.  
> Batching/fsync may be used, but a bounded flush window is required (see §7).

### SP-003 — Sequence Monotonicity  
Records MUST be written in _strictly increasing_ `sequence` order **with no gaps**.

### SP-004 — Idempotent Replay  
On replay, AIR MAY send duplicates; Core handles deduplication via `event_uuid`.  
AIR **MUST NOT** re-generate new `event_uuid` values during replay.

### SP-005 — Spool is Replay Source  
After any disconnect, AIR MUST replay from **spool**, _never_ from only in-memory state, _provided the spool is readable_.

---

## 5. Replay Protocol (Core ACK → AIR Replay)

- **AIR MUST persistently track each session’s latest Core ACK.**

### SP-ACK-001 — Ack Tracking File  
Store Core’s last ACK at:  
```
/opt/retrovue/data/logs/evidence_spool/{channel_id}/{playout_session_id}.ack
```
**File contents (text):**
```
acked_sequence=<uint64>
updated_utc=<iso8601>
```

### SP-ACK-002 — Replay Start  
On reconnect, AIR REPLAYS all spooled events with:  
```
sequence > acked_sequence
```

### SP-ACK-003 — Ack Update Discipline  
Update the `.ack` file **only** upon receipt of a strictly higher `acked_sequence`. File must be **flushed** after update.

---

## 6. Spool Retention and Compaction

### SP-RET-001 — Safe Deletion Rule  
AIR **MUST NOT** delete a spool file until _both_:  
- Core ACKs at least the final sequence in the spool; **AND**
- Spool contains a finalizing event (`BLOCK_FENCE` for last block OR `CHANNEL_TERMINATED`)

### SP-RET-002 — Compaction Allowed  
AIR **MAY** compact spool files by truncating already-ACKed prefix (that is, dropping records where `sequence <= acked_sequence`), **provided:**
- All events with `sequence > acked_sequence` are preserved
- Compaction process is crash-safe (write to temp + atomic rename)

### SP-RET-003 — Bounded Disk Usage  
AIR MUST enforce a SP configurable disk space cap _per channel_.  
If exceeded, AIR MUST:
- Refuse to start new playout sessions for that channel **OR**
- Emit `CHANNEL_TERMINATED` with reason `EVIDENCE_SPOOL_FULL`

> **Under no circumstances should AIR silently drop evidence records.**

---

## 7. Performance and Timing Constraints

### SP-PERF-001 — Non-Blocking Emission  
Spooling MUST NOT block frame emission.  
AIR MUST use an internal queue and a _dedicated_ spool writer thread.

### SP-PERF-002 — Flush Window Bound  
Spool writer must flush records at least every:  
- `flush_interval_ms` (**default: 250ms**) **OR**
- `flush_records_max` (**default: 50 records**)  
(Whichever comes first.)

> This bounds the maximum risk window for evidence loss to small, controlled bursts.

---

## 8. Crash Recovery Behavior

### SP-CRASH-001 — Recovery on Restart  
On AIR restart:
- If a session’s spool file exists and `.ack` indicates not all delivered:  
  - Next Core connection → replay from spool
- If a new session starts (new `playout_session_id`), AIR **SHOULD STILL** offer replay of _unfinished_ old spool files for that channel (unless configured otherwise)

> Prevents evidence loss even in the face of process restarts.

### SP-CRASH-002 — Corrupt Tail Handling  
If the spool file ends with a _corrupt/incomplete JSON record_:  
- Incomplete final line MUST be ignored  
- Prior records MUST be left intact  
- Appending resumes from the last valid record

---

## 9. Required AIR Tests

- Append-only spool test
- Sequence monotonicity test
- Disconnect & replay test (acked_sequence respected)
- Crash/restart replay test (spool survives)
- ACK persistence test (`.ack` updated & flushed)
- Corrupt tail recovery test
- Disk cap enforcement test (no silent drops)
- Compaction atomicity test (temp + rename)

---

## 10. Relationship to Other Contracts

- **[ExecutionEvidenceGrpcInterfaceContract_v0.1](../../docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md):**  
  Defines ACK high-water mark semantics for replay.

- **[AirExecutionEvidenceEmitterContract_v0.1](./AirExecutionEvidenceEmitterContract_v0.1.md):**  
  Specifies when evidence events are to be produced.

- **[AsRunLogArtifactContract (v0.2)](../../../docs/contracts/artifacts/AsRunLogArtifactContract.md):**  
  Requires Core to commit durability before advancing ACK.

> **Spooling guarantees evidence is reliably deliverable until Core persists and acknowledges each event.**