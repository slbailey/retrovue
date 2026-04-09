# INV-POLICY-LAYERED-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-09 (Phase 4 — RETA-111)

## Statement

Scheduling policies MUST NOT override, relax, or re-evaluate the core
eligibility gate (`LAW-ELIGIBILITY`). An asset that does not satisfy
`LAW-ELIGIBILITY` MUST NOT reach policy evaluation.

## Enforcement

- **Contract tests:** `pkg/core/tests/contracts/test_scheduling_policies.py`
- **Canonical source:** `docs/contracts/invariants/core/scheduling-policy/INV-POLICY-LAYERED-001.md`
