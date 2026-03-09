# INV-TIER2-EXPANSION-CANONICAL-001

## Behavioral Guarantee

All Tier-2 writers (daemon, rebuild, any future path) MUST call `expand_editorial_block()` with the **same arguments**, including `asset_library` and `break_config`. Omitting `asset_library` causes silent fallback to static filler. Omitting `break_config` causes legacy flat-fill instead of structured break expansion.

## Authority Model

`expand_editorial_block()` is the single canonical Tier-1 → Tier-2 expansion function. It deserializes the editorial block, then calls `fill_ad_blocks()` with the traffic manager. The traffic manager uses `asset_library` to select real interstitials and `break_config` to produce structured breaks (bumpers, interstitial pool, station IDs). When either is `None`, the corresponding behavior degrades silently — producing Tier-2 output that does not match the channel's traffic configuration.

## Boundary / Constraint

1. Every call site that invokes `expand_editorial_block()` MUST pass an `asset_library` argument constructed from a `DatabaseAssetLibrary` (or equivalent) scoped to the channel.
2. Every call site that invokes `expand_editorial_block()` MUST pass a `break_config` argument resolved from the channel DSL via `resolve_break_config()`. When the channel has no `traffic.break_config`, `break_config=None` is correct (legacy flat-fill).
3. The `asset_library` and `break_config` parameters MUST NOT default to `None` at the call site when a database session and channel DSL are available.
4. `rebuild_tier2()` and `PlaylistBuilderDaemon._extend_to_target()` are the two current Tier-2 writers. Both MUST pass `asset_library` and `break_config`.
5. Static filler fallback is only acceptable when `DatabaseAssetLibrary` construction fails. The fallback MUST be logged as a warning.

## Violation

A Tier-2 writer that calls `expand_editorial_block()` without `break_config` when the channel DSL declares `traffic.break_config`. The result: `schedule rebuild --tier 2` produces flat-fill breaks while the runtime path (`DslScheduleService`) produces structured breaks for the same editorial block.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_tier2_expansion_canonical.py`

## Enforcement Evidence

TODO
