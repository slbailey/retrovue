# INV-CM-BPP-INJECTION-REQUIRED-001

## Behavioral Guarantee

`BlockPlanProducer.__init__` MUST require `air_bridge: AirBridge` and `supply_controller: SupplyController` as keyword arguments. Phase 5A's transitional fallback (BPP constructing its own helpers when none were injected) is retired: every BPP instance MUST receive its helpers from its caller.

## Authority Model

`ChannelManager` is the sole constructor of `BlockPlanProducer` on the channel-runtime path (per `INV-CM-OWNS-AIR-BRIDGE-001` and `INV-CM-OWNS-SUPPLY-CONTROLLER-001`). Making the kwargs required closes the Phase 5A migration gap and ensures no caller can accidentally construct a BPP with internally-built helpers the CM does not reference.

## Boundary / Constraint

- `BlockPlanProducer.__init__` MUST declare `air_bridge` and `supply_controller` as required keyword arguments (no `None` defaults).
- A BPP constructed without both kwargs MUST raise `TypeError` at construction time.
- BPP's internal code path that previously constructed `AirBridge(...)` or `SupplyController(...)` when `None` was injected MUST be removed.

## Violation

A `BlockPlanProducer` constructor that accepts `air_bridge=None` or `supply_controller=None` as a valid state. Any BPP code path that instantiates `AirBridge` or `SupplyController` internally.

## Derives From

`LAW-MIGRATION-SAFETY`, `INV-CM-OWNS-AIR-BRIDGE-001`, `INV-CM-OWNS-SUPPLY-CONTROLLER-001`

## Required Tests

- `server/tests/contracts/runtime/test_inv_cm_bpp_injection_required.py` — BPP's constructor signature declares both kwargs without defaults; constructing BPP without either kwarg raises `TypeError`; BPP source contains no internal `AirBridge(` or `SupplyController(` construction.

## Enforcement Evidence

TODO
