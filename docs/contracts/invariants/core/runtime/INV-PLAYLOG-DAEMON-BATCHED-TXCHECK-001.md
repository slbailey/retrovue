# INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001

## Behavioral Guarantee

PlaylistBuilderDaemon `_extend_to_target()` MUST batch PlaylistEvent existence checks per scan-day and yield the GIL after each block fill. The upstream reader thread MUST NOT be starved by a convoy of per-block DB queries.

## Authority Model

PlaylistBuilderDaemon owns the Tier 2 write path. GIL scheduling between the daemon thread and the upstream reader thread is the daemon's responsibility.

## Boundary / Constraint

1. `_extend_to_target()` MUST check PlaylistEvent existence for candidate blocks using a single batched query per scan-day (`block_id IN (...)`) — not one query per block.
2. `_extend_to_target()` MUST yield the GIL (`time.sleep(≥0.010)`) after each block fill. A 1ms yield is insufficient when per-block fill work exceeds the upstream reader's select timeout; 10ms MUST be the minimum.
3. A `_batch_block_exists_in_txlog(block_ids)` method MUST exist and MUST return `set[str]` of block_ids that already have PlaylistEvent entries.
4. The wait between consecutive `_run_loop()` evaluations MUST include a random component with a minimum bound of 1 second and a maximum of `eval_interval_s * 0.25`.

## Violation

Per-block `_block_exists_in_txlog()` calls inside `_extend_to_target()`; absence of GIL yield between block fills; GIL yield below 10ms minimum; fixed-interval evaluation wait with no random component; UPSTREAM_LOOP spikes of 150ms+ during concurrent daemon evaluation and active streaming.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_playlog_daemon_batched_txcheck.py`

## Enforcement Evidence

TODO
