# gRPC Evidence Interface Contract — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Core ↔ AIR Coordination)  
**Authority Level:** Coordination (Wire Protocol)  
**Governs:** AIR gRPC Client → Core Evidence Server  
**Out of Scope:** Evidence emission logic (see AirExecutionEvidenceEmitterContract), spool persistence (see AirExecutionEvidenceSpoolContract), as-run mapping (see ExecutionEvidenceToAsRunMappingContract)

---

## 1. Purpose

This contract defines the bidirectional gRPC streaming protocol between AIR and Core for execution evidence transport. It specifies the handshake, sequencing, acknowledgement, deduplication, reconnection, and error handling semantics at the wire level.

AIR emits execution evidence. Core persists it durably and acknowledges. This contract governs the transport layer between those responsibilities.

---

## 2. Authority Model

### AIR (Client)

- **Emission authority.** Owns evidence production and sequence assignment.
- Maintains local spool for crash-resilient replay.
- Initiates connection and handshake.

### Core (Server)

- **Persistence authority.** Owns durable write of evidence to as-run artifacts.
- **ACK authority.** An ACK from Core constitutes a durability guarantee.
- Maintains durable ack store per (channel_id, playout_session_id).

### No shared authority

- AIR MUST NOT assume durability without receiving an ACK.
- Core MUST NOT emit evidence or invent execution state.

---

## 3. Service Definition

**Proto:** `protos/execution_evidence_v1.proto`  
**Package:** `retrovue.evidence.v1`

```protobuf
service ExecutionEvidenceService {
  rpc EvidenceStream(stream EvidenceFromAir)
      returns (stream EvidenceAckFromCore);
}
```

Bidirectional streaming: AIR sends `EvidenceFromAir` messages, Core returns `EvidenceAckFromCore` messages. One stream per channel playout session.

---

## 4. Handshake Protocol

### GRPC-EVID-001 — HELLO Handshake

AIR MUST send a `HELLO` message as the first message on each new stream.

**HELLO message fields:**
- `schema_version = 1`
- `channel_id` — channel being played
- `playout_session_id` — unique session identifier
- `sequence = 0` — HELLO always carries sequence 0
- `event_uuid = "hello"`
- `payload.hello.first_sequence_available` — lowest sequence AIR can replay from spool
- `payload.hello.last_sequence_emitted` — highest sequence AIR has emitted

**Core response:**
- Core MUST ACK the HELLO with `acked_sequence = 0`.
- Core initializes the stream's writer and loads durable ack state for this session.

### GRPC-EVID-002 — Post-HELLO Replay

