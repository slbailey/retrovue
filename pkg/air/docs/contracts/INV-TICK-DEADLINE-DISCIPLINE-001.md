# INV-TICK-DEADLINE-DISCIPLINE-001: Hard Deadline Discipline for Output Ticks

**Classification:** INVARIANT (Coordination — Broadcast-Grade)
**Owner:** PipelineManager
**Enforcement Phase:** Every output tick within a BlockPlan playout session
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, LAW-OUTPUT-LIVENESS, Clock Law (Layer 0), INV-BLOCK-WALLCLOCK-FENCE-001
**Created:** 2026-02-08
**Status:** Active

---

## Definition

AIR MUST treat each output tick `N` as a **hard scheduled deadline** derived from the
session's epoch and rational FPS timebase.

Let `spt(N)` be the scheduled presentation time (SPT) for tick `N`, expressed as
a rational value (not quantized to integer milliseconds):

- `spt(N) = session_epoch_utc + N * fps_den / fps_num`
  (rational arithmetic; authoritative timebase — convert to ms only for display/logging)

AIR MUST enforce that the output stream advances by exactly one tick per frame
period *in wall-clock time*, even when internal work (decode, I/O, transitions,
mux) runs late.

If the system is late for a tick, AIR MUST still emit an output frame for that
tick immediately using a **non-blocking fallback path** (freeze/pad), and MUST
advance `session_frame_index` by exactly 1.

This invariant ensures that wall-clock anchored fences (INV-BLOCK-WALLCLOCK-FENCE-001)
occur at their scheduled wall-clock instants rather than "when we eventually reach
the fence tick".

*Tick deadlines do not define schedule semantics; they enforce schedule semantics defined by block boundary authorities (INV-BLOCK-WALLCLOCK-FENCE-001) and the session epoch.*

---

## Scope

Applies to:

- The main output pacing loop that advances `session_frame_index`.
- The wall-clock timing behavior of *every tick* (not just block boundaries).
- All block swaps that are defined in tick-index space (INV-BLOCK-WALLCLOCK-FENCE-001).

Does NOT apply to:

- Offline rendering / non-realtime export modes (if any exist).
- Precomputation / planning logic that does not emit ticks.

---

## Requirements

### R1 — One tick per frame period (no slip)
For each tick `N`, AIR MUST schedule emission against `spt(N)` such that:

- If `now < spt(N)`: AIR MAY wait until `spt(N)` to emit tick `N`.
- If `now >= spt(N)`: AIR MUST NOT delay tick emission to complete expensive work.

`now` is evaluated in the enforcement time domain (see INV-TICK-MONOTONIC-UTC-ANCHOR-001).

### R2 — Late ticks MUST still emit (fallback allowed)
When `now >= spt(N)` and a normal content frame is not already available
without blocking:

- AIR MUST emit a fallback frame (freeze or pad) for tick `N`.
- AIR MUST NOT block on decode, demux, I/O, segment transition, mux flush, or
  any other operation that can exceed the remaining time budget for the tick.

Fallback frames MUST satisfy INV-TICK-GUARANTEED-OUTPUT and LAW-OUTPUT-LIVENESS.

### R3 — No catch-up bursts
AIR MUST NOT attempt to "catch up" by emitting multiple ticks back-to-back in a
tight loop. Each output tick corresponds to exactly one output frame period and
must preserve cadence.

Late ticks are represented by fallback output, not accelerated time.

### R4 — Fence checks remain tick-index authoritative even when late
Block transitions MUST remain driven by the fence tick index. The A/B swap rule:

- swap when `session_frame_index >= fence_tick`

MUST still be evaluated using the tick index and MUST still occur BEFORE frame
emission on the fence tick (per INV-BLOCK-WALLCLOCK-FENCE-001), even if the tick
is late and using fallback output.

### R5 — Drift-proof anchoring
A slow/long/blocked tick MUST NOT shift the scheduled deadlines of future ticks.
Tick `N+1` remains anchored to `spt(N+1)` derived from the session epoch,
not from "when tick N finished".

---

## Forbidden Patterns

- **Best-effort progression:** "emit frames as fast as possible; fences happen when we reach the index"
- **Work-first pacing:** decode/transition/mux determines when tick N is emitted
- **Catch-up bursts:** emitting multiple ticks in one wall-clock frame period
- **Reactive fence firing:** swapping blocks because a budget hit zero or a segment ended (timing authority violation)

---

## Relationship to Other Contracts

- Complements INV-BLOCK-WALLCLOCK-FENCE-001 by ensuring `session_frame_index`
  advances in lockstep with wall clock, so the fence tick occurs at the scheduled instant.
- Does not change frame budget semantics (INV-BLOCK-FRAME-BUDGET-AUTHORITY):
  budget remains counting-only and decremented 1:1 per emitted output frame.
- Reinforces LOOKAHEAD PRIMING: priming reduces late risk at seams, but deadline
  discipline guarantees correctness even when priming fails.

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_tick_deadline_discipline.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_deadline_schedule_is_epoch_derived` | 001 | Verify `spt(N)` derives solely from epoch + rational FPS, independent of processing time. |
| `test_no_slip_under_decode_stall` | 001 | Simulate per-tick stalls; assert tick deadlines do not shift and tick index at time T matches expected (within jitter tolerance). |
| `test_late_tick_emits_fallback_without_blocking` | 001 | Force frame unavailability; ensure fallback frame is emitted immediately when late. |
| `test_no_catchup_burst_behavior` | 001 | When behind, engine emits at most one tick per loop iteration / wall-clock period (no multi-tick burst). |
| `test_fence_swap_occurs_on_tick_index_even_when_late` | 001 + INV-BLOCK-WALLCLOCK-FENCE-001 | Induce late seam; assert swap happens on fence tick index and before emission for that tick. |
| `test_future_deadlines_unchanged_after_late_ticks` | 001 | Induce late ticks; verify `spt(N+k)` remains epoch-derived (no drift accumulation). |
