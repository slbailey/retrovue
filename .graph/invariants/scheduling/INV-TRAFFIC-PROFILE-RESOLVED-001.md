# INV-TRAFFIC-PROFILE-RESOLVED-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-10 (Phase E — RETA-155)

## Statement

Every compiled block that contains break structures MUST have a resolved traffic profile. Resolution follows the precedence: block-level override > template `breaks.traffic_profile` > channel `traffic.default`. An unresolvable profile MUST fail at validation time. TrafficManager MUST NOT infer traffic policy from content type or template name.

## Enforcement

- **Contract tests:** `server/tests/contracts/test_traffic_profiles_conformance.py`
- **Canonical source:** `docs/contracts/traffic_profiles_conformance.md`
