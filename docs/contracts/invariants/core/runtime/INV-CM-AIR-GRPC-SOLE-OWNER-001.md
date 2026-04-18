# INV-CM-AIR-GRPC-SOLE-OWNER-001

## Behavioral Guarantee

The gRPC surface between Core and AIR (`feed_blockplan`, `iter_blockplan_events`, and any future `PlayoutSession` RPCs) MUST be invoked only from the `AirBridge` class in `retrovue.runtime.air_bridge`. No other runtime-path module may construct gRPC calls against a per-channel AIR endpoint.

## Authority Model

`AirBridge` holds the `grpc_addr` obtained from `launch_air` and is the sole caller of the generated gRPC stubs. Upstream components (`BlockPlanProducer`, `ChannelManager`) consume AIR events and issue feed requests through `AirBridge` methods (`iter_events`, `feed`), never through direct gRPC-helper imports.

## Boundary / Constraint

- On the channel-runtime path (`retrovue.runtime.*`), `feed_blockplan` and `iter_blockplan_events` MUST be called only from `retrovue.runtime.air_bridge`.
- `AirBridge` MUST expose `iter_events()` and `feed(block)` methods that encapsulate these calls.
- `BlockPlanProducer` MUST NOT import `feed_blockplan` or `iter_blockplan_events` from `retrovue.usecases.channel_manager_launch`.
- `BlockPlanProducer.grpc_addr` access MUST go through `self._air_bridge.grpc_addr`; no direct handling of the address string outside the bridge is permitted.

## Violation

Any runtime-path module other than `retrovue.runtime.air_bridge` that imports or calls `feed_blockplan` / `iter_blockplan_events`. Any code that constructs per-channel gRPC clients against an AIR endpoint outside `AirBridge`.

## Derives From

`LAW-MIGRATION-SAFETY`, `LAW-RUNTIME-AUTHORITY`, `INV-CM-AIR-LIFECYCLE-SOLE-OWNER-001`

## Required Tests

- `server/tests/contracts/runtime/test_inv_cm_air_grpc_ownership.py` — AirBridge exposes `iter_events` and `feed`; BPP no longer imports `feed_blockplan`/`iter_blockplan_events`; no runtime-path module other than `air_bridge.py` imports them.

## Enforcement Evidence

TODO
