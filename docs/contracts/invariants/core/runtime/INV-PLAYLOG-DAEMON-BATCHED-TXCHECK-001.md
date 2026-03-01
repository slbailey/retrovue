# INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001

## Behavioral Guarantee

PlaylogHorizonDaemon `_extend_to_target()` MUST batch TransmissionLog existence checks per scan-day and yield the GIL after each block fill. The upstream reader thread MUST NOT be starved by a convoy of per-block DB queries.

## Authority Model

PlaylogHorizonDaemon owns the Tier 2 write path. GIL scheduling between the daemon thread and the upstream reader thread is the daemon's responsibility.

## Boundary / Constraint

1. `_extend_to_target()` MUST check TransmissionLog existence for candidate blocks using a single batched query per scan-day (`block_id IN (...)`) — not one query per block.
2. `_extend_to_target()` MUST yield the GIL (e.g. `time.sleep(0.001)`) after each block fill.
3. A `_batch_block_exists_in_txlog(block_ids)` method MUST exist and MUST return `set[str]` of block_ids that already have TransmissionLog entries.

## Violation

Per-block `_block_exists_in_txlog()` calls inside `_extend_to_target()`; absence of GIL yield between block fills; UPSTREAM_LOOP spikes of 150-210ms+ during concurrent daemon evaluation and active streaming.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_playlog_daemon_batched_txcheck.py`

## Enforcement Evidence

TODO
