# INV-CM-ORCHESTRATION-SOLE-OWNER-001

## Behavioral Guarantee

`ChannelManager` MUST own the per-channel runtime orchestration logic for BlockPlan playout: producer-start, producer-stop, driver loop, health projection, failure surfacing, and HLS editorial-timebase push. CM's runtime code paths MUST call CM's own orchestration methods rather than delegating through `self.active_producer`.

## Authority Model

Orchestration methods live as private methods on `ChannelManager` (`_producer_start`, `_producer_stop`, `_producer_health`, `_producer_driver_loop`, `_producer_fail`, `_producer_push_hls_timebase`). A narrow public `halt_producer()` API exposes the "stop the AIR subprocess" operation to `ProgramDirector`'s teardown paths without requiring PD to reach through `active_producer`. During the ADR-004 migration, `BlockPlanProducer`'s equivalent methods remain in the module as dead code on the CM path (rollback safety) and are retired in Phase 5C.2.

## Boundary / Constraint

- `ChannelManager._ensure_producer_running` MUST call `self._producer_start(...)`; MUST NOT call `self.active_producer.start(...)`.
- `ChannelManager.stop_channel` MUST call `self._producer_stop(...)`; MUST NOT call `self.active_producer.stop(...)` or `producer.stop(...)` for producer shutdown.
- `ChannelManager.check_health` MUST use `self._producer_health()`; MUST NOT call `self.active_producer.health()`.
- `ProgramDirector` MUST NOT call `manager.active_producer.stop(...)` in shutdown or teardown paths. The narrow CM API `manager.halt_producer(reason=...)` replaces these call sites.
- Informational reads of producer metadata (`mode`, `status`, `get_stream_endpoint()`) on `active_producer` are permitted during the migration; they retire with BPP in Phase 5C.2.

## Violation

Any CM production method that delegates orchestration through `self.active_producer`. Any `ProgramDirector` code that calls `manager.active_producer.stop(...)` directly.

## Derives From

`LAW-MIGRATION-SAFETY`, `LAW-RUNTIME-AUTHORITY`, `INV-AUTHORITY-SINGLE-OWNER-001`, `INV-CM-OWNS-AIR-BRIDGE-001`, `INV-CM-OWNS-SUPPLY-CONTROLLER-001`

## Required Tests

- `server/tests/contracts/runtime/test_inv_cm_orchestration_ownership.py` — CM exposes `_producer_start` / `_producer_stop` / `_producer_health` / `_producer_driver_loop` / `_producer_fail` / `_producer_push_hls_timebase` / `halt_producer`; CM's `_ensure_producer_running` does not call `active_producer.start`; CM's teardown paths do not call `active_producer.stop`; PD does not call `manager.active_producer.stop` anywhere.

## Enforcement Evidence

TODO
