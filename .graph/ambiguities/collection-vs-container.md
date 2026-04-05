# Ambiguity: Collection vs Container

**Domain:** systems (disambiguation)

## Canonical term vs legacy wording

| Term | Intended meaning | Graph target |
|------|------------------|--------------|
| **Container** | Subdivision of a **Source** used for **discovery** in ingest. | `entity:container` |
| **Collection** | Legacy or informal wording in some docs for a similar **catalog grouping**—**ambiguous**. | Treat as **alias** until doc is aligned; default mapping to `container` for **discovery** context. |

## Critical confusion

**Scheduling `zone`** is **not** an ingest container. Same English word “bucket” in conversation does **not** imply the same entity.

## Resolution rule

- **Ingest / importers / discovery** → `container`.
- **Grid / programming window** → `zone`.

## Relationships

See `relationships/cross-domain.yaml` (`ambiguity:collection-vs-container`).
