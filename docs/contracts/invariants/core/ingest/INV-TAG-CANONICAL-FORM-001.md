# INV-TAG-CANONICAL-FORM-001 — All persisted tags use namespace.value canonical form

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` and `LAW-CONTENT-AUTHORITY` by ensuring tags have a single unambiguous representation in the database. Mixed tag formats (plain strings, colon-prefixed, canonical) cause pool resolution mismatches: the same logical tag appears as multiple distinct strings, breaking filter semantics.

## Guarantee

Every tag persisted in `asset_tags.tag` MUST conform to the canonical form `namespace.value`, where `namespace` is drawn from the controlled vocabulary defined in `tag_canonical_form.md` section B and `value` is a non-empty, normalized, lowercase string.

## Preconditions

- The controlled namespace vocabulary is defined and enforced at ingest time.
- `canonicalize_tag()` is the single entry point for producing canonical tags.

## Observability

`SELECT tag FROM asset_tags WHERE tag NOT LIKE '%.%' OR tag LIKE '%.%.%'` MUST return zero rows. Any row in the result set is a violation.

## Deterministic Testability

1. Create tags in all legacy forms: plain (`hbo`), colon-prefixed (`TAG:hbo`, `NETWORK:cbs`), and canonical (`tag.hbo`).
2. Pass each through `canonicalize_tag()`.
3. Assert every output matches the regex `^[a-z]+\.[a-z0-9][a-z0-9 -]*$`.
4. Assert the namespace portion is in the controlled vocabulary.
5. Simulate persistence and query: assert only canonical-form tags exist in the table.

## Failure Semantics

**Planning fault.** Non-canonical tags in the database cause pool DSL filters to silently miss matching assets, producing incorrect programming pools.

## Required Tests

- `pkg/core/tests/contracts/test_inv_tag_canonical_form.py`

## Enforcement Evidence

- `canonicalize_tag()` in `pkg/core/src/retrovue/domain/tag_normalization.py` enforces canonical form
- CLI `asset update --tags` writes via `canonicalize_tag()` (asset.py)
- Ingest pipeline writes via `canonicalize_tag()` (container_ingest.py)
- Studio web API writes via `canonicalize_tag()` (studio.py)
- Alembic migration `h1i2j3k4l5m6` migrates existing DB tags
