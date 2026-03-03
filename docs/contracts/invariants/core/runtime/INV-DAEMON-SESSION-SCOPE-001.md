# INV-DAEMON-SESSION-SCOPE-001

## Behavioral Guarantee

Each `PlaylogHorizonDaemon.evaluate_once()` cycle MUST acquire at most **one** database session for its entire execution. Background daemon threads MUST NOT open multiple sessions per evaluation cycle, as cumulative checkout storms across N concurrent daemons (one per channel) cause QueuePool exhaustion under multi-channel load.

## Authority Model

PlaylogHorizonDaemon owns the Tier 2 write path and is the sole background consumer of database sessions for horizon extension. Connection pool capacity is a shared resource across all daemon threads, HTTP handlers, and auxiliary tasks (loudness measurement, resolver rebuilds). Each daemon MUST minimize its pool footprint to at most one concurrent connection.

## Boundary / Constraint

1. `evaluate_once()` MUST open at most one database session and pass it to all sub-methods that require database access within that cycle.
2. All database helper methods (`_tier2_row_covers_now`, `_get_frontier_utc_ms`, `_load_tier1_blocks`, `_batch_block_exists_in_txlog`, `_fill_ads`, `_write_to_txlog`, `_purge_expired_tier2`) MUST accept an optional `db` parameter. When provided, they MUST reuse it instead of opening a new session.
3. `_extend_to_target()` MUST NOT open any sessions internally; it MUST receive the session from `evaluate_once()`.
4. With N active channels, peak daemon connection demand MUST be at most N (one per daemon thread), not `N * sessions_per_iteration`.

## Violation

Multiple `with session()` calls inside a single `evaluate_once()` cycle; helper methods that unconditionally open their own sessions; QueuePool exhaustion (`TimeoutError: QueuePool limit ... reached`) caused by daemon session checkout storms under multi-channel load (observed with 13 channels at pool_size=20, max_overflow=30).

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_daemon_session_scope.py`

## Enforcement Evidence

TODO
