# PlayoutControl gRPC Hardening Contract — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Core ↔ AIR Coordination)  
**Authority Level:** Coordination (Wire Protocol)  
**Governs:** Core gRPC Client → AIR PlayoutControl Service  
**Out of Scope:** Evidence transport (see GrpcEvidenceInterfaceContract), frame-level execution (AIR internal), channel lifecycle (ProgramDirector)  
**Extends:** `GrpcEvidenceInterfaceContract_v0.1.md` (E.1) — this contract adds operational hardening to the existing gRPC interface without modifying E.1 semantics. All evidence transport behavior (GRPC-EVID-001 through GRPC-EVID-012) remains governed by E.1.

---

## 1. Purpose

This contract extends the E.1 gRPC interface contract (`GrpcEvidenceInterfaceContract_v0.1.md`) with production-grade operational hardening for the PlayoutControl service. It specifies timeout policy, backpressure signaling, graceful shutdown drain, and health probing at the wire level.

No clause in this contract overrides or modifies E.1 evidence transport semantics. Where behavior intersects (e.g., shutdown evidence emission), E.1 governs evidence ordering and durability; this contract governs the operational envelope (deadlines, drain sequencing, health signaling).

---

## 2. Authority Model

### Core (Client)

- **Lifecycle authority.** Owns when channels start and stop.
- **Timeout authority.** Sets gRPC deadlines on all RPCs.
- **Drain initiator.** Signals AIR to drain before termination.

### AIR (Server)

- **Execution authority.** Owns frame-level playout correctness.
- **Backpressure authority.** Owns queue depth and QUEUE_FULL signaling.
- **Health authority.** Reports its own readiness state.

### No shared authority

- Core MUST NOT bypass QUEUE_FULL to force-feed blocks.
- AIR MUST NOT ignore drain requests or delay health status reporting.

---

## 3. Timeout Policy

### GRPC-HARD-001 — Deadline Policy

Every RPC from Core to AIR MUST carry a gRPC deadline. No RPC may be issued without a timeout.

| RPC | Default Deadline | Config Key |
|-----|-----------------|------------|
| `GetVersion` | 2.0s | `playout.grpc.version_timeout_seconds` |
| `AttachStream` | 5.0s | `playout.grpc.attach_timeout_seconds` |
| `StartBlockPlanSession` | 10.0s | `playout.grpc.start_timeout_seconds` |
| `FeedBlockPlan` | 5.0s | `playout.grpc.feed_timeout_seconds` |
| `StopBlockPlanSession` | 5.0s | `playout.grpc.stop_timeout_seconds` |
| `SubscribeBlockEvents` | None (streaming) | N/A |

Streaming RPCs (`SubscribeBlockEvents`) do not carry per-call deadlines. Connection loss is detected by gRPC keepalive.

### GRPC-HARD-002 — Deadline Exceeded Behavior

**Trigger:** gRPC returns `DEADLINE_EXCEEDED` (status code 4).

**Response:**
- Core MUST treat the RPC as failed.
- Core MUST NOT retry automatically. Retry decisions are made by the caller (ChannelManager/ProgramDirector).
- Core MUST log the timeout as a structured event with `channel_id`, RPC name, and configured deadline value.

**Failure outcome:** The PlayoutSession reports the failure to its caller. No state mutation occurs on the Core side for a timed-out RPC.

---

## 4. Backpressure Signaling

### GRPC-HARD-003 — Feed Backpressure Protocol

**Trigger:** Core calls `FeedBlockPlan` when AIR's bounded block queue (default depth: 2) is at capacity.

**Response:** AIR returns the RPC with `success=false` and `queue_full=true`, result code `QUEUE_FULL`. The gRPC status is `OK` (status code 0) — this is an application-level capacity signal, not a transport error.

**Core behavior:**
- Core MUST map `queue_full=true` to `FeedResult.QUEUE_FULL` (not `FeedResult.ERROR`).
- Core MUST NOT treat `QUEUE_FULL` as a failure; it is a capacity signal.
- Core MUST wait for a `BlockStarted` event (indicating queue slot freed) before retrying feed.
- Core MUST NOT log `QUEUE_FULL` at error level (warning or debug only).

**Failure outcome:** If `FeedBlockPlan` returns a gRPC transport error (`UNAVAILABLE`, `DEADLINE_EXCEEDED`, etc.), Core maps this to `FeedResult.ERROR`. Transport errors indicate AIR health problems, not capacity.

