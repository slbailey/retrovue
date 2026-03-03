# INV-TEMPLATE-GRAFT-DUAL-YAML-001

**Status:** Binding
**Owner:** Core / Schedule Compiler
**Last revised:** 2026-03-03

---

## Statement

The schedule compiler MUST accept both legacy channel YAML syntax and
new template-capable YAML syntax. Both syntaxes MUST produce valid
Tier 1 editorial schedules (ProgramLogDay day blobs) without
regression.

## Definitions

**Legacy syntax:** Channel YAML where `schedule:` entries use block-level
keys (`block`, `movie_marathon`, `movie_block`, `movie_selector`, or
inline `slots`). Templates in legacy mode (if present under `templates:`)
serve only as schedule-day aliases via `{ use: template_name }`.

**New template syntax:** Channel YAML where:
- `templates:` is a mapping keyed by `template_id`, each value containing
  a `segments:` list defining segment composition (source, selection, mode).
- `schedule:` entries use `type: template` with `name: <template_id>` to
  reference segment-composition templates.

## Rules

1. **Coexistence.** A channel YAML may use legacy syntax, new template
   syntax, or both. The compiler MUST NOT reject a valid YAML because
   it contains keys from the other syntax.

2. **Detection.** The compiler detects template-mode entries by the
   presence of `type:` key on schedule entries. Legacy entries lack
   this key and use block-type discriminators (`block`, `movie_marathon`,
   etc.) instead.

3. **Legacy preservation.** Legacy YAML channels that have never used
   `type: template` entries MUST produce identical compilation output
   to prior compiler versions. No behavioral regression is permitted.

4. **Window identity.** Template-mode compilation MUST emit `window_uuid`
   (UUID4 string) per editorial window in the compiled day blob JSON.
   Legacy-mode compilation MAY omit `window_uuid` (backward compatibility).

5. **Rollback.** Removing new template syntax from a channel YAML and
   reverting to legacy syntax MUST produce a valid compilation. No
   persistent state depends on template-mode having been previously used.

6. **No mixed templates mapping.** Within a single `templates:` mapping,
   all entries MUST be consistently one style. If any entry is a
   segment-composition template (contains a `segments:` key), then every
   entry MUST be a segment-composition template. Mixing segment-composition
   entries with legacy day-alias entries in the same `templates:` mapping
   is INVALID. The compiler MUST raise a `CompileError` identifying the
   offending legacy entries.

## Enforcement

Contract test: `pkg/core/tests/contracts/test_template_graft_contract.py`

## Related

- `docs/domains/ProgramTemplateAssembly.md` — template segment model
- `docs/domains/SchedulerTier1Authority_v1.0.md` — window_uuid semantics
- `pkg/core/src/retrovue/runtime/schedule_compiler.py` — production compiler
