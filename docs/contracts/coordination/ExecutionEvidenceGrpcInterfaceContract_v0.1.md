# ExecutionEvidenceGrpcInterfaceContract_v0.1

**Classification:** Contract (AIR ↔ Core gRPC Interface)  
**Owner:** AIR Runtime + Core ChannelManager  
**Enforcement Phase:** During Playout Execution  
**Created:** 2026-02-13  
**Status:** Proposed

---

## 1. Purpose

This contract defines the **authoritative gRPC streaming interface** between AIR and Core for transmission of execution evidence.

It ensures:

- **Strong typing:** Protobuf schema
- **Strict ordering guarantees**
- **Idempotent processing**
- **Explicit ACK + resume semantics**
- **Deterministic integration** with:
  - [AirExecutionEvidenceEmitterContract_v0.1](AirExecutionEvidenceEmitterContract_v0.1.md)
  - [ExecutionEvidenceToAsRunMappingContract_v0.1](../core/ExecutionEvidenceToAsRunMappingContract_v0.1.md)
  - [AsRunLogArtifactContract (v0.2)](../artifacts/AsRunLogArtifactContract.md)

**This is the canonical transport for execution evidence.**

---

## 2. Transport Model

- Implemented as **bidirectional streaming gRPC**:
  
  ```
  rpc EvidenceStream(stream EvidenceFromAir)
      returns (stream EvidenceAckFromCore);
  ```

- **Stream properties:**
  - Dedicated to execution evidence
  - Separated from playout control RPCs
  - Exactly one active stream per `(channel_id, playout_session_id)`

---

## 3. Ordering and Delivery Guarantees

- **GRPC-EVID-001 — In-Stream Ordering:**  
  Evidence messages MUST be processed in the order received.

- **GRPC-EVID-002 — Sequence Authority:**  
  Each `EvidenceFromAir` MUST contain `sequence` (`uint64`):
  - Starts at 1 per `playout_session_id`
  - Increments strictly by 1
  - Values MUST NOT be skipped

- **GRPC-EVID-003 — Idempotency:**  
  Each `EvidenceFromAir` must contain `event_uuid` (string).
  - Core MUST deduplicate on `event_uuid`
  - Duplicate events MUST NOT create duplicate As-Run entries

---

## 4. Resume and ACK Semantics

This interface MUST support **resumption after disconnect**.

### 4.1 Initial Handshake

- **First AIR message:** `HELLO`  
  Including:
  - `channel_id`
  - `playout_session_id`
  - `first_sequence_available`
  - `last_sequence_emitted`

- **Core responds:** `ACK`  
  With:
  - `acked_sequence` (highest successfully processed sequence)

### 4.2 Replay Rule

- Upon receiving `ACK`:
  - If `acked_sequence < last_sequence_emitted`:  
    AIR MUST replay all events with `sequence > acked_sequence`
  - If equal:  
    AIR continues streaming new events

- **GRPC-EVID-004 — High-Water Mark ACK:**  
  Core MUST periodically send:
  ```protobuf
  EvidenceAckFromCore {
      acked_sequence: <highest durable sequence>
  }
  ```
  **Durable** means:
  - .asrun entry written
  - Sidecar JSONL written
  - Flush completed

  Core MUST NOT ack beyond what is safely persisted.

---

## 5. Protobuf Schema Definition

**The following .proto definition is normative for v1.**

```protobuf
syntax = "proto3";

package retrovue.evidence.v1;

service ExecutionEvidenceService {
  rpc EvidenceStream(stream EvidenceFromAir)
      returns (stream EvidenceAckFromCore);
}

message EvidenceFromAir {
  uint32 schema_version = 1;              // must be 1
  string channel_id = 2;
  string playout_session_id = 3;
  uint64 sequence = 4;
  string event_uuid = 5;
  string emitted_utc = 6;                 // ISO8601 Z

  oneof payload {
    Hello hello = 10;
    BlockStart block_start = 11;
    SegmentEnd segment_end = 12;
    BlockFence block_fence = 13;
    ChannelTerminated channel_terminated = 14;
  }
}

message EvidenceAckFromCore {
  string channel_id = 1;
  string playout_session_id = 2;
  uint64 acked_sequence = 3;
  string error = 4; // optional
}

message Hello {
  uint64 first_sequence_available = 1;
  uint64 last_sequence_emitted = 2;
}

message BlockStart {
  string block_id = 1;
  uint64 swap_tick = 2;
  uint64 fence_tick = 3;
  string actual_start_utc = 4;
  bool primed_success = 5;
}

message SegmentEnd {
  string block_id = 1;
  string event_id_ref = 2;
  string actual_start_utc = 3;
  uint64 actual_duration_ms = 4;
  string status = 5;
  string reason = 6;
  uint64 fallback_frames_used = 7;
}

message BlockFence {
  string block_id = 1;
  uint64 swap_tick = 2;
  uint64 fence_tick = 3;
  string actual_end_utc = 4;
  uint64 ct_at_fence_ms = 5;
  uint64 total_frames_emitted = 6;
  bool truncated_by_fence = 7;
  bool early_exhaustion = 8;
  bool primed_success = 9;
}

message ChannelTerminated {
  string termination_utc = 1;
  string reason = 2;
  string detail = 3;
}
```

---

## 6. Failure Handling Rules

- **GRPC-EVID-005 — Core Crash:**  
  If Core disconnects:
  - AIR MUST buffer evidence in memory
  - On reconnect, resume per ACK semantics

- **GRPC-EVID-006 — AIR Crash:**  
  If AIR restarts:
  - `playout_session_id` MUST change
  - `sequence` MUST reset to 1
  - Core MUST treat as a new session

---

## 7. Durability Requirements (Core Side)

Core MUST:

- Write `.asrun`
- Write `.asrun.jsonl`
- Flush file descriptors

**Only then** advance `acked_sequence`.  
ACK implies durable persistence.

---

## 8. Performance Constraints

- Emission MUST NOT:
  - Block frame emission
  - Stall playout
  - Introduce fence drift

- **AIR MAY:**
  - Emit evidence asynchronously
  - Queue outbound events

- **Core MAY:**
  - Process on dedicated thread
  - Batch `fsync` operations (ACK only after durability)

---

## 9. Required Integration Tests

- Ordered streaming test
- Duplicate event replay test
- Disconnect + resume replay test
- Partial replay after Core restart
- Fence + truncation integration test
- ChannelTerminated handling test

---