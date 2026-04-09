# INV-POLICY-VIOLATION-STRUCTURED-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-09 (Phase 4 — RETA-111)

## Statement

Every PolicyViolation MUST carry: `invariant_id` (string, non-empty),
`rule_type` (one of `"repeat_window"`, `"frequency_cap"`, `"tag_eligibility"`,
`"duration_gate"`), `message` (human-readable, non-empty), and `details`
(dict with at minimum `asset_id`).

## Enforcement

- **Contract tests:** `pkg/core/tests/contracts/test_scheduling_policies.py`
- **Canonical source:** `docs/contracts/invariants/core/scheduling-policy/INV-POLICY-VIOLATION-STRUCTURED-001.md`
