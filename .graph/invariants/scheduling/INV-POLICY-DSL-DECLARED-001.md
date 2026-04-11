# INV-POLICY-DSL-DECLARED-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-09 (Phase 4 — RETA-111)

## Statement

All scheduling policies MUST originate from channel DSL YAML declarations
compiled via DslScheduleService. No component MUST introduce, modify, or
override scheduling policies outside of DSL compilation.

## Enforcement

- **Contract tests:** `server/tests/contracts/test_scheduling_policies.py`
- **Canonical source:** `docs/contracts/invariants/core/scheduling-policy/INV-POLICY-DSL-DECLARED-001.md`
