# INV-POLICY-IDEMPOTENT-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-09 (Phase 4 — RETA-111)

## Statement

Given identical `candidate_assets`, `policy`, and `context`,
`evaluate_scheduling_policies` MUST return identical eligible assets and
identical violations. Evaluation MUST NOT depend on call order, global state,
random sources, or wall-clock time not passed via `context`.

## Enforcement

- **Contract tests:** `server/tests/contracts/test_scheduling_policies.py`
- **Canonical source:** `docs/contracts/invariants/core/scheduling-policy/INV-POLICY-IDEMPOTENT-001.md`
