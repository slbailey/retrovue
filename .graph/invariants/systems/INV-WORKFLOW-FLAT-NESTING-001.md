# INV-WORKFLOW-FLAT-NESTING-001

**Domain:** systems

## Plain-language rule

Workflows nest **at most one level**. A workflow may call usecases (domain-internal functions) and may call other workflows, but a called workflow must **not** call another workflow. If a call chain reaches depth > 1, it signals an architecture problem that must be decomposed.

## Why it exists

Deeply nested workflow chains recreate the hidden orchestration layers that the domain separation is designed to prevent. They make failure handling ambiguous (which layer retries? which layer rolls back?), obscure the true coordination surface, and resist static reasoning about cross-domain dependencies.

## What it constrains

- **All modules under `workflows/`**: a workflow function may invoke usecases from any domain and may invoke sibling workflows, but those sibling workflows must not themselves invoke further workflows.
- **Concrete example**: `SourceIngestWorkflow` calls `ContainerIngestWorkflow` (depth 1 — allowed). `ContainerIngestWorkflow` must call only usecases, never another workflow (depth would be 2 — prohibited).

## Failure mode if violated

- Implicit orchestration chains that are impossible to trace from a single entry point.
- Retry/rollback ambiguity across nested coordination layers.
- Symptom: debugging a failure requires reading 3+ workflow files to understand a single operation.

## Enforcement

- Code review: any `import` of a `workflows/` module from within another `workflows/` module at depth > 0 is a candidate violation. The one permitted case is the top-level workflow calling a sibling.
- Static analysis candidate: build an import graph of `workflows/` and flag transitive workflow-to-workflow edges.
