# Asset Identity Migration and Backfill

This document defines how existing Asset rows are migrated from the **current identity** model to the **contract identity** model so that Phase 2 reconciliation (compare by locator, fingerprint, outcome) can run without stalling. Without an explicit backfill and constraint, reconciliation cannot reliably match discovered locators to existing assets or enforce (source_id, container_id, locator) uniqueness.

**Reference:** `AssetMediaIdentityContract_v0.1.md`, `CatalogReconciliationContract_v0.1.md`, `PIPELINE_MIGRATION_ARCHITECTURE.md`, `PIPELINE_MIGRATION_TASK_PLAN.md`.

---

## Current vs Contract Identity

| Aspect | Current (pre–Phase 2) | Contract (target) |
|--------|------------------------|-------------------|
| **Identity tuple** | (collection_uuid, canonical_key_hash) and (collection_uuid, uri) | (source_id, container_id, locator) |
| **Stored on Asset** | collection_uuid, canonical_key_hash, uri | Need: source_id; container_id = collection_uuid; locator = uri |
| **Uniqueness** | UniqueConstraint(collection_uuid, canonical_key_hash), UniqueConstraint(collection_uuid, uri) | (source_id, container_id, locator) MUST be unique across all Media/Asset records |

Today, Asset has `collection_uuid` (the container FK), `canonical_key_hash`, and `uri`. The container entity has `source_id`. The contract identity is (source_id, container_id, locator). So we map:

- **locator** = `asset.uri` (already on Asset; the unique address of the media within the container)
- **container_id** = `asset.collection_uuid` (contract: container; DB column name unchanged until final phase)
- **source_id** = from the container row referenced by `asset.collection_uuid`; not yet on Asset

To support the contract and reconciliation “compare by locator” step without joining to the container table every time, and to add a contract-aligned unique constraint, we add **source_id** to Asset and backfill it from the container table (DB table name remains `collections` until the final migration).

---

## Migration Rule

```
locator      = asset.uri
container_id = asset.collection_uuid   (contract: container_id; DB column name unchanged until final phase)
source_id    = container.source_id     (where container.uuid = asset.collection_uuid; DB table name still "collections")
```

Implementation:

1. **Add column:** `assets.source_id` (UUID, nullable initially, FK to `sources.id` or the same type as `collections.source_id`).
2. **Backfill:** For every Asset, set `source_id` from its container (DB table name `collections` until final migration):
   ```sql
   UPDATE assets
   SET source_id = collections.source_id
   FROM collections
   WHERE collections.uuid = assets.collection_uuid;
   ```
3. **Make non-null:** After backfill, alter column to NOT NULL (and add FK if desired).
4. **Add unique constraint:** Enforce contract uniqueness with a unique constraint on (source_id, container_id, locator). Using existing column names: (source_id, collection_uuid, uri). Name the constraint e.g. `uq_assets_source_container_locator`.
5. **Verify no collisions before adding constraint:** Run a query to detect duplicate (source_id, collection_uuid, uri) (e.g. group by and count > 1). If any exist, resolve them (e.g. operator merge, or deduplicate by canonical_key_hash) before adding the constraint. Document the resolution policy.

---

## Backfill and Constraint Order (Phase 2)

Execute in this order so Phase 2 does not stall:

1. **Add source_id column** (nullable, no FK yet if you want to backfill first).
2. **Backfill source_id** from Collection (UPDATE … FROM collections …).
3. **Verify no collisions:** `SELECT source_id, collection_uuid, uri, COUNT(*) FROM assets WHERE is_deleted = false GROUP BY source_id, collection_uuid, uri HAVING COUNT(*) > 1`. If rows returned, fix duplicates (see below) before proceeding.
4. **Make source_id NOT NULL** (and add FK to sources if applicable).
5. **Add unique constraint** `UNIQUE (source_id, collection_uuid, uri)` — optionally only for non-deleted assets if the schema uses soft-delete and you allow same locator to reappear after delete; otherwise global uniqueness. Contract says “(source_id, container_id, locator) MUST be unique across all Media records”; for Asset-as-media, that implies unique per (source_id, collection_uuid, uri) for active assets. Document whether the constraint is partial (WHERE is_deleted = false) or total.
6. **Use in reconciliation:** Load catalog state for the container can key by locator (uri) or by (source_id, container_id, locator). New assets created in Phase 2 must set source_id from the container's source_id so they satisfy the constraint.

---

## Resolving Collisions

If the collision check finds duplicate (source_id, collection_uuid, uri):

- **Cause:** Same logical file ingested twice under the same collection (e.g. bug or duplicate path). Contract forbids duplicate locators within a container.
- **Options:** (a) Merge: keep one asset, mark the other deleted or merge metadata. (b) Deduplicate by canonical_key_hash and keep the older or newer row. (c) Operator review: list collisions and let operator choose which to keep or merge.
- Document the chosen policy in this file or in the runbook. Do not add the unique constraint until collisions are resolved.

---

## New Assets (Post–Backfill)

When creating new assets in the create path (Phase 2 and later), set:

- `source_id` = container's source_id (from the container being ingested)
- `collection_uuid` = container.uuid (contract: container_id; DB column name unchanged until final phase)
- `uri` = the locator string produced by discovery (locator)

So new rows automatically satisfy the contract identity and the unique constraint.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Add `assets.source_id` (nullable). |
| 2 | Backfill: `UPDATE assets SET source_id = (SELECT source_id FROM collections WHERE collections.uuid = assets.collection_uuid)`. |
| 3 | Verify no duplicate (source_id, collection_uuid, uri); resolve any collisions. |
| 4 | Alter source_id to NOT NULL; add FK if desired. |
| 5 | Add unique constraint `uq_assets_source_container_locator` on (source_id, collection_uuid, uri). |
| 6 | In create path, set source_id (and uri, collection_uuid) for new assets so reconciliation and contract are satisfied. |

This unblocks Phase 2: reconciliation can load catalog state by locator (or by (source_id, container_id, locator)), compare with discovered locators, and enforce the contract’s uniqueness guarantee.
