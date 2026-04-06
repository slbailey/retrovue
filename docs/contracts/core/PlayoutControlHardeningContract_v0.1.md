# PlayoutControl gRPC Hardening Contract — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Core ↔ AIR Coordination)  
**Authority Level:** Coordination (Wire Protocol)  
**Governs:** Core gRPC Client → AIR PlayoutControl Service  
**Out of Scope:** Evidence transport (see GrpcEvidenceInterfaceContract), frame-level execution (AIR internal), channel lifecycle (ProgramDirector)

---

## 1. Purpose

This contract defines the operational hardening semantics for the PlayoutControl gRPC service between Core and AIR. It specifies timeout policy, backpressure signaling, graceful shutdown drain, and health probing at the wire level.

The PlayoutControl happy path and basic failure recovery already function. This contract adds production-grade resilience guarantees.

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

When a deadline is exceeded:
- Core MUST treat the RPC as failed.
- Core MUST NOT retry automatically. Retry decisions are made by the caller (ChannelManager/ProgramDirector).
- Core MUST log the timeout as a structured event with channel_id and RPC name.

---

## 4. Backpressure Signaling

### GRPC-HARD-003 — Feed Backpressure Protocol

AIR maintains a bounded block queue (default depth: 2). When the queue is full:

- `FeedBlockPlan` MUST return `QUEUE_FULL` result code (not an error).
- Core MUST distinguish `QUEUE_FULL` from transport errors.
- Core MUST NOT treat `QUEUE_FULL` as a failure; it is a capacity signal.
- Core MUST wait for a `BlockStarted` event (indicating queue slot freed) before retrying feed.

### GRPC-HARD-004 — Feed Flow Control

Block feeding is event-driven, not polling-driven:
- Core feeds blocks in response to `BlockStarted` or `BlockCompleted` events.
- Core MUST NOT poll `FeedBlockPlan` in a loop.
- If a feed returns `QUEUE_FULL`, Core MUST wait for the next boundary event before retrying.

---

## 5. Graceful Shutdown Protocol

### GRPC-HARD-005 — Drain Semantics

When Core calls `StopBlockPlanSession`:
- AIR MUST complete the currently executing block (drain).
- AIR MUST emit final evidence (BlockFence, ChannelTerminated) before terminating.
- AIR MUST emit `SessionEnded` event with reason `stopped`.
- Core MUST wait for `SessionEnded` before terminating the AIR process.

If `SessionEnded` is not received within the stop timeout (default 5.0s):
- Core MUST terminate the AIR process (SIGTERM, then SIGKILL after 5s).
- Core MUST log forced termination as a structured warning.

### GRPC-HARD-006 — Stop Idempotency

`StopBlockPlanSession` MUST be idempotent:
- If AIR has already stopped (no active session), the RPC MUST return success.
- If AIR is unreachable (process already exited), Core MUST handle `UNAVAILABLE` gracefully without logging an error.

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

## 7. Invariants

| Invariant ID | Guarantee |
|-------------|-----------|
| `INV-GRPC-DEADLINE-POLICY-001` | Every PlayoutControl RPC carries a gRPC deadline |
| `INV-GRPC-FEED-BACKPRESSURE-001` | Feed backpressure uses QUEUE_FULL, not errors; Core waits for boundary events |
| `INV-GRPC-GRACEFUL-DRAIN-001` | Stop drains current block and emits final evidence before termination |
| `INV-GRPC-HEALTH-CHECK-001` | AIR exposes grpc.health.v1.Health for readiness probing |
