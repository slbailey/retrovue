# Terminology: Container (Canonical)

## Purpose

The ingest and catalog pipeline is defined as **Source → Container → Locator → Asset → Processor Jobs → Processor Runtime**. **Container** is the canonical term for the subdivision of a Source used for discovery (e.g. Plex library, filesystem directory).

---

## Canonical model

- **Source** — content source (e.g. Plex server, filesystem).
- **Container** — subdivision of a Source that holds discoverable media (locators). One container has 1..n assets. Table: `containers`; FK: `container_id`.
- **Locator** — logical/media identity; leads to **Asset**.
- **Asset** — media file record; may trigger **Processor Jobs** and **Processor Runtime**.
- **Collection** *(reserved)* — future concept: a logical grouping of assets from **1..n containers** (e.g. “Horror” = 2 movies from Container A + 2 from Container B). Do not use “collection” for the source-subdivision entity; that is **Container**.

---

## Where “Collection” may still appear

1. **Historical Alembic migrations**  
   Files under `server/alembic/versions/` that reference `collections`, `collection_uuid`, or `collection_id` must **not** be edited. They record schema history; the live schema is `containers` / `container_id`.

2. **Historical migration notes**  
   [MIGRATION_NOTES_COLLECTION_TO_CONTAINER.md](MIGRATION_NOTES_COLLECTION_TO_CONTAINER.md) and the refactor inventory may use “Collection” when describing the rename.

3. **External API (e.g. Plex)**  
   The key/tag `"Collection"` from external systems may remain in integration code; the internal entity is **Container**.

4. **Future “Collection” concept**  
   When we implement logical groupings of assets across multiple containers, that entity will be named **Collection**. Until then, any reference to “a bunch of assets from one place” is a **Container** (source subdivision).

---

## Policy

- **Code, CLI, API, and docs** use **Container** and `container_id` for the source-subdivision entity. Do not use “collection” for that entity.
- Reserve **Collection** for the future concept: grouping of assets from 1..n containers.
- **CI:** The terminology guard fails if `Collection` or `collection_id` appears outside allowlisted paths (historical migrations and the guard’s own docstrings).

---

## References

- [COLLECTION_TO_CONTAINER_REFACTOR_PHASE0_INVENTORY.md](COLLECTION_TO_CONTAINER_REFACTOR_PHASE0_INVENTORY.md) — full inventory and rename table  
- [ContainerDiscoveryContract_v0.1.md](../core/ContainerDiscoveryContract_v0.1.md) — contract definitions  
- [PIPELINE_MIGRATION_ARCHITECTURE.md](PIPELINE_MIGRATION_ARCHITECTURE.md) — pipeline flow and component responsibilities  
