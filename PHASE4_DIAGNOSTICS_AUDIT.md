# PHASE4_DIAGNOSTICS_AUDIT.md — Diagnostics Isolation Audit

> Produced by: Phase 3d / Phase 4 kickoff atomic step
> Date: 2026-03-28
> Branch: refactor/simplify-single-authority-l3
> Test count entering Phase 4: 330 passing

---

## Audit Scope

Phase 4 goal: Ensure diagnostics **cannot alter steady-state runtime behavior** outside
explicit bounded windows. Reduce baseline noise. Enforce auto-expiry.

Three distinct diagnostics subsystems identified:

---

## Subsystem A — HLS Conditional Diagnostic Mode (ProgramDirector)

**Location:** `pkg/core/src/retrovue/runtime/program_director.py`
**Owner:** ProgramDirector (single authority ✓)
**Contract:** `tests/contracts/runtime/test_inv_hls_diagnostic_mode.py` (4 tests)

### What it does
- Ring buffer per channel (`_hls_diag_ring`, bounded by `_hls_diag_ring_max_events`)
- Timed "active window" per channel (`_hls_diag_mode_until`, auto-expires ✓)
- Triggered by: wallclock audit violations, unexpected segment 404, repeated reconnects
- When active: emits WARNING logs for every manifest/segment serve

### Isolation status: **PARTIALLY CORRECT, 1 ISSUE**

**Issue found:** `_hls_diag_record()` is called **unconditionally on EVERY manifest and
segment serve**, regardless of whether diagnostic mode is active. This means:
- Lock contention on `_hls_diag_lock` happens on every HLS poll (could be 10–30 Hz)
- The ring keeps accumulating history at steady state (bounded by maxlen, so no leak)
- Records are intentional pre-fault history (by design — so they exist when triggered)

**Verdict:** The ring-write approach is intentional for "lookback" value. It does NOT
alter runtime behavior (no branching on ring contents at steady state). Lock contention
is minimal (deque append under lock is ~microseconds). **Acceptable as-is.**

The steady-state WARNING log path IS gated by `_hls_diag_is_active()` — that check is
correct. No log noise at steady state. ✓

### Invariants holding
- [x] Auto-expiry via `_hls_diag_mode_until` timed window ✓
- [x] Ring bounded by `ring_max_events` ✓
- [x] Trigger causes active window, not permanent mode ✓
- [x] No behavior change at steady state (only logs change when active) ✓
- [x] Contract `test_inv_hls_diagnostic_mode.py` covers structure ✓

### Action needed: None. Status: CLEAN.

---

## Subsystem B — Pool Resolution Diagnostics (SchedulingLayer)

**Location:** `pkg/core/src/retrovue/runtime/program_assembly.py`,
`catalog_resolver.py`, `asset_resolver.py`
**Owner:** program_assembly layer (single authority ✓)
**Contract:** `tests/contracts/test_pool_diagnostics_integration.py` (11 tests)
            `tests/contracts/test_pool_resolution_visibility.py`

### What it does
- `query_with_diagnostics()` on resolvers: counts candidates, records exclusion reasons
- Called only when pool resolution is needed (schedule assembly time, not request time)
- Attaches `PoolDiagnostics` to `AssemblyResult.pool_diagnostics` for empty pools
- Emits `INV-POOL-RESOLUTION-VISIBILITY-001` WARNING log for empty pools

### Isolation status: **CLEAN**

- These diagnostics are computed only during schedule assembly, not on the hot HLS path
- They do not alter runtime behavior: empty pools still proceed / fault on content-pool empty
- Log output is conditional on pool being empty (no steady-state log noise) ✓
- Data is attached to result objects and consumed by callers — no side effects ✓

### Action needed: None. Status: CLEAN.

---

## Subsystem C — StreamingDiagnostics config schema (DEAD OR AIR-ONLY)

**Location:** `pkg/core/src/retrovue/config/schema.py` (class `StreamingDiagnostics`)
**Fields:** `enabled`, `startup_events`, `steady_interval`, `recv_gap_warn_threshold_ms`,
           `recv_gap_warn_count`, `upstream_loop_spike_ms`

### What it does (or should do)
These fields exist in `StreamingSchema.diagnostics` but grep finds ZERO references to
them in any Python runtime code outside config loading. They are declared in config
and in `testing.py` fixtures, but **not consumed by any Python runtime module**.

Hypothesis: These are consumed by the AIR layer (C++ PipelineManager/FFmpeg) which reads
its config directly from the same YAML. If so, these are correct schema definitions for
AIR-side behavior.

### Isolation status: **NEEDS VERIFICATION**

**Question to answer in Phase 4b:** Are these fields actually read by AIR (C++ code) or
by any Python runtime code? If they're read by AIR only, the schema is correct and the
Python side is appropriately hands-off. If they're dead in both layers, they're config noise.

### Action needed: 4b — Verify consumption of StreamingDiagnostics fields.

---

## Subsystem D — pts_drift_logger.py (AIR, Reference Only)

**Location:** `pkg/air/playout/pts_drift_logger.py`
**Status:** DEPRECATED per docstring. Reference for C++ contract only. Not called in production.

### Isolation status: CLEAN (already marked, no runtime path)

### Action needed: None.

---

## Subsystem E — diagnostics/ts_health.py (CLI-only)

**Location:** `pkg/core/src/retrovue/diagnostics/ts_health.py`
**Usage:** CLI tool only (`python -m retrovue.diagnostics.ts_health <url>`)
**Runtime wiring:** NONE — not imported by any runtime module

### Isolation status: CLEAN

### Action needed: None.

---

## Phase 4 Execution Plan

| Sub-step | Action | Target | Risk |
|----------|--------|--------|------|
| 3d | Kickoff: write this audit (DONE) | PHASE4_DIAGNOSTICS_AUDIT.md | None |
| 4a | Verify StreamingDiagnostics config fields — grep AIR C++ code for usage | schema.py investigation | Low |
| 4b | If StreamingDiagnostics fields are dead in both layers: remove from schema + testing config | schema.py, testing.py | Medium |
| 4c | Write contract test: `_hls_diag_record` must NOT be called on warm-path when ring is at capacity AND diag inactive (optional — only if overhead verified problematic via profiling) | SKIP unless profiling shows issue | Low |
| 5a | Phase 5: Change-surface control gates | Process gates | — |

---

## Summary

- Subsystem A (HLS conditional diag): **CLEAN** — bounded, auto-expiring, no steady-state noise
- Subsystem B (Pool diagnostics): **CLEAN** — event-driven, no hot-path overhead
- Subsystem C (StreamingDiagnostics schema): **NEEDS VERIFICATION** — check if dead config
- Subsystem D (PTS drift logger): **CLEAN** — deprecated, reference only
- Subsystem E (ts_health CLI): **CLEAN** — CLI-only, no runtime wiring

**NEXT SUB-STEP: 4a** — Grep AIR C++ code for StreamingDiagnostics config field consumption.
