# INV-CM-SUPPLY-STATE-SOLE-WRITER-001

## Behavioral Guarantee

Per-channel supply bookkeeping — the currently-airing block cursor and the last block fed to AIR — MUST be owned exclusively by a `SupplyController` instance in `retrovue.runtime.supply_controller`. No other runtime-path component may mutate or hold these fields directly.

## Authority Model

`SupplyController` is the sole writer of the supply cursor (`current_block`) and feed-deduplication state (`last_fed_block_id`). During the ADR-004 migration, `BlockPlanProducer` MUST hold exactly one `SupplyController` instance and MUST route all cursor/dedup operations through it.

## Boundary / Constraint

- `SupplyController` MUST expose `seed(current_block, next_block)`, `mark_fed(block)`, `is_duplicate_feed(block)`, `reset()`, and read-only `current_block` / `last_fed_block_id` properties.
- `BlockPlanProducer` MUST NOT hold `_current_block` or `_last_fed_block_id` as direct attributes. These fields live on its `SupplyController` instance.
- Any future supply-state additions (feed credits, in-flight tracking, pending-block holds, queue-depth caps) MUST be added to `SupplyController`, not to `BlockPlanProducer` or `ChannelManager` directly.

## Violation

Any runtime-path module other than `retrovue.runtime.supply_controller` that writes to a supply-state field. Any `BlockPlanProducer` instance that holds `_current_block` or `_last_fed_block_id` as direct attributes.

## Derives From

`LAW-MIGRATION-SAFETY`, `LAW-RUNTIME-AUTHORITY`, `INV-AUTHORITY-SINGLE-OWNER-001`

## Required Tests

- `server/tests/contracts/runtime/test_inv_cm_supply_state_ownership.py` — SupplyController exists with the required surface; BPP holds a SupplyController and does not carry `_current_block` or `_last_fed_block_id` directly.

## Enforcement Evidence

TODO
