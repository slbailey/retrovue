# INV-GRPC-GRACEFUL-DRAIN-001

## Behavioral Guarantee

When Core calls `StopBlockPlanSession`, AIR completes the currently executing block and emits final evidence before terminating. Core waits for `SessionEnded` before killing the AIR process.

## Authority Model

Core owns the stop decision. AIR owns drain execution and evidence emission. Neither may skip its responsibility.

## Boundary / Constraint

- After `StopBlockPlanSession`, AIR MUST emit `SessionEnded` event with reason `stopped`.
- Core MUST wait for `SessionEnded` before calling `_terminate_air_process()`.
- If `SessionEnded` is not received within the stop timeout, Core MUST force-terminate (SIGTERM then SIGKILL).
- `StopBlockPlanSession` MUST be idempotent: success on already-stopped sessions, graceful handling of `UNAVAILABLE` on exited processes.

## Violation

Core terminates AIR before `SessionEnded` is received (except on timeout). AIR exits without emitting `SessionEnded`. `StopBlockPlanSession` fails on an already-stopped session.

## Derives From

`LAW-LIVENESS`, `LAW-CLOCK`

## Required Tests

- `server/tests/contracts/grpc/test_grpc_graceful_drain.py`

## Enforcement Evidence
TODO
