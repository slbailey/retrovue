# INV-TIER2-SOURCE-WINDOW-UUID-001

**Status:** Planned (not yet enforced)
**Owner:** Core / PlaylistBuilderDaemon
**Last revised:** 2026-03-03

---

## Statement

When the PlaylistBuilderDaemon writes a PlaylistEvent row from a
Tier 1 segmented block that contains `window_uuid`, the daemon MUST
propagate the value as `source_window_uuid` into the PlaylistEvent
row's `segments` JSON.

## Rules

1. **Propagation.** If `sb_dict["window_uuid"]` exists in the Tier 1
   block, the PlaylistEvent row written by `_write_to_txlog` includes
   `source_window_uuid` in the row-level JSON or as a column.

2. **Staleness detection.** A future window (not yet on-air) whose
   PlaylistEvent `source_window_uuid` does not match the current
   Tier 1 `window_uuid` for the same time slot is stale and MAY be
   regenerated.

3. **On-air freeze.** A window that is currently airing (block
   `start_utc_ms <= now < end_utc_ms`) MUST NOT be regenerated
   regardless of staleness. Regeneration is deferred until after
   the window ends.

4. **Backward compatibility.** Tier 1 blocks without `window_uuid`
   (legacy channels) produce PlaylistEvent rows without
   `source_window_uuid`. The daemon does not fail on missing fields.

## Status

This invariant is **planned**. The propagation code is not yet
implemented. The contract test is a placeholder that asserts the
future behavior.

## Enforcement

Contract test: `pkg/core/tests/contracts/test_template_graft_contract.py`
(placeholder tests marked `@pytest.mark.skip` until implementation lands)

## Related

- `INV-WINDOW-UUID-EMBEDDED-001` — Tier 1 emission
- `pkg/core/src/retrovue/runtime/playlog_horizon_daemon.py` — Tier 2 writer
