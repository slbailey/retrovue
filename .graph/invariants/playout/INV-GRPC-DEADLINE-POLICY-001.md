# INV-GRPC-DEADLINE-POLICY-001

**Domain:** playout (Core↔AIR coordination)

## Plain-language rule

Every gRPC RPC from Core to AIR on the PlayoutControl service **MUST** carry a deadline. No RPC is issued without a timeout.

## Why it exists

Prevents indefinite hangs when AIR is unresponsive. Ensures Core can detect and react to AIR failures within bounded time.

## What it constrains

- **Services:** `playout-session` (Core gRPC client), `air-playout-engine` (AIR gRPC server).
- Streaming RPCs (`SubscribeBlockEvents`) are exempt; connection loss detected by gRPC keepalive.
- Deadline-exceeded responses MUST NOT trigger automatic retry within PlayoutSession.

## Failure mode if violated

Core hangs indefinitely on AIR RPC; channel lifecycle stalls; no error surfaced to operator.
