# Tag Canonical Form Contract

**Status:** Contract
**Domain:** Ingest / Catalog Metadata
**Derived From:** `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

---

## Overview

Tags in RetroVue identify metadata facets on assets: network origin, genre, content rating, editorial flags, and operator-assigned labels. Tags are used by the pool DSL (`select.where.tags`) and the catalog resolver to filter assets into programming pools.

This contract defines the canonical storage form for tags, the migration path from legacy formats, and backward-compatibility semantics during transition.

---

## A. Canonical Form Definition

**A-1.** All tags MUST be stored in `namespace.value` form with a single dot separator.

**A-2.** `namespace` MUST be a lowercase alphabetic string from the controlled vocabulary (see section B).

**A-3.** `value` MUST be a non-empty, lowercase string. Internal whitespace is collapsed to a single space. Leading/trailing whitespace is stripped.

**A-4.** The dot separator (`.`) MUST appear exactly once in a canonical tag. Values containing dots are forbidden.

**A-5.** Examples of canonical tags:
- `tag.hbo` (general label)
- `network.cbs` (network origin)
- `genre.comedy` (content genre)
- `rating.tv-14` (content rating)
- `tag.presentation` (editorial flag)

---

## B. Namespace Vocabulary

The following namespaces are recognized. New namespaces require a contract amendment.

| Namespace  | Semantics                                      |
|------------|-------------------------------------------------|
| `tag`      | General-purpose label (default for plain tags)  |
| `network`  | Network or channel origin of content            |
| `genre`    | Content genre classification                    |
| `rating`   | Content rating (e.g. `tv-14`, `tv-ma`)          |

**B-1.** Unknown or unrecognized namespace prefixes MUST be rejected at ingest time.

**B-2.** Tags with no explicit namespace (plain strings like `hbo`) MUST be migrated to the `tag` namespace: `tag.hbo`.

---

## C. Migration Semantics

**C-1.** Legacy colon-prefixed tags (`TAG:hbo`, `NETWORK:cbs`) MUST be migrated to canonical form by:
1. Stripping the prefix, lowercasing: `TAG:hbo` -> namespace=`tag`, value=`hbo`
2. Mapping legacy prefixes to canonical namespaces:
   - `TAG:` -> `tag.`
   - `NETWORK:` -> `network.`
   - `GENRE:` -> `genre.`
   - `RATING:` -> `rating.`

**C-2.** Plain tags with no prefix (`hbo`, `classic`) MUST be migrated to `tag.hbo`, `tag.classic`.

**C-3.** Migration MUST be idempotent: applying migration to an already-canonical tag MUST return the same tag unchanged. See `INV-TAG-MIGRATION-IDEMPOTENT-001`.

**C-4.** Migration MUST NOT create duplicate tags. If both `TAG:hbo` and `hbo` exist on an asset, they MUST collapse to a single `tag.hbo`.

---

## D. Backward Compatibility During Transition

**D-1.** During the transition period, the pool DSL and catalog resolver MUST accept queries using any of the three historical forms:
- Canonical: `tag.hbo`
- Colon-prefixed: `TAG:hbo`
- Plain: `hbo`

All three MUST match the same underlying canonical tag.

**D-2.** `expand_tag_match_set()` MUST be updated to expand canonical-form tags into all legacy query forms for matching.

**D-3.** The backward-compatibility layer (`expand_tag_match_set`) is transitional. Once all DSL configs and operator workflows use canonical form exclusively, this function will be simplified to identity expansion.

---

## E. Storage Rules

**E-1.** The `asset_tags.tag` column MUST store only canonical-form tags after migration.

**E-2.** New tags created via ingest or operator CLI MUST be written in canonical form. The ingest pipeline and CLI MUST normalize before persistence.

**E-3.** The `tag_normalization.normalize_tag()` function remains the low-level string normalizer. A new `canonicalize_tag()` function MUST handle namespace resolution and canonical form production.

---

## F. Invariants

This contract is enforced by:
- `INV-TAG-CANONICAL-FORM-001` — all persisted tags are in `namespace.value` canonical form
- `INV-TAG-MIGRATION-IDEMPOTENT-001` — tag migration is idempotent and reversible
- `INV-ASSET-TAGS-PERSISTED-CORRECTLY-001` — path-derived tag count survives the pipeline (existing)
