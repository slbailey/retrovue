# INV-API-NO-BUSINESS-LOGIC-001 — API routes contain no business logic

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

API route handlers are presentation-layer entry points, symmetric with CLI commands. If business logic lives in route handlers, the same operation cannot be tested without HTTP harness setup and the CLI path diverges from the API path. `LAW-CONTENT-AUTHORITY` requires domain decisions to flow from authoritative domain owners, not from presentation wrappers.

## Guarantee

Every API route handler MUST be limited to:

1. Request validation (Pydantic models, query parameter parsing).
2. Dependency injection resolution (database sessions, auth).
3. Calling a usecase function (domain-internal) or workflow function (cross-domain).
4. Response formatting (serializing results to JSON).
5. HTTP error mapping (domain exceptions → HTTP status codes).

API route handlers MUST NOT contain domain decision logic, state transitions, query construction, or cross-domain coordination.

## Preconditions

- Usecases exist for domain-internal operations.
- Workflows exist for cross-domain coordination.

## Observability

Static analysis of `web/api/` modules: no direct ORM queries beyond dependency injection, no domain entity state mutations, no cross-domain imports beyond workflow or usecase entry points.

## Deterministic Testability

For each API route module, verify that the route handler body contains only: resolve dependencies, call usecase/workflow, format response, map exceptions. Assert that no `db.query()`, `db.add()`, or entity state mutation appears in the handler itself (session management via `Depends` is permitted).

## Failure Semantics

**Planning fault.** Business logic in an API handler means the CLI cannot share the same operation path, creating divergent behavior between interaction models.

## Required Tests

- `server/tests/contracts/test_interaction_boundary_contract.py` (not yet implemented)

## Enforcement Evidence
TODO
