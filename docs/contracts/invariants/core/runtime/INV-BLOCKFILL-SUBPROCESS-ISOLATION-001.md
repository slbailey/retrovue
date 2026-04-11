# INV-BLOCKFILL-SUBPROCESS-ISOLATION-001

## Behavioral Guarantee

PlaylistBuilderDaemon `_extend_to_target()` MUST execute block expansion (`expand_editorial_block` and traffic fill) in a subprocess. When the subprocess exits, all memory allocated during expansion MUST be returned to the OS, preventing allocator fragmentation from accumulating in the long-running daemon process.

## Authority Model

PlaylistBuilderDaemon owns the playlog plan write path. `_extend_to_target()` is the sole forward-fill entry point for the daemon's block expansion pipeline.

## Boundary / Constraint

1. `_extend_to_target()` MUST NOT call `expand_editorial_block` in the daemon's own process. Block expansion MUST execute in a child process.
2. The child process MUST exit after completing each batch of block expansions. `ProcessPoolExecutor` with `max_tasks_per_child=1` or equivalent MUST be used to guarantee process-per-batch isolation.
3. Results MUST cross the process boundary as serialized dicts (picklable). The parent process deserializes results and writes to the database.
4. The subprocess MUST complete within a bounded timeout. If the subprocess exceeds the deadline, the parent MUST log the failure and continue without crashing.
5. All existing `_extend_to_target()` behavioral contracts (`INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001` Rule 2 GIL yield, `INV-DAEMON-SESSION-SCOPE-001` session scope) MUST be preserved in the parent process.

## Violation

`expand_editorial_block` called in the daemon process during `_extend_to_target()`; subprocess reuse across batches (no process-per-batch guarantee); subprocess timeout with no error handling; silent data loss when subprocess fails.

## Required Tests

- `server/tests/contracts/runtime/test_inv_blockfill_subprocess_isolation.py`

## Enforcement Evidence

TODO
