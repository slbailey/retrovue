# INV-FEED-MISS-POLICY-001

## Behavioral Guarantee

Feed-ahead miss detection MUST record and classify late feeds but MUST NOT alter control flow. AIR handles planning gaps via PADDED_GAP (black + silence). A late feed is an annotation, not a correction.

## Authority Model

`BlockPlanProducer._feed_ahead()` is the sole feed-ahead decision-maker. Miss classification and annotation are owned by BlockPlanProducer.

## Boundary / Constraint

Two classifications exist:

1. **TRUE MISS (MISS_READY_BY):** The feed-ahead logic first noticed the block AFTER `block.start_utc_ms`. The block was not prepared on time. `_ready_by_miss_count` MUST be incremented. A WARNING log with `lateness_ms` MUST be emitted. An as-run annotation MUST be recorded via `_record_miss_annotation()`.

2. **LATE DECISION:** The feed-ahead logic noticed the block in the `[ready_by, start)` window but could not feed due to credits or queue state. The block was prepared on time but delivered late. `_late_decision_count` MUST be incremented. An INFO log with `decision_lag_ms` MUST be emitted.

When `_resolve_plan_for_block()` returns `None` (horizon exhaustion), the feed-ahead loop MUST log `INV-BLOCKPLAN-HORIZON-MISS` at WARNING level and return without feeding. It MUST NOT crash, reorder, or attempt alternative resolution.

In all three cases, feed ordering MUST be preserved. No miss or late feed may cause block reordering.

## Violation

- A true miss that does not increment `_ready_by_miss_count`.
- A true miss that does not emit a WARNING log.
- A late feed that alters block ordering or control flow.
- A horizon miss that crashes or attempts re-resolution beyond retry-next-tick.
- Feed-ahead logic that silently drops a miss without annotation.

## Derives From

`LAW-LIVENESS`, `LAW-CLOCK`

## Required Tests

- `pkg/core/tests/contracts/test_blockplan_feeding_contracts.py` — INV-FEED-EXACTLY-ONCE, INV-FEED-NO-MID-BLOCK, INV-FEED-TWO-BLOCK-WINDOW
- `pkg/core/tests/contracts/runtime/test_inv_exec_no_structure.py::TestMissingScheduleDataPolicy` — horizon miss returns None, no crash
- `pkg/core/tests/contracts/runtime/test_feed_ahead_clock_authority.py` — miss/due decisions driven by injected clock only

## Enforcement Evidence

TODO
