# INV-POOL-CLI-DELEGATES-001 — Pool CLI commands contain no business logic

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Instance of `INV-CLI-NO-BUSINESS-LOGIC-001` applied to pool management. Protects `LAW-CONTENT-AUTHORITY` by ensuring pool domain logic lives in the workflow layer, not the CLI layer. If pool business logic lives in CLI commands, it becomes invisible to API consumers and untestable without CLI harness.

## Guarantee

Every pool CLI command (`pool create`, `pool list`, `pool inspect`, `pool assign`) MUST delegate all domain logic to `workflows/pool_management.py`. CLI command modules MUST be limited to argument parsing, IO formatting, session management, and calling the workflow.

Pool CLI commands MUST NOT contain: ORM queries, entity creation or mutation, match criteria evaluation, catalog resolution, or cross-domain coordination.

## Preconditions

- Pool management workflow exists at `workflows/pool_management.py`.
- Workflow functions cover all pool operations.

## Observability

Static analysis of pool CLI command modules: no direct ORM queries, no domain entity state mutations, no imports beyond workflow entry points and CLI utilities.

## Deterministic Testability

For each pool CLI command, verify that the command module imports only from `workflows/` (plus CLI-specific utilities). Assert that no `db.query()`, `db.add()`, or entity state mutation appears in the command module.

## Failure Semantics

**Planning fault.** Business logic in a CLI command means the API cannot expose the same operation, creating a capability gap between interaction models.

## Required Tests

- `server/tests/contracts/test_pool_management.py`

## Enforcement Evidence

TODO
