# INV-POLICY-PURE-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-09 (Phase 4 — RETA-111)

## Statement

`evaluate_scheduling_policies` and all per-rule evaluation functions MUST NOT
mutate any input, perform I/O, database queries, or filesystem access. All
state needed for evaluation MUST be passed as arguments.

## Enforcement

- **Contract tests:** `pkg/core/tests/contracts/test_scheduling_policies.py`
- **Canonical source:** `docs/contracts/invariants/core/scheduling-policy/INV-POLICY-PURE-001.md`
