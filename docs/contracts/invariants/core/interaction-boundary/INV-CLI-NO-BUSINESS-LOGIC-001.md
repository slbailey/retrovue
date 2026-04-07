# INV-CLI-NO-BUSINESS-LOGIC-001 — CLI commands contain no business logic

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

CLI commands are presentation-layer entry points. If business logic lives in CLI commands, it becomes invisible to API consumers and untestable without CLI harness setup. `LAW-CONTENT-AUTHORITY` requires that domain decisions flow from authoritative domain owners, not from presentation wrappers.

## Guarantee

Every CLI command module MUST be limited to:

1. Argument parsing and validation.
2. IO (stdout, stdin confirmation prompts, progress output).
3. Session/transaction management.
4. Calling a usecase function (domain-internal) or workflow function (cross-domain).

CLI commands MUST NOT contain domain decision logic, state transitions, query construction, or cross-domain coordination.

## Preconditions

- Usecases exist for domain-internal operations.
- Workflows exist for cross-domain coordination.

## Observability

Static analysis of CLI command modules: no direct ORM queries, no domain entity state mutations, no cross-domain imports beyond workflow entry points.

## Deterministic Testability

For each CLI command, verify that the command module imports only from `workflows/` or `usecases/`, plus CLI-specific utilities (confirmation, formatting). Assert that no `db.query()`, `db.add()`, or entity state mutation appears in the command module itself.

## Failure Semantics

**Planning fault.** Business logic in a CLI command means the API cannot expose the same operation, creating a capability gap between interaction models.

## Required Tests

- `pkg/core/tests/contracts/test_interaction_boundary_contract.py` (not yet implemented)

## Enforcement Evidence
TODO
