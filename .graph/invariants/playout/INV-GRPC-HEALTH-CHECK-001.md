# INV-GRPC-HEALTH-CHECK-001

**Domain:** playout (Core↔AIR coordination)

## Plain-language rule

AIR exposes `grpc.health.v1.Health` for readiness probing. Core uses health checks (not `GetVersion`) to determine when AIR is ready to accept PlayoutControl RPCs after spawn.

## Why it exists

Standardized readiness probing replaces ad-hoc version polling. Enables proper startup gating and future integration with orchestration health checks.

## What it constrains

- **Services:** `air-playout-engine` (health service implementation), `playout-session` (readiness probing).
- AIR reports `SERVING` when ready, `NOT_SERVING` when draining.
- Readiness timeout configurable via `playout.grpc.readiness_timeout_seconds` (default 10.0s).

## Failure mode if violated

Core sends RPCs before AIR is ready; startup race conditions; no standard health signal for orchestration tooling.
