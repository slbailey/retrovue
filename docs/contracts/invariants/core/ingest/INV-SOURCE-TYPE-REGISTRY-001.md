# INV-SOURCE-TYPE-REGISTRY-001 — Source type dispatch through a single registry

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring source types are dispatched through a single registry. Without a registry, source type handling scatters across CLI commands, API handlers, and workflows, creating undocumented type-specific branches that diverge silently.

## Guarantee

All source type dispatch MUST route through a single `SOURCE_TYPE_REGISTRY` that maps type identifiers to importer implementations. A source type that is not present in the registry MUST be rejected at registration time with `INV-SOURCE-TYPE-REGISTRY-001-VIOLATED`. No CLI command, API handler, or workflow may contain inline type-dispatch logic (e.g. `if source_type == "plex"`) outside the registry lookup.

## Preconditions

- The registry is initialized before any source operation.
- Each registered type maps to exactly one importer class.

## Observability

A source registration attempt with an unknown type emits a structured log event with `source_type_rejected`, the attempted type, and the list of registered types.

## Deterministic Testability

1. Register a source with a known type (e.g. `plex`). Assert the registry resolves to the correct importer.
2. Register a source with an unknown type (e.g. `betamax`). Assert rejection with `INV-SOURCE-TYPE-REGISTRY-001-VIOLATED`.
3. Assert the registry contains no duplicate type keys.
4. Assert no production module outside the registry contains inline `if source_type ==` dispatch logic.

## Failure Semantics

**Planning fault.** An unregistered source type that bypasses the registry produces undefined behavior during container discovery and ingest.

## Required Tests

- `pkg/core/tests/contracts/ingest/test_inv_source_type_registry.py`

## Enforcement Evidence

TODO