After receiving the HELLO ACK, AIR replays from spool all events with `sequence > acked_sequence` (from Core's durable ack store). After replay completes, AIR streams new live events.

**Replay ordering:** Events MUST be replayed in strictly ascending sequence order.

---

## 5. Message Envelope

Every `EvidenceFromAir` message carries:

| Field | Type | Constraint |
|-------|------|------------|
| `schema_version` | uint32 | MUST be 1 |
| `channel_id` | string | Non-empty; identifies the channel |
| `playout_session_id` | string | Non-empty; identifies the playout session |
| `sequence` | uint64 | Strictly monotonic (see GRPC-EVID-004) |
| `event_uuid` | string | Globally unique per event (see GRPC-EVID-003) |
| `emitted_utc` | string | ISO8601 UTC timestamp of emission |
| `payload` | oneof | One of: Hello, BlockStart, SegmentStart, SegmentEnd, BlockFence, ChannelTerminated |

---

## 6. Sequence Discipline

### GRPC-EVID-004 — Sequence Monotonicity

The `sequence` field MUST increase strictly by +1 for each evidence event within a playout session. HELLO carries sequence 0. The first evidence event carries sequence 1.

**No gaps.** If Core receives sequence N, the next non-duplicate evidence event MUST carry sequence N+1.

**Session reset.** A new `playout_session_id` resets the sequence counter to 0 (HELLO) / 1 (first event).

---

## 7. Acknowledgement Semantics

### GRPC-EVID-005 — ACK Implies Durability

Every `EvidenceAckFromCore` message constitutes a durability guarantee: the evidence event identified by `acked_sequence` has been written to persistent storage (`.asrun` + `.asrun.jsonl`) and flushed to disk before the ACK was sent.

**ACK message fields:**
- `channel_id` — echoed from the evidence message
- `playout_session_id` — echoed from the evidence message
- `acked_sequence` — the sequence number being acknowledged
- `error` — empty string on success; non-empty on processing error

### GRPC-EVID-006 — ACK Ordering

Core MUST ACK messages in the order they are received. For each evidence message processed (including deduplicated messages), exactly one ACK MUST be yielded.

### GRPC-EVID-007 — Durable ACK Store

Core maintains a persistent ack store at:
```
{ack_dir}/{channel_id}/{playout_session_id}.ack
```

**File format:**
```
acked_sequence=<uint64>
updated_utc=<iso8601>
```

The ack store records the high-water mark of durably committed sequences. Updates are atomic (write to temp file, then rename). The store is monotonic: a lower sequence value MUST NOT overwrite a higher one.

---

## 8. Deduplication

### GRPC-EVID-003 — Dual-Layer Deduplication

Core MUST deduplicate evidence events using two mechanisms:

**Layer 1 — Intra-stream dedup (event_uuid):**  
Within a single stream, if a message arrives with an `event_uuid` already seen in this stream, it is a duplicate. Core MUST ACK the duplicate but MUST NOT write it to as-run artifacts.

**Layer 2 — Cross-stream dedup (durable ack high-water mark):**  
On reconnect/replay, if a message arrives with `sequence <= durable_ack_sequence` for this session, it was already committed in a prior stream. Core MUST ACK the duplicate but MUST NOT write it again.

**HELLO messages** (event_uuid = "hello") are exempt from dedup — they are always processed.

---

## 9. Reconnect and Resume Protocol

### GRPC-EVID-008 — Resume from Durable ACK

On reconnection (new stream for the same session):

1. AIR opens a new bidirectional stream.
2. AIR sends HELLO with `last_sequence_emitted` reflecting the highest sequence in its spool.
3. Core loads the durable ack for this (channel_id, playout_session_id).
4. Core ACKs the HELLO.
5. AIR replays from spool: all events with `sequence > acked_sequence`.
6. Core deduplicates any events that were already committed (cross-stream dedup per GRPC-EVID-003 Layer 2).

**Resume source:** AIR MUST replay from its durable spool, never from in-memory state alone (per AirExecutionEvidenceSpoolContract SP-005).

### GRPC-EVID-009 — Fresh Server Resume

If Core restarts with a fresh (empty) ack store, it ACKs the HELLO with `acked_sequence = 0`. AIR replays its entire spool. Core writes all events (no cross-stream dedup triggers since durable ack is 0).

If Core restarts with a preserved ack store, it loads the persisted high-water mark. AIR's replayed events with `sequence <= acked_sequence` are deduplicated; only new events are written.

---

## 10. Concurrent Streams

Core MUST support multiple concurrent evidence streams (one per channel/session). Streams for different channels MUST NOT interfere with each other. Each stream maintains independent:
- `seen_uuids` set (intra-stream dedup)
- AsRunWriter instance
- Durable ack tracking

---

## 11. Evidence Payload Types

The following payload types are transported over this protocol. Emission rules are defined in AirExecutionEvidenceEmitterContract; mapping rules are defined in ExecutionEvidenceToAsRunMappingContract. This section specifies wire-level constraints only.

| Payload | Key Fields | Wire Constraint |
|---------|-----------|-----------------|
| `Hello` | `first_sequence_available`, `last_sequence_emitted` | MUST be first message; sequence MUST be 0 |
| `BlockStart` | `block_id`, `swap_tick`, `fence_tick`, `actual_start_utc_ms`, `primed_success` | One per block activation |
| `SegmentStart` | `block_id`, `event_id`, `segment_index`, `actual_start_utc_ms`, `asset_start_frame`, `segment_uuid`, `segment_type_name`, `asset_uri` | One per segment start |
| `SegmentEnd` | `block_id`, `event_id_ref`, `actual_start_utc_ms`, `actual_end_utc_ms`, `computed_duration_ms`, `computed_duration_frames`, `status`, `segment_uuid`, `segment_type_name` | One per segment end; `event_id_ref` MUST match prior `SegmentStart.event_id` |
| `BlockFence` | `block_id`, `swap_tick`, `fence_tick`, `actual_end_utc_ms`, `total_frames_emitted`, `truncated_by_fence`, `early_exhaustion` | One per block fence |
| `ChannelTerminated` | `termination_utc_ms`, `reason`, `detail` | Terminal event; no further evidence in this session |

---

## 12. Error Handling

### GRPC-EVID-010 — Schema Version Mismatch

If `schema_version != 1`, Core MUST ACK with a non-empty `error` field describing the mismatch. Core MUST NOT write the event to as-run artifacts.

### GRPC-EVID-011 — Malformed Messages

If a message lacks required fields (empty `channel_id`, missing payload), Core MUST ACK with a non-empty `error` field. Core MUST NOT write the event.

### GRPC-EVID-012 — Stream Termination

When the client closes the stream (normal or abnormal), Core MUST close the AsRunWriter and log the stream closure. No implicit evidence is generated on stream close.

---

## 13. Processing Order (Write-Then-ACK)

For each non-duplicate evidence message, Core MUST:

1. Map the evidence to as-run artifacts (per ExecutionEvidenceToAsRunMappingContract).
2. Write and flush both `.asrun` and `.asrun.jsonl` files to disk.
3. Update the durable ack store.
4. THEN yield the ACK.

This ordering guarantees that an ACK is never sent for evidence that has not been durably persisted. If Core crashes between write and ACK, AIR replays from spool; the duplicate is deduplicated on the next connection.

---

## 14. Required Tests

- `pkg/core/tests/test_grpc_evidence_basic.py` — HELLO + event ACK ordering
- `pkg/core/tests/test_grpc_failure_scenarios.py` — Core crash recovery, AIR crash replay, duplicate dedup
- `pkg/core/tests/test_grpc_replay_resume.py` — Replay after restart, durable ack persistence, write-before-ACK

---

## 15. Relationship to Other Contracts

- **AirExecutionEvidenceEmitterContract_v0.1:**  
  Defines when and what AIR emits. This contract defines how it is transported and acknowledged.

- **AirExecutionEvidenceSpoolContract_v0.1:**  
  Defines AIR-side durable spool for crash-resilient replay. This contract defines the replay protocol.

- **ExecutionEvidenceToAsRunMappingContract_v0.1:**  
  Defines how Core maps evidence to persistent as-run artifacts. This contract defines the durability guarantee that ACK implies.

- **AsRunLogArtifactContract (v0.2):**  
  Defines the file format and persistence invariants for as-run outputs.

---

**This contract defines the wire-level protocol for execution evidence transport between AIR and Core, ensuring no evidence is lost, duplicated in persistence, or acknowledged before durable write.**
