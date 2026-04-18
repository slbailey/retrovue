# INV-CM-OWNS-SUPPLY-CONTROLLER-001

## Behavioral Guarantee

`ChannelManager` MUST construct its per-channel `SupplyController` instance itself and inject it into `BlockPlanProducer` via the producer's constructor. During Phase 5A of the ADR-004 migration, CM holds the per-channel helpers at the CM layer rather than delegating their construction to BPP.

## Authority Model

`ChannelManager._build_producer_for_mode` is the sole construction site for the per-channel `SupplyController`. BPP's constructor accepts `supply_controller` as an injected dependency. `BlockPlanProducer` MUST use the injected `SupplyController` when one is provided; construction of an internal `SupplyController` inside BPP is permitted only as a transitional fallback until Phase 5B.

## Boundary / Constraint

- `ChannelManager._build_producer_for_mode` MUST call `SupplyController(...)` and pass the resulting instance as the `supply_controller` kwarg to `BlockPlanProducer(...)`.
- `BlockPlanProducer.__init__` MUST accept an optional `supply_controller: SupplyController | None` kwarg.
- When `supply_controller` is provided at BPP construction, the injected instance MUST be used as `self._supply`; BPP MUST NOT construct a second `SupplyController` in that case.
- The injected `SupplyController` MUST be constructed with the same `execution_reader` and `on_failure` callback that CM passes to BPP (no divergence between the CM-constructed helper and the BPP-observed dependencies).

## Violation

Any `ChannelManager._build_producer_for_mode` call that does not construct a `SupplyController` at CM level. Any BPP instance constructed with an injected `supply_controller` that nevertheless creates its own internally.

## Derives From

`LAW-MIGRATION-SAFETY`, `LAW-RUNTIME-AUTHORITY`, `INV-AUTHORITY-SINGLE-OWNER-001`

## Required Tests

- `server/tests/contracts/runtime/test_inv_cm_owns_helpers.py` — CM imports SupplyController; `_build_producer_for_mode` constructs one and passes it to BPP; BPP accepts `supply_controller` kwarg and uses the injected instance.

## Enforcement Evidence

TODO
