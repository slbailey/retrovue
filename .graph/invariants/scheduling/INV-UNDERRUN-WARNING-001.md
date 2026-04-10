# INV-UNDERRUN-WARNING-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-10 (Phase E — RETA-155)

## Statement

When `content_duration < 0.5 * scheduled_duration`, the compiler MUST emit a structured warning containing block identifier, template name, content duration, slot duration, and utilization percentage. The warning MUST NOT halt compilation.

## Enforcement

- **Contract tests:** `pkg/core/tests/contracts/test_traffic_profiles_conformance.py`
- **Canonical source:** `docs/contracts/traffic_profiles_conformance.md`
