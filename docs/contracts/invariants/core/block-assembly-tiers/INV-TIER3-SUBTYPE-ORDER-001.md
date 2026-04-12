# INV-TIER3-SUBTYPE-ORDER-001 — Tier 3 sub-types follow fixed ordering

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` by ensuring Tier 3 sub-type ordering is deterministic and reproducible. If ordering depended on template declaration order or other non-canonical inputs, the same configuration could produce different segment sequences, violating reproducibility. `LAW-CONTENT-AUTHORITY` requires that broadcast presentation order is an editorial decision with a single canonical answer.

## Guarantee

When multiple Tier 3 sub-types are present within a block, they MUST appear in this fixed order: `channel_ident`, `network_branding`, `coming_up_next`. This ordering is deterministic and MUST NOT vary based on template declaration order or compilation path.

## Preconditions

- The block's template declares multiple Tier 3 element types in `continuity.optional`.

## Observability

Tier 3 segments in `compiled_segments` or the expanded `ScheduledBlock` appear in an order other than `channel_ident` → `network_branding` → `coming_up_next`.

## Deterministic Testability

Compile a block with a template declaring all three Tier 3 sub-types. Assert the ordering in `compiled_segments` is `channel_ident`, `network_branding`, `coming_up_next`. Reverse the declaration order in the template and recompile. Assert the output order is unchanged.

## Failure Semantics

**Planning fault.** Non-deterministic ordering makes compilation unreproducible and breaks segment-level audit trails.

## Required Tests

- `server/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
