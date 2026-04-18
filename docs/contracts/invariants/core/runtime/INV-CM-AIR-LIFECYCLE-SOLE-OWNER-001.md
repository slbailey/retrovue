# INV-CM-AIR-LIFECYCLE-SOLE-OWNER-001

## Behavioral Guarantee

For each channel's AIR subprocess, the `ProcessHandle` and its lifecycle (spawn via `launch_air`, terminate via `terminate_air`) MUST be owned by an `AirBridge` instance in `retrovue.runtime.air_bridge`. Peer callers of `launch_air` / `terminate_air` in production modules are prohibited.

## Authority Model

`AirBridge` is the sole per-channel owner of the AIR subprocess handle, the socket path, the gRPC address, and the reader socket queue. During the ADR-004 migration, `BlockPlanProducer` MUST hold exactly one `AirBridge` instance and MUST delegate all AIR-process concerns to it.

## Boundary / Constraint

- On the channel-runtime path (`retrovue.runtime.*`), `launch_air` and `terminate_air` MUST be called only from `retrovue.runtime.air_bridge`.
- `BlockPlanProducer` MUST NOT hold a `ProcessHandle` attribute directly; the handle MUST live on its `AirBridge` instance.
- `BlockPlanProducer` MUST NOT import `launch_air` or `terminate_air` from `retrovue.usecases.channel_manager_launch`.
- Operator-facing CLI tools (`retrovue.cli.*`) are excluded from this invariant; they MAY launch AIR manually for debugging outside the channel-runtime path.

## Violation

Any runtime-path module other than `retrovue.runtime.air_bridge` that imports or calls `launch_air` / `terminate_air`. Any `BlockPlanProducer` instance that holds a `ProcessHandle` as a direct attribute.

## Derives From

`LAW-MIGRATION-SAFETY`, `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `server/tests/contracts/runtime/test_inv_cm_air_lifecycle_ownership.py` — AirBridge exists with the required surface; BPP imports AirBridge and does not import `launch_air`/`terminate_air`; BPP holds no direct `ProcessHandle` attribute.

## Enforcement Evidence

TODO
