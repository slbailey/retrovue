# Pool Management — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

---

## Overview

Pool management covers the persistent lifecycle of named pool definitions: create, list, inspect, and assign. This contract extends the existing Programming Pools contract (which governs inline DSL pool definitions and compile-time evaluation) by introducing pools as **persistent named entities** in the database.

Persistent pools are reusable across channels without duplicating match criteria in each DSL file. Inline `match:` blocks in the DSL continue to work alongside named pool references. The two forms are equivalent at scheduling time — the resolver treats both as match criteria to evaluate against the catalog.

This contract does not redefine pool evaluation semantics, match criteria fields, or resolver behavior. Those concerns are governed by the Programming Pools contract and `INV-POOL-RESOLUTION-VISIBILITY-001`.

### Authority Boundary

This contract owns:
- Pool entity definition (persistent named definition)
- CRUD operations: create, list, inspect, assign
- Name uniqueness constraint
- Inspect semantics (resolve against catalog, return diagnostics)
- Assignment semantics (advisory pool→channel association)
- Backward compatibility guarantee (inline `match:` coexists with named pools)
- CLI delegation rule (pool CLI commands delegate to workflow)

This contract does NOT own:
- Match criteria field definitions (Programming Pools contract)
- Pool evaluation at compile time (Programming Pools contract)
- Per-filter exclusion diagnostics structure (`INV-POOL-RESOLUTION-VISIBILITY-001`)
- DSL syntax or pool declaration format (scheduling DSL contract)
- Asset catalog or resolver internals (asset resolution)

---

## Domain Objects

### Pool

Persistent named pool definition stored in the database.

| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| `id` | UUID | PK | Internal identifier. |
| `name` | str | UNIQUE, NOT NULL | DSL-referenceable pool name. |
| `description` | str | nullable | Operator-facing description of pool intent. |
| `match_criteria` | JSON | NOT NULL | Match criteria dict (same schema as inline `match:` blocks). |
| `created_at` | datetime | NOT NULL | Creation timestamp. |
| `updated_at` | datetime | NOT NULL | Last modification timestamp. |

### PoolAssignment

Advisory association between a pool and a channel. Records which pools an operator intends to use on which channels. This is informational only — it does not affect scheduling behavior. The DSL remains the sole authority for what airs.

| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| `id` | UUID | PK | Internal identifier. |
| `pool_id` | UUID | FK → Pool | The pool being assigned. |
| `channel_id` | UUID | FK → Channel | The target channel. |
| `created_at` | datetime | NOT NULL | Assignment timestamp. |

### PoolInspectResult

Returned by the inspect operation. Not persisted.

| Field | Type | Description |
|-------|------|-------------|
| `pool_name` | str | Name of the inspected pool. |
| `match_criteria` | dict | The pool's match criteria. |
| `matched_asset_ids` | list[str] | Asset IDs matching the criteria. |
| `matched_count` | int | Number of matched assets. |
| `diagnostics` | PoolDiagnostics | Per-filter exclusion breakdown (`INV-POOL-RESOLUTION-VISIBILITY-001`). |

---

## Public API (Workflow)

All pool management operations are exposed through `server/src/retrovue/workflows/pool_management.py`. CLI commands delegate to this workflow per `INV-CLI-NO-BUSINESS-LOGIC-001`.

### `create_pool`

```
create_pool(
    db: Session,
    name: str,
    match_criteria: dict,
    description: str | None = None,
) -> Pool
```

Creates a persistent named pool definition. The name MUST be unique (`INV-POOL-NAME-UNIQUE-001`). Match criteria are stored as-is; they are not evaluated at creation time. Returns the created Pool entity.

### `list_pools`

```
list_pools(db: Session) -> list[Pool]
```

Returns all persistent pool definitions, ordered by name.

### `inspect_pool`

```
inspect_pool(
    db: Session,
    resolver: CatalogAssetResolver,
    pool_name: str,
) -> PoolInspectResult
```

Resolves the named pool's match criteria against the current catalog using `query_with_diagnostics`. Returns matched assets and a `PoolDiagnostics` breakdown. This operation is read-only and does not mutate pool or catalog state.

### `assign_pool`

```
assign_pool(
    db: Session,
    pool_name: str,
    channel_name: str,
) -> PoolAssignment
```

