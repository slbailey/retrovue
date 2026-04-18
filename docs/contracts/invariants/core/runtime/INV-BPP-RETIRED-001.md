# INV-BPP-RETIRED-001

## Behavioral Guarantee

`BlockPlanProducer` and the `retrovue.runtime.block_plan_producer` module are retired. `ChannelManager` owns all per-channel runtime concerns that previously lived on BPP: orchestration (Phase 5C.1), AirBridge + SupplyController composition (Phases 5A/5B), and the Producer-base informational surface (Phase 5C.2). No production code imports `BlockPlanProducer` or invokes it as a class; no runtime-path component holds a BPP instance as `active_producer`.

## Authority Model

`ChannelManager` is the authoritative per-channel runtime broker. It owns its AIR subprocess (via `AirBridge`), its supply state (via `SupplyController`), and its own lifecycle-state fields. External consumers query CM directly: `manager.is_producer_active()`, `manager._producer_health()`, `manager.runtime_state.*`.

## Boundary / Constraint

- `retrovue.runtime.block_plan_producer` MUST NOT exist as an importable module in the server source tree.
- `retrovue.runtime.channel_manager` MUST NOT re-export `BlockPlanProducer`.
- `ChannelManager` MUST NOT hold an `active_producer` attribute of type `BlockPlanProducer`. Any residual `active_producer` field MUST be either removed or repurposed as a lightweight state projection (not a BPP instance).
- `_build_producer_for_mode` MUST NOT construct a `BlockPlanProducer`. Helper construction (`AirBridge`, `SupplyController`) moves inline to `_ensure_producer_running` or equivalent.
- `ProgramDirector` MUST NOT read `manager.active_producer` as a BPP reference. Producer-activity checks use `manager.is_producer_active()`.

## Violation

Any import of `retrovue.runtime.block_plan_producer` in production code. Any BPP class construction. Any `manager.active_producer.X()` call that relies on BPP-specific methods.

## Derives From

`LAW-MIGRATION-SAFETY`, `LAW-RUNTIME-AUTHORITY`, `INV-CM-ORCHESTRATION-SOLE-OWNER-001`

## Required Tests

- `server/tests/contracts/runtime/test_inv_bpp_retired.py` — verifies `block_plan_producer` module is not importable; `ChannelManager` exposes `is_producer_active()`; no production runtime file imports `BlockPlanProducer`.

## Retires

- `INV-PLAYOUT-MODULE-EXTRACTION-001` (subject retires)
- `INV-MIGRATION-BPP-SURFACE-STABLE-001` (time-scoped to ADR-004; retires with BPP)
- `INV-MIGRATION-DELETION-ORDERING-001` (fires during this phase's merge, then retires)
- `INV-MIGRATION-INVARIANT-COVERAGE-001` (time-scoped; retires)
- `INV-CM-BPP-INJECTION-REQUIRED-001` (Phase 5B transition guard; subject retires)

## Enforcement Evidence

TODO
