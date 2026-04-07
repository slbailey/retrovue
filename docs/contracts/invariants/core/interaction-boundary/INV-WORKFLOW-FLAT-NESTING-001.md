# INV-WORKFLOW-FLAT-NESTING-001 — Workflows nest at most one level

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Workflows coordinate operations across domain boundaries. If workflows call other workflows arbitrarily, the coordination graph becomes opaque and traceability degrades. `LAW-DERIVATION` requires that artifact chains remain traceable; deeply nested workflow calls obscure the chain. A flat nesting constraint keeps coordination auditable.

## Guarantee

A workflow function MUST NOT call another workflow that itself calls a workflow. The maximum call depth from a workflow entry point to domain usecases is: workflow → usecase. The maximum depth when one workflow delegates to another is: workflow → workflow → usecase. Three-level nesting (workflow → workflow → workflow) MUST NOT occur.

## Preconditions

- The `retrovue/workflows/` package contains all cross-domain coordination.
- Domain-internal operations live in `retrovue/usecases/`.

## Observability

Static call-graph analysis of `workflows/` modules. Any import chain from a workflow module through another workflow module to a third workflow module is a violation.

## Deterministic Testability

Enumerate all modules in `workflows/`. For each, extract the set of imported workflow modules. Assert that no imported workflow module itself imports from `workflows/` (beyond shared types/results). This is a static analysis test requiring no runtime setup.

## Failure Semantics

**Planning fault.** Three-level workflow nesting indicates an architecture problem: either a missing usecase or a misplaced domain boundary. The fix is to restructure, not to add depth.

## Required Tests

- `pkg/core/tests/contracts/test_interaction_boundary_contract.py` (not yet implemented)

## Enforcement Evidence
TODO
