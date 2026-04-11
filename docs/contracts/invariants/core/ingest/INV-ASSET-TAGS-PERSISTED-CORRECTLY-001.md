# INV-ASSET-TAGS-PERSISTED-CORRECTLY-001 — Path-derived tags survive the full pipeline at correct count

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring that every directory component between the root path and the file's parent is emitted as a tag, persisted to the database, preserved across updates, and queryable for pool resolution. Without this guarantee, deep directory structures silently lose tags, causing pool filter mismatches.

## Guarantee

Given a source file path with N directory segments between root and file parent, the system MUST:

1. Generate exactly N tags (one per segment, case-normalized, deduplicated by value)
2. Persist all N tags to the `asset_tags` table
3. Preserve all N tags across subsequent metadata updates (re-enrichment, fingerprint updates)
4. Make all N tags queryable via `expand_tag_match_set` for pool resolution

No tags may be silently dropped, truncated, or overwritten, regardless of path depth.

## Preconditions

- The `FilesystemImporter` is configured with `tag_from_path_segments=True`.
- The path contains at least one directory component between root and file.
- All directory names are distinct after case normalization (duplicates are legitimately deduplicated).

## Observability

`SELECT COUNT(*) FROM asset_tags WHERE asset_uuid = :id` MUST equal the number of unique normalized directory segments for that asset's source path.

## Deterministic Testability

1. Create paths with N=1..5 directory segments.
2. Run `_infer_tags_from_path_segments()`.
3. Assert tag count equals segment count.
4. Simulate persistence via `normalize_tag_set` + `TAG:` namespacing.
5. Assert all namespaced tags are present.
6. Simulate pool resolution via `expand_tag_match_set`.
7. Assert all original segment names are matchable.
8. Simulate metadata update (probed-only persist).
9. Assert tag count unchanged.

## Failure Semantics

**Planning fault.** Missing tags cause pool resolution to exclude assets that should match, producing empty pools and missing presentation segments.

## Required Tests

- `server/tests/contracts/test_inv_asset_tags_persisted_correctly.py`

## Enforcement Evidence

TODO
