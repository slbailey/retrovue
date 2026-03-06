# INV-TIER2-EXPANSION-CANONICAL-001

## Behavioral Guarantee

All Tier-2 writers (daemon, rebuild, any future path) MUST call `expand_editorial_block()` with the **same arguments**, including `asset_library`. No Tier-2 writer may omit the `asset_library` parameter, as this causes silent fallback to static filler instead of real interstitials from the traffic section.

## Authority Model

`expand_editorial_block()` is the single canonical Tier-1 → Tier-2 expansion function. It deserializes the editorial block, then calls `fill_ad_blocks()` with the traffic manager. The traffic manager uses the `asset_library` to select real interstitials (promos, commercials, trailers) from the database. When `asset_library` is `None`, `fill_ad_blocks()` silently falls back to the static filler file — producing incorrect Tier-2 output that does not reflect the channel's traffic configuration.

## Boundary / Constraint

1. Every call site that invokes `expand_editorial_block()` MUST pass an `asset_library` argument constructed from a `DatabaseAssetLibrary` (or equivalent) scoped to the channel.
2. The `asset_library` parameter MUST NOT default to `None` at the call site when a database session is available.
3. `rebuild_tier2()` and `PlaylistBuilderDaemon._extend_to_target()` are the two current Tier-2 writers. Both MUST pass `asset_library`.
4. Static filler fallback is only acceptable when `DatabaseAssetLibrary` construction fails (e.g., no traffic section configured for the channel). The fallback MUST be logged as a warning.

## Violation

`rebuild_tier2()` calls `expand_editorial_block()` without `asset_library`, causing all filler placeholders to be filled with static `filler.mp4` instead of real interstitials. The daemon was previously fixed to pass `asset_library`; the rebuild path was missed. The result: `schedule rebuild --tier 2` produces different output than the daemon for the same editorial block.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_tier2_expansion_canonical.py`

## Enforcement Evidence

TODO
