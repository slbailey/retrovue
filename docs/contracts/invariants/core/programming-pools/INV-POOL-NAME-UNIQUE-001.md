# INV-POOL-NAME-UNIQUE-001 — Pool names are globally unique

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring pool names are unambiguous references. If two pools share a name, DSL pool references become non-deterministic — the schedule compiler cannot determine which definition to use.

## Guarantee

Every persistent pool definition MUST have a name that is unique across all persistent pool definitions in the system. The database MUST enforce this via a UNIQUE constraint on the pool name column. The workflow MUST reject creation of a pool whose name collides with an existing pool.

## Preconditions

- The pools table exists with a UNIQUE constraint on the `name` column.

## Observability

A uniqueness violation produces a clear error message naming the conflicting pool. Database-level constraint violations are caught and re-raised as domain errors.

## Deterministic Testability

Create a pool with name `"test-pool"`. Attempt to create a second pool with the same name. Assert that the second creation raises a uniqueness error. Assert the original pool is unchanged.

## Failure Semantics

**Planning fault.** Duplicate pool names create ambiguous DSL references, which may cause the wrong assets to air on a channel.

## Required Tests

- `server/tests/contracts/test_pool_management.py`

## Enforcement Evidence

TODO
