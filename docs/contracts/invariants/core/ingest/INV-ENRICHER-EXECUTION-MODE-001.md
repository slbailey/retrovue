# INV-ENRICHER-EXECUTION-MODE-001 — Enrichers declare execution mode; system triggers

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring the system — not the enricher — controls when enrichment occurs. Without declared execution modes, enrichers self-trigger at arbitrary times, creating unpredictable load, race conditions with scheduling, and untraceable execution paths.

## Guarantee

Every enricher MUST declare exactly one execution mode: `immediate`, `lazy_on_access`, or `background`. The system is responsible for honoring the declared mode — enrichers MUST NOT self-trigger. Scheduling MUST NOT block on enricher completion. `lazy_on_access` enrichers MUST complete fast enough to not delay schedule compilation. Adding a new execution mode requires a contract change — enrichers MUST NOT invent ad-hoc triggers.

## Preconditions

- The enricher is registered in the enricher pipeline with a declared execution mode.

## Observability

An enricher that executes outside its declared mode is a violation. Detection occurs by comparing the execution context (caller, timing) against the enricher's declared mode.

## Deterministic Testability

1. Register an enricher with mode `immediate`. Assert it executes when the asset enters `ready` state.
2. Register an enricher with mode `background`. Assert it executes via the worker queue, not inline.
3. Assert that no enricher class lacks an execution mode declaration.
4. Assert that schedule compilation does not block waiting for any enricher to complete.
5. Attempt to register an enricher with an undeclared mode (e.g. `"on_demand"`). Assert rejection.

## Failure Semantics

**Planning fault.** An enricher that self-triggers or executes in the wrong mode creates untraceable execution paths and potential scheduling delays.

## Required Tests

- `pkg/core/tests/contracts/ingest/test_inv_enricher_execution_mode.py`

## Enforcement Evidence

TODO