### GRPC-HARD-004 — Feed Flow Control

Block feeding is event-driven, not polling-driven:
- Core feeds blocks in response to `BlockStarted` or `BlockCompleted` events.
- Core MUST NOT poll `FeedBlockPlan` in a loop.
- If a feed returns `QUEUE_FULL`, Core MUST wait for the next boundary event before retrying.

---

## 5. Graceful Shutdown Protocol

### GRPC-HARD-005 — Drain Semantics

**Trigger:** Core calls `StopBlockPlanSession` with a reason string.

**AIR response (ordered):**
1. AIR completes the currently executing block (drain).
2. AIR emits final evidence per E.1 contract (BlockFence, ChannelTerminated via `ExecutionEvidenceService`).
3. AIR emits `SessionEnded` event on the `SubscribeBlockEvents` stream with reason `stopped`.
4. The RPC returns `success=true` with `final_ct_ms` and `blocks_executed`.

**Core response (ordered):**
1. Core receives `SessionEnded` on the event thread.
2. Core calls `_terminate_air_process()` (SIGTERM, wait 5s, then SIGKILL).
3. Core fires `on_session_end` callback.

**Timeout fallback:** If `SessionEnded` is not received within the stop timeout (default 5.0s), Core MUST force-terminate the AIR process and MUST log forced termination as a structured warning.

**Known gap:** AIR does not currently transition health status to `NOT_SERVING` during drain. Core cannot distinguish graceful shutdown from abrupt termination via health probing alone. This is tracked for follow-up and does not block current acceptance.

### GRPC-HARD-006 — Stop Idempotency

**Trigger:** Core calls `StopBlockPlanSession` when AIR has already stopped or is unreachable.

**Response:**
- If AIR has no active session: RPC returns `success=true` (idempotent).
- If AIR is unreachable (`UNAVAILABLE`, status code 14): Core handles gracefully without logging an error (debug level only).
- If AIR process has already exited: Core skips the RPC and proceeds to cleanup.

**Ordering guarantee:** `stop()` may be called multiple times without side effects. The first call initiates drain; subsequent calls are no-ops.

---

## 6. Health Probing

### GRPC-HARD-007 — Health Check Service

AIR MUST implement `grpc.health.v1.Health` with service-level granularity:
- Service name `retrovue.playout.v1.PlayoutControl` reports readiness for playout RPCs.
- Empty service name (`""`) reports overall server health.

Health states:
- `SERVING` — AIR is ready to accept RPCs.
- `NOT_SERVING` — AIR is draining or shutting down.

### GRPC-HARD-008 — Readiness Probing

Core uses health probing during startup:
- After spawning AIR, Core polls health instead of `GetVersion` for readiness.
- Readiness timeout is configurable via `playout.grpc.readiness_timeout_seconds` (default: 10.0s).
- If AIR does not become `SERVING` within the readiness timeout, Core treats startup as failed.

---

## 7. Completion Criteria

This contract is considered complete when:
1. All behavior is formally specified in this document (clauses GRPC-HARD-001 through GRPC-HARD-008).
2. Implementation in `playout_session.py` (Core) and `playout_service.h` / `main.cpp` (AIR) conforms to all clauses.
3. Each invariant (INV-GRPC-*-001) has passing contract tests.
4. Behavior is testable via E.2 failure scenarios (existing tests in `test_grpc_failure_modes.py` cover deadline-exceeded and partition cases).
5. E.1 evidence transport semantics (GRPC-EVID-001 through GRPC-EVID-012) are not violated by any hardening change.

**Known gap (non-blocking):** AIR does not emit `NOT_SERVING` during graceful drain (GRPC-HARD-007). Lifecycle signaling (SERVING → NOT_SERVING → termination) is tracked for follow-up.

---

## 8. Invariants

| Invariant ID | Guarantee |
|-------------|-----------|
| `INV-GRPC-DEADLINE-POLICY-001` | Every PlayoutControl RPC carries a gRPC deadline |
| `INV-GRPC-FEED-BACKPRESSURE-001` | Feed backpressure uses QUEUE_FULL, not errors; Core waits for boundary events |
| `INV-GRPC-GRACEFUL-DRAIN-001` | Stop drains current block and emits final evidence before termination |
| `INV-GRPC-HEALTH-CHECK-001` | AIR exposes grpc.health.v1.Health for readiness probing |
