# INV-TEMPLATE-PRIMARY-SEGMENT-001

**Status:** Binding
**Owner:** Core / Schedule Compiler
**Last revised:** 2026-03-03

---

## Statement

Every template definition used in a `type: template` schedule entry MUST
resolve to exactly one primary content segment. The primary segment's
resolved asset provides the editorial identity (EPG title derivation,
asset_id) for each Tier 1 program block produced by that template.

## Rules

1. **Explicit flag.** If exactly one segment in the template's `segments`
   list has `primary: true`, that segment is the primary content segment.

2. **Multiple explicit.** If more than one segment has `primary: true`,
   the template is INVALID. The compiler MUST raise a `CompileError`
   identifying the template and the count of conflicting markers.

3. **Convention fallback.** If zero segments have `primary: true` and
   exactly one segment has `source.type == "pool"`, that pool segment
   is the primary content segment by convention.

4. **Ambiguous — no pools.** If zero segments have `primary: true` and
   zero segments have `source.type == "pool"`, the template is INVALID.
   The compiler MUST raise a `CompileError` instructing the operator to
   set `primary: true` on exactly one segment.

5. **Ambiguous — multiple pools.** If zero segments have `primary: true`
   and multiple segments have `source.type == "pool"`, the template is
   INVALID. The compiler MUST raise a `CompileError` instructing the
   operator to set `primary: true` on exactly one segment.

6. **Source type restriction.** Segment `source.type` MUST be one of
   `collection` or `pool`. The `primary_content` source type is retired
   and MUST NOT be used. Primary identity is expressed exclusively via
   the `primary: true` segment flag.

## Enforcement

Contract test: `pkg/core/tests/contracts/test_template_graft_contract.py`
(class `TestPrimarySegmentDetection`)

## Related

- `docs/domains/ProgramTemplateAssembly.md` — segment definition model
- `INV-TEMPLATE-GRAFT-DUAL-YAML-001` — dual YAML coexistence
- `pkg/core/src/retrovue/runtime/schedule_compiler.py` — `_compile_template_entry()`
