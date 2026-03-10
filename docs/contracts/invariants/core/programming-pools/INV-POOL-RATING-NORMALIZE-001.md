# INV-POOL-RATING-NORMALIZE-001 — Pool rating match normalizes shorthand to canonical form

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` by ensuring that pool match evaluation produces identical results regardless of which rating syntax the operator uses. Without normalization, bare-string ratings silently match nothing or raise runtime errors.

## Guarantee

The pool rating filter MUST accept three input forms and normalize them to a canonical `{ include: [...], exclude: [...] }` structure before evaluation:

1. Bare string: `rating: "PG"` → `{ include: ["PG"] }`
2. List of strings: `rating: ["PG", "PG-13"]` → `{ include: ["PG", "PG-13"] }`
3. Dict (canonical): `rating: { include: [...], exclude: [...] }` → passed through unchanged

## Preconditions

- The pool match dict contains a `rating` key with a non-null value.

## Observability

A pool with `rating: "PG"` returns zero assets when the catalog contains PG-rated assets.

## Deterministic Testability

Construct a catalog with assets of known ratings. Evaluate the same pool using all three rating syntaxes. Assert identical result sets.

## Failure Semantics

**Planning fault.** A pool that silently matches nothing due to syntax produces an empty schedule block.

## Required Tests

- `pkg/core/tests/contracts/test_pool_rating_normalize.py`

## Enforcement Evidence

TODO
