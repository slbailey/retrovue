# INV-GRPC-DEADLINE-POLICY-001

## Behavioral Guarantee

Every gRPC RPC from Core to AIR on the PlayoutControl service MUST carry a deadline. No RPC is issued without a timeout.

## Authority Model

Core (gRPC client) owns deadline configuration. Deadlines are resolved from channel configuration with documented defaults.

## Boundary / Constraint

- Every unary RPC (`GetVersion`, `AttachStream`, `StartBlockPlanSession`, `FeedBlockPlan`, `StopBlockPlanSession`) MUST pass a `timeout` parameter.
- Streaming RPCs (`SubscribeBlockEvents`) are exempt from per-call deadlines.
- When a deadline is exceeded, Core MUST treat the RPC as failed and MUST NOT retry automatically.
- Deadline values MUST be configurable via `playout.grpc.*_timeout_seconds` config keys.

## Violation

An RPC is issued without a timeout parameter. A deadline-exceeded response triggers automatic retry within PlayoutSession.

## Derives From

`LAW-LIVENESS`, `LAW-CLOCK`

## Required Tests

- `server/tests/contracts/grpc/test_grpc_deadline_policy.py`

## Enforcement Evidence
TODO
