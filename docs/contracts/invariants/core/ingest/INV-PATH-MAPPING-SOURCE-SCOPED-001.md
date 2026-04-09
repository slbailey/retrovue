# INV-PATH-MAPPING-SOURCE-SCOPED-001 — Path mappings are source-level configuration

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring path mappings are declared at the source level and inherited by containers automatically. Without source-scoped mappings, each container requires manual path configuration, creating operator burden and silent ingest failures when new containers are discovered.

## Guarantee

Each source declares zero or more path mappings (`source_path` / `retrovue_path`). When a container is ingested, it MUST inherit the source's path mappings automatically. Per-container overrides are optional; source-level inheritance is the default. Path mapping field names MUST be generic (`source_path` / `retrovue_path`), not provider-specific.

## Preconditions

- The source exists and has been registered.
- Path mappings use the canonical field names (`source_path`, `retrovue_path`).

## Observability

A container that fails path resolution despite its source having valid mappings is a violation. Detection occurs when `AssetPathResolver` cannot resolve an asset path that falls within a source-level mapping prefix.

## Deterministic Testability

1. Create a source with a path mapping `{ source_path: "/media/movies", retrovue_path: "/mnt/nfs/movies" }`.
2. Create a container under that source with no container-level overrides.
3. Assert the container inherits the source-level mapping during resolution.
4. Add a container-level override for a different prefix. Assert the override takes precedence for that prefix while the source-level mapping still applies to other prefixes.
5. Assert that provider-specific field names (`plex_path`, `local_path`) are rejected at the schema level.

## Failure Semantics

**Planning fault.** A container that does not inherit source-level mappings produces assets with unresolvable paths, causing silent ingest failures or playout errors at runtime.

## Required Tests

- `pkg/core/tests/contracts/ingest/test_inv_path_mapping_source_scoped.py`

## Enforcement Evidence

TODO
