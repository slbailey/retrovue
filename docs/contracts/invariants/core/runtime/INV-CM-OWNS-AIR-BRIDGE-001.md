# INV-CM-OWNS-AIR-BRIDGE-001

## Behavioral Guarantee

`ChannelManager` MUST construct its per-channel `AirBridge` instance itself and inject it into `BlockPlanProducer` via the producer's constructor. During Phase 5A of the ADR-004 migration, CM holds the per-channel helpers at the CM layer rather than delegating their construction to BPP.

## Authority Model

`ChannelManager._build_producer_for_mode` is the sole construction site for the per-channel `AirBridge`. BPP's constructor accepts `air_bridge` as an injected dependency. `BlockPlanProducer` MUST use the injected `AirBridge` when one is provided; construction of an internal `AirBridge` inside BPP is permitted only as a transitional fallback until Phase 5B.

## Boundary / Constraint

- `ChannelManager._build_producer_for_mode` MUST call `AirBridge(...)` and pass the resulting instance as the `air_bridge` kwarg to `BlockPlanProducer(...)`.
- `BlockPlanProducer.__init__` MUST accept an optional `air_bridge: AirBridge | None` kwarg.
- When `air_bridge` is provided at BPP construction, the injected instance MUST be used as `self._air_bridge`; BPP MUST NOT construct a second `AirBridge` in that case.
- The injected `AirBridge` MUST be the same object that CM holds in its internal state (identity check, not equality).

## Violation

Any `ChannelManager._build_producer_for_mode` call that does not construct an `AirBridge` at CM level. Any BPP instance constructed with an injected `air_bridge` that nevertheless creates its own bridge internally.

## Derives From

`LAW-MIGRATION-SAFETY`, `LAW-RUNTIME-AUTHORITY`, `INV-AUTHORITY-SINGLE-OWNER-001`

## Required Tests

- `server/tests/contracts/runtime/test_inv_cm_owns_helpers.py` — CM imports AirBridge; `_build_producer_for_mode` constructs one and passes it to BPP; BPP accepts `air_bridge` kwarg and uses the injected instance.

## Enforcement Evidence

TODO
