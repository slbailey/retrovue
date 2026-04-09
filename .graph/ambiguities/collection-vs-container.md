# Ambiguity: Collection vs Container

**Domain:** systems (disambiguation)

## Canonical term vs legacy wording

| Term | Intended meaning | Graph target |
|------|------------------|--------------|
| **Container** | Subdivision of a **Source** used for **discovery** in ingest. | `entity:container` |
| **Collection** | Legacy or informal wording in some docs for a similar **catalog grouping**—**ambiguous**. | Treat as **alias** until doc is aligned; default mapping to `container` for **discovery** context. |

## Critical confusion

**Scheduling `zone`** was a grid/programming concept (now retired — RETA-88). It was never an ingest container. Same English word "bucket" in conversation does **not** imply the same entity.

## Resolution rule

- **Ingest / importers / discovery** → `container`.
- **Grid / programming window** → formerly `zone` (retired). In the DSL model, time-bounded scheduling regions are expressed as DSL block definitions, not as Zone CRUD entities.

## Relationships

See `relationships/cross-domain.yaml` (`ambiguity:collection-vs-container`).
