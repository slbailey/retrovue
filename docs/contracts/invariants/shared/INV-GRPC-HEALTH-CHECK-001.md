# INV-GRPC-HEALTH-CHECK-001

## Behavioral Guarantee

AIR exposes `grpc.health.v1.Health` for readiness probing. Core uses health checks during startup to determine when AIR is ready to accept PlayoutControl RPCs.

## Authority Model

AIR owns health state reporting. Core owns readiness probing policy and timeout.

## Boundary / Constraint

- AIR MUST implement `grpc.health.v1.Health` with service name `retrovue.playout.v1.PlayoutControl`.
- AIR MUST report `SERVING` when ready to accept RPCs, `NOT_SERVING` when draining or shutting down.
- Core MUST use health probing (not `GetVersion`) for startup readiness detection.
- Readiness timeout MUST be configurable via `playout.grpc.readiness_timeout_seconds` (default: 10.0s).

## Violation

AIR does not implement the health service. Core uses a non-standard readiness probe. AIR reports `SERVING` while unable to accept RPCs.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `server/tests/contracts/grpc/test_grpc_health_check.py`

## Enforcement Evidence

- **AIR**: `runtime/src/main.cpp` — `grpc::EnableDefaultHealthCheckService(true)` enables the built-in gRPC health service; `SetServingStatus("retrovue.playout.v1.PlayoutControl", true)` called after `BuildAndStart()`.
- **Core**: `server/src/retrovue/runtime/playout_session.py` — `_wait_for_grpc()` uses `grpc_health.v1.health_pb2_grpc.HealthStub.Check()` with service name `retrovue.playout.v1.PlayoutControl` for readiness probing. Timeout configurable via `readiness_timeout_seconds` constructor parameter (maps to `playout.grpc.readiness_timeout_seconds`).
- **Tests**: `server/tests/contracts/grpc/test_grpc_health_check.py` — source-inspection tests verify health check imports and configurable timeout presence.