Creates an advisory association between a pool and a channel. The assignment is informational — it does not affect scheduling. Both the pool and channel MUST exist.

---

## CLI Surface

| Command | Workflow Call | Description |
|---------|-------------|-------------|
| `retrovue pool create <name> --type episode --tags horror --rating R` | `create_pool()` | Create a named pool definition. |
| `retrovue pool list` | `list_pools()` | List all pool definitions. |
| `retrovue pool inspect <name>` | `inspect_pool()` | Resolve pool against catalog, show matched assets + diagnostics. |
| `retrovue pool assign <pool-name> <channel>` | `assign_pool()` | Record pool→channel association. |

All CLI commands MUST delegate to the workflow. No business logic in the CLI layer (`INV-POOL-CLI-DELEGATES-001`).

---

## Backward Compatibility

Inline `match:` blocks in channel DSL YAML MUST continue to work alongside named pool references. The schedule compiler MUST support both forms:

```yaml
# Named pool reference (new)
episode_selector:
  pool: cheers_s6
  mode: sequential

# Inline match (existing, still valid)
pools:
  cheers_s6:
    match:
      type: episode
      series_title: Cheers
      season: 6
```

When a DSL references a pool name that exists as both an inline definition and a persistent named definition, the inline definition takes precedence (local scope wins). This prevents remote mutation from altering a compiled schedule unexpectedly.

---

## Inspect Semantics

The inspect command evaluates pool match criteria against the current catalog state and returns:
1. The list of matched asset IDs.
2. A `PoolDiagnostics` breakdown per `INV-POOL-RESOLUTION-VISIBILITY-001`.

Inspect is a point-in-time snapshot. The catalog may change between inspect and scheduling. Inspect does not cache or persist results.

When a pool matches zero assets, the inspect output MUST include the full `PoolDiagnostics` with per-filter exclusion counts and per-asset exclusion reasons. This is the primary debugging tool for operators.

---

## Assignment Semantics

Pool assignments are advisory metadata. They record operator intent ("I plan to use this pool on this channel") but do not affect scheduling behavior. The DSL remains the sole editorial authority per `LAW-CONTENT-AUTHORITY`.

Assignments serve two purposes:
1. Operator tracking: which pools feed which channels.
2. Future tooling: pool assignment reports, dependency graphs.

Deleting a pool that has assignments MUST cascade-delete the assignments.

---

## Invariants

### INV-POOL-NAME-UNIQUE-001 — Pool names are globally unique

Pool names MUST be unique across all persistent pool definitions. Attempting to create a pool with a name that already exists MUST raise a uniqueness violation error. This is enforced at the database level (UNIQUE constraint) and at the workflow level (pre-check with clear error message).

### INV-POOL-CLI-DELEGATES-001 — Pool CLI commands contain no business logic

Pool CLI commands MUST delegate all domain logic to the pool management workflow. This is an instance of `INV-CLI-NO-BUSINESS-LOGIC-001`. CLI commands are limited to argument parsing, IO, session management, and calling the workflow.

### INV-POOL-RESOLUTION-VISIBILITY-001 — Pool inspection produces diagnostics

The inspect operation MUST return `PoolDiagnostics` per the existing invariant. This contract confirms that the inspect command is the CLI surface for invoking `query_with_diagnostics`. No changes to the invariant definition are required.

---

## Edge Cases

| Condition | Result |
|-----------|--------|
| Create pool with duplicate name | Error: uniqueness violation (`INV-POOL-NAME-UNIQUE-001`). |
| Inspect pool with zero matches | Returns empty matched list + full `PoolDiagnostics`. |
| Inspect pool when catalog is empty | Returns zero matches, `total_considered = 0`. |
| Assign pool to non-existent channel | Error: channel not found. |
| Assign same pool to same channel twice | Error or idempotent (implementation choice). |
| Delete pool with assignments | Cascade-delete assignments. |
| DSL references a named pool that does not exist | Compiler error at schedule compilation time (not this contract's concern). |
| Inline pool and persistent pool share name | Inline definition takes precedence in DSL scope. |

---

## Required Tests

- `server/tests/contracts/test_pool_management.py`

---

## Enforcement Evidence

TODO
