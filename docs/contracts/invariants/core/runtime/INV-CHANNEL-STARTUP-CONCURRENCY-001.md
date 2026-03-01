# INV-CHANNEL-STARTUP-CONCURRENCY-001

## Behavioral Guarantee

Concurrent channel startup operations MUST be bounded by a global concurrency limit. Startup work (manager acquisition + tune_in) MUST execute on a dedicated bounded executor. When the concurrency limit is reached, new startup requests MUST fail fast with HTTP 503 rather than queue unboundedly.

## Authority Model

`ProgramDirector` owns the startup concurrency gate. `_startup_semaphore` enforces the concurrency cap. `_startup_executor` provides the bounded thread pool for all startup work.

## Boundary / Constraint

- `ProgramDirector` MUST have a `_startup_semaphore` (`asyncio.Semaphore`) with a fixed concurrency cap.
- `ProgramDirector._startup_executor` MUST be a `ThreadPoolExecutor` with `max_workers` matching the semaphore cap.
- Both `stream_channel()` and `hls_playlist()` MUST check `_startup_semaphore.locked()` before attempting startup. If the semaphore is at capacity, the handler MUST return HTTP 503 without queuing.
- All startup work (manager acquisition + `tune_in`) MUST execute inside `run_in_executor(self._startup_executor, ...)`.
- The `run_in_executor(None, seg.wait_for_playlist, ...)` call in `hls_playlist()` is NOT startup work and MUST NOT use `_startup_executor`.

## Violation

Startup stampede degrades live streaming. Observable as: unbounded thread creation during concurrent startup, missing semaphore guard in handler source, or startup work executing on the default executor.

## Derives From

`LAW-LIVENESS`, `INV-CHANNEL-STARTUP-NONBLOCKING-001`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_channel_startup_concurrency.py`

## Enforcement Evidence

TODO
