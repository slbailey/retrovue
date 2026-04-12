# Migration Notes: Collection → Container (Historical)

**Status:** Complete. This note is for historical context only.

## What changed

The ingest/catalog entity formerly named **Collection** was renamed to **Container** across the repo. The canonical model is:

**Source → Container → Locator → Asset → Processor Jobs → Processor Runtime**

- **Container** = subdivision of a Source used for discovery (e.g. Plex library, filesystem directory). Table: `containers`; FK column: `container_id`.
- The word **Collection** and identifier **collection_id** no longer appear in application code, CLI, API, or docs except as noted below.

## Where “Collection” still appears

1. **Historical Alembic migrations**  
   Files under `server/alembic/versions/` that created or renamed the `collections` table or `collection_uuid` / `collection_id` columns. These must not be edited; they record schema history.

2. **This note and the refactor inventory**  
   `COLLECTION_TO_CONTAINER_REFACTOR_PHASE0_INVENTORY.md` and this file describe the migration and may use “Collection” when referring to the old name.

3. **Plex API**  
   External metadata may use the tag/key `"Collection"`; that is external surface, not our entity name.

## References

- [TERMINOLOGY_COLLECTION_TO_CONTAINER.md](TERMINOLOGY_COLLECTION_TO_CONTAINER.md) — canonical terminology
- [COLLECTION_TO_CONTAINER_REFACTOR_PHASE0_INVENTORY.md](COLLECTION_TO_CONTAINER_REFACTOR_PHASE0_INVENTORY.md) — phase-by-phase inventory
