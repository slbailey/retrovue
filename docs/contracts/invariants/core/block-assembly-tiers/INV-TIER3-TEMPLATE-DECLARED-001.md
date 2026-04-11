# INV-TIER3-TEMPLATE-DECLARED-001 — Tier 3 elements declared in templates only

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring optional presentation is an explicit editorial decision, not an implicit or ad-hoc injection. `LAW-DERIVATION` requires that every segment in the compiled output traces to a declared configuration source. Without this constraint, Tier 3 elements could appear from undocumented code paths, making the schedule non-auditable.

## Guarantee

Tier 3 optional presentation elements MUST be declared in a template's `continuity.optional` section. No Tier 3 element may be injected ad-hoc outside of template configuration. Blocks that reference no template MUST NOT have Tier 3 elements in their `compiled_segments`.

## Preconditions

- Channel YAML has a `templates:` section with template definitions.
- Schedule blocks reference templates via `template: <name>`.

## Observability

A `compiled_segments` entry with a Tier 3 segment type appears on a block that references no template or whose template has no `continuity.optional` entry for that segment type.

## Deterministic Testability

Compile a block with no template reference. Assert `compiled_segments` contains no Tier 3 segment types. Compile a block with a template that has no `continuity.optional`. Assert the same. Compile a block with a template declaring `continuity.optional` entries. Assert only declared types appear.

## Failure Semantics

**Planning fault.** Ad-hoc Tier 3 injection violates editorial traceability.

## Required Tests

- `server/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
