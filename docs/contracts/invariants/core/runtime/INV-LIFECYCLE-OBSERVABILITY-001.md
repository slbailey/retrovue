# INV-LIFECYCLE-OBSERVABILITY-001 — Runtime Lifecycle Observability

**Derived from:** LAW-SIMPLICITY, LAW-LIVENESS

## Statement

Runtime lifecycle transitions must emit structured log events at DEBUG level.
Viewer sessions must carry a correlation ID (session_id) traceable end-to-end.

## Prohibited

- Lifecycle transitions with no log event (silent state changes).
- Viewer session handling that does not propagate a correlation ID.
- Free-form log strings for lifecycle events — use structured key=value fields.
- Log events that omit session_id when one exists in scope.

## Required Lifecycle Events

At minimum, the following transitions must be logged:
- channel activation
- first segment produced
- viewer join
- viewer leave
- linger start
- linger expire
- teardown

## Rationale

Without structured, correlation-ID-tagged events, it is impossible to trace a
viewer session end-to-end through logs. Debugging production issues becomes
guesswork. Every refactor touching lifecycle must preserve or extend observability.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_lifecycle_observability_session_manager.py`
  - V8a: first_viewer emits structured DEBUG
  - V8b: last_viewer emits structured DEBUG
  - V8c: reap_expiration emits structured DEBUG
  - No INFO-level lifecycle events

## Added

Phase 8.5d (2026-03-28) — Observability Hardening phase
