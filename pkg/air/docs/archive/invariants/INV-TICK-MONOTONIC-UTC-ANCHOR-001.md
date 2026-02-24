# INV-TICK-MONOTONIC-UTC-ANCHOR-001: Monotonic Deadline Enforcement Anchored to UTC Epoch

**Classification:** INVARIANT (Coordination — Broadcast-Grade)
**Owner:** PipelineManager
**Enforcement Phase:** Every output tick within a BlockPlan playout session
**Depends on:** Clock Law (Layer 0), INV-TICK-DEADLINE-DISCIPLINE-001
**Created:** 2026-02-08
**Status:** Active

---

## Definition

AIR MUST anchor tick deadlines to the session's UTC epoch, but MUST implement
deadline waiting and lateness detection using a monotonic clock to avoid
system-time adjustments (NTP steps, leap corrections, admin changes) from
breaking cadence.

At session start, AIR MUST capture:

- `session_epoch_utc_ms` (UTC wall-clock authority)
- `session_epoch_mono_ns` (monotonic anchor)

For each tick `N`, AIR MUST compute a monotonic deadline:

- `deadline_mono_ns(N) = session_epoch_mono_ns + round_rational(N * 1e9 * fps_den / fps_num)`

And MUST treat tick `N` as late if:

- `now_mono_ns >= deadline_mono_ns(N)`

This preserves the UTC schedule model while keeping enforcement stable under
UTC clock perturbations.

---

## Scope

Applies to:

- Tick deadline computation and lateness detection.
- Waiting/sleep decisions in the tick loop.

Does NOT apply to:

- Fence tick computation itself (that remains UTC-based per INV-BLOCK-WALLCLOCK-FENCE-001).

---

## Requirements

### R1 — Dual-anchor capture
A session MUST record both UTC epoch and monotonic epoch once, at session start,
and MUST NOT rewrite them during the session.

### R2 — Monotonic enforcement
All "are we late?" checks and "wait until deadline" behavior MUST use monotonic time.

### R3 — UTC remains the schedule authority
The UTC epoch remains the authoritative origin for mapping schedules → fence ticks
and for defining "what should be happening now" semantically. Monotonic time is an
implementation anchor for enforcement, not a new scheduling authority.

---

## Forbidden Patterns

- Using `utcnow()`/system wall time directly for "wait until tick deadline"
- Re-anchoring epochs mid-session
- Letting NTP/system-time steps cause tick cadence discontinuities

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_monotonic_utc_anchor.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_epochs_are_captured_once` | 001 | Verify UTC+monotonic epochs are immutable once session starts. |
| `test_deadline_mono_matches_rational_period` | 001 | Validate monotonic deadlines follow rational FPS across many ticks (no drift). |
| `test_monotonic_enforcement_ignores_utc_step` | 001 | Simulate UTC time step (mocked); assert lateness detection remains correct via monotonic clock. |
| `test_utc_authority_unchanged_for_fence_math` | 001 | Ensure fence tick computation still uses UTC epoch + schedule, not monotonic time. |
