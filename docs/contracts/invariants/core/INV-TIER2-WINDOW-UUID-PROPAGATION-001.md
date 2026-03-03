# INV-TIER2-WINDOW-UUID-PROPAGATION-001

**Status:** Binding
**Owner:** Core / PlaylistBuilderDaemon
**Last revised:** 2026-03-03

---

## Statement

When `PlaylistBuilderDaemon` writes a `PlaylistEvent` row from a Tier 1
block that contains `window_uuid`, the daemon MUST set the
`PlaylistEvent.window_uuid` column to the Tier 1 value.

## Rules

1. **Propagation.** If the Tier 1 block dict (`sb_dict`) contains a
   `window_uuid` field, the `PlaylistEvent` row MUST have its
   `window_uuid` column set to that value.

2. **Exact match.** The propagated `window_uuid` string on the
   `PlaylistEvent` row MUST be identical to the `window_uuid` string in
   the source Tier 1 block dict. No transformation, truncation, or
   re-generation is permitted.

3. **Legacy compatibility.** Tier 1 blocks without `window_uuid`
   (legacy channels) produce `PlaylistEvent` rows with
   `window_uuid = NULL`. The daemon MUST NOT fail on missing fields.

4. **Column storage.** `window_uuid` is a top-level nullable UUID
   column on `playlist_events`, indexed for lookup. It is NOT stored
   inside the `segments` JSONB payload.

5. **Provenance only.** This invariant establishes UUID provenance in
   Tier 2 artifacts. It does NOT implement staleness detection,
   rebuild logic, or on-air freeze semantics. Those are deferred to
   `INV-TIER2-SOURCE-WINDOW-UUID-001`.

## Enforcement

Contract test: `pkg/core/tests/contracts/test_tier2_window_uuid_propagation.py`

## Related

- `INV-WINDOW-UUID-EMBEDDED-001` — Tier 1 emission
- `INV-TIER2-SOURCE-WINDOW-UUID-001` — future staleness detection (planned)
- `pkg/core/src/retrovue/runtime/playlist_builder_daemon.py` — `_write_to_txlog()`
