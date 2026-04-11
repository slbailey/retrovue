# INV-TAG-MIGRATION-IDEMPOTENT-001 — Tag migration is idempotent and reversible

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring the tag migration function is safe to re-run on any tag — including tags that have already been migrated. Without idempotency, re-running migration on canonical tags would corrupt them (e.g. `tag.hbo` becoming `tag.tag.hbo`). Without reversibility, data recovery from a failed migration is impossible.

## Guarantee

The `canonicalize_tag()` function MUST be idempotent: `canonicalize_tag(canonicalize_tag(x)) == canonicalize_tag(x)` for all valid input strings `x`.

The original form of every tag MUST be recoverable from its canonical form and the known namespace vocabulary: given `tag.hbo`, the original could have been `hbo`, `TAG:hbo`, or `tag.hbo` — all mapping to the same canonical output.

## Preconditions

- Input is a non-empty string after whitespace stripping.
- The namespace vocabulary is stable and known at migration time.

## Observability

Run `canonicalize_tag()` twice on every distinct `asset_tags.tag` value. If `canonicalize_tag(tag) != tag` for any row, the row was not fully migrated. If `canonicalize_tag(canonicalize_tag(tag)) != canonicalize_tag(tag)` for any row, the function is not idempotent — this is a violation.

## Deterministic Testability

1. For each legacy format (plain, colon-prefixed, canonical), apply `canonicalize_tag()`.
2. Assert output matches canonical form.
3. Apply `canonicalize_tag()` again to the output.
4. Assert output is unchanged (idempotency).
5. For duplicate inputs (`TAG:hbo` and `hbo`), assert both produce the same canonical output (`tag.hbo`).

## Failure Semantics

**Planning fault.** A non-idempotent migration function corrupts tags on re-run, causing silent data loss and pool resolution failures that are difficult to diagnose after the fact.

## Required Tests

- `server/tests/contracts/test_inv_tag_canonical_form.py` (class `TestMigrationC`)

## Enforcement Evidence

- `canonicalize_tag()` in `server/src/retrovue/domain/tag_normalization.py` — handles all three input forms and is idempotent by construction
- Test class `TestMigrationC` in `test_inv_tag_canonical_form.py` — parametric idempotency checks
