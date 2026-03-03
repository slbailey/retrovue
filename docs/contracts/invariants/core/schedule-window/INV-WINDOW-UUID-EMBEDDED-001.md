# INV-WINDOW-UUID-EMBEDDED-001

**Status:** Binding
**Owner:** Core / Schedule Compiler
**Last revised:** 2026-03-03

---

## Statement

When the schedule compiler produces a Tier 1 day blob for a
template-mode channel, every editorial window's segmented block dicts
MUST include a `window_uuid` field. This field is a UUID4 string
embedded in the JSON, NOT a column on `ProgramLogDay`.

## Rules

1. **Emission.** For each editorial window compiled via template-mode,
   the compiler emits a `window_uuid` (UUID4) into every segmented
   block dict that belongs to that window. All blocks within the same
   window share the same `window_uuid`.

2. **Uniqueness.** No two windows within the same day blob share a
   `window_uuid`. Different broadcast days produce different UUIDs
   for windows at the same clock position.

3. **Stability within compilation.** Within a single compilation pass,
   the `window_uuid` for a given window is stable — all blocks
   belonging to that window carry the same UUID.

4. **No schema change.** `ProgramLogDay` table schema is unchanged.
   `window_uuid` exists only inside `program_log_json["segmented_blocks"][i]`.

5. **Downstream transparency.** The PlaylistBuilderDaemon already loads
   `program_log_json["segmented_blocks"]` as `list[dict]` and iterates
   in-memory. Adding `window_uuid` to each dict requires NO daemon
   changes. The daemon passes through fields it does not consume.

6. **Tier 2 propagation (future).** When Tier 2 (PlaylistBuilderDaemon)
   writes PlaylistEvent rows, it SHOULD propagate `source_window_uuid`
   from the Tier 1 block dict. This enables staleness detection. This
   rule is not enforced until the Tier 2 propagation code is implemented.

## Enforcement

Contract test: `pkg/core/tests/contracts/test_template_graft_contract.py`

## Related

- `docs/domains/SchedulerTier1Authority_v1.0.md` §7 — window_uuid semantics
- `pkg/core/src/retrovue/runtime/dsl_schedule_service.py` — serialization
