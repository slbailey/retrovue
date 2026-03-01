# INV-CHANNEL-STARTUP-NONBLOCKING-001

## Behavioral Guarantee

Channel viewer-join MUST NOT trigger schedule compilation. The viewer-join path MUST only lookup a cached schedule block, compute the JIP offset, and spawn the producer.

## Authority Model

`ProgramDirector._stop_channel_internal()` owns teardown policy. `ProgramDirector._get_or_create_manager()` owns manager lifecycle. `DslScheduleService._build_initial()` owns compilation idempotency.

## Boundary / Constraint

- `_stop_channel_internal()` MUST NOT remove the ChannelManager from `self._managers`. It MUST stop the producer and fanout but preserve the manager and its schedule state.
- `_build_initial()` MUST be idempotent: if schedule blocks are already loaded, it MUST return without recompilation.
- `tune_in()` / `_ensure_producer_running()` MUST be offloaded from the event loop via a bounded `ThreadPoolExecutor` to prevent blocking concurrent playout streams during AIR subprocess spawn.

## Violation

Schedule compilation triggered by viewer join. Observable as `_build_initial()` executing during the `tune_in()` / `_ensure_producer_running()` call path.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_channel_startup_nonblocking.py`

## Enforcement Evidence

TODO
