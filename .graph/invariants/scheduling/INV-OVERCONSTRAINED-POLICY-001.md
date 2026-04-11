# INV-OVERCONSTRAINED-POLICY-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-10 (Phase E — RETA-155)

## Statement

Every template MUST declare or inherit an `overconstrained` policy (`bleed` or `reject`). When no explicit value is set, `bleed` is the default. The compiler MUST evaluate the declared policy when `content_duration + presentation_duration > scheduled_duration`. No silent truncation, no silent gap insertion, and no implicit fallback behavior is permitted.

## Enforcement

- **Contract tests:** `server/tests/contracts/test_traffic_profiles_conformance.py`
- **Canonical source:** `docs/contracts/traffic_profiles_conformance.md`
