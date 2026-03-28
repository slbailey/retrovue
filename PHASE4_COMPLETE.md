# PHASE4_COMPLETE.md — Diagnostics Isolation

**Date:** 2026-03-28  
**Branch:** refactor/simplify-single-authority-l3

## What Was Done

### 4a — Audit
StreamingDiagnostics class found DEAD in both Python runtime and AIR C++.
No callers, no references. Safe to delete.

### 4b — Delete StreamingDiagnostics
Removed StreamingDiagnostics class, diagnostics field from StreamingSchema,
and defaults.yaml section. 26 lines removed. Tests held at 330 passing.

### 4c — Extract HlsDiagnosticsState
Extracted `_hls_diag_*` state fields from ProgramDirector into a
`HlsDiagnosticsState` dataclass. PD holds one instance and delegates.
No behavior change — makes the boundary explicit and testable.

### 4d — Expiry Mechanism Audit + Contract Hardening
**Finding:** Auto-expiry via `time.monotonic()` is the SOLE expiry mechanism.

Evidence:
- `HlsDiagnosticsState.is_active()` checks `mode_until.get(channel_id, 0.0) > now`
- `HlsDiagnosticsState.trigger()` only ever extends via `max(prev, now + duration_s)`
- Zero manual reset/clear/disable paths exist anywhere in the codebase
- `mode_until` entries are never deleted or zeroed

**Contract added:** `test_hls_diagnostics_state_auto_expiry_is_sole_mechanism`
- Asserts no method zeros/deletes mode_until entries
- Asserts the only write is the max() extend in trigger()
- This test will fail if anyone adds a manual disable path

**Pre-existing test fixed:** `test_program_director_has_conditional_hls_diag_mode_controls`
- Was checking PD source for `_hls_diag_mode_until` (moved to HlsDiagnosticsState in 4c)
- Updated to check: PD delegate methods exist + HlsDiagnosticsState has mode_until authority
- Converted pre-existing failure into a GREEN test (63 pre-existing failures → 62)

## Invariant Established

INV-HLS-DIAG-AUTO-EXPIRY-001: HLS diagnostic mode expires only by
monotonic clock. There is no manual disable path. `mode_until` entries
are only written once per trigger (extend-only via max()).

## Test Result
- Before change: 63 contract failures (pre-existing), 2737 passing
- After change: 62 contract failures (one pre-existing fixed), 2739 passing
- Net: +2 tests, -1 failure
