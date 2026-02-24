# INV-EXECUTION-CONTINUOUS-OUTPUT-001: Continuous Output Execution Model

**Classification:** INVARIANT (Semantic — Broadcast-Grade)
**Owner:** PipelineManager
**Enforcement Phase:** Session lifetime when execution mode is continuous_output
**Depends on:** INV-TICK-DEADLINE-DISCIPLINE-001, INV-FPS-RESAMPLE, INV-TICK-GUARANTEED-OUTPUT, INV-SEAM-001
**Created:** 2026-02-23
**Status:** Active

---

## Definition

When the playout engine runs in **execution_model=continuous_output** (PlayoutExecutionMode::kContinuousOutput), the session MUST satisfy the following contract. This invariant ties continuous output to the house-format tick grid authority and forbids any segment, block, or decoder lifecycle event from shifting the tick schedule.

---

## Requirements

### R1 — Session runs in continuous_output

The authoritative execution mode for BlockPlan playout is continuous_output. The engine MUST use a session-long encoder, OutputClock at fixed cadence, pad frames when no block content is available, and TAKE-at-commit source selection at fence. No other execution mode is authoritative for the current runtime.

### R2 — Tick deadlines anchored to session epoch + rational output FPS

Tick deadlines MUST be derived solely from:

- **Session epoch** (UTC and monotonic), captured once at session start and immutable for the session (see INV-TICK-MONOTONIC-UTC-ANCHOR-001).
- **Rational output FPS** (fps_num, fps_den) from the session ProgramFormat (house format).

The scheduled presentation time for tick N is:

- `spt(N) = session_epoch_utc + N * fps_den / fps_num` (rational timebase; in ms: `spt_ms(N) = session_epoch_utc_ms + N * 1000 * fps_den / fps_num` using integer division consistent with INV-FPS-RESAMPLE).

The tick grid is fixed by session RationalFps; no floating-point FPS or rounded intervals.

### R3 — No segment/block/decoder lifecycle event may shift tick schedule

No segment swap, block transition, decoder open/close/seek/prime, or buffer swap MAY change:

- When tick N is scheduled (spt(N)),
- The advancement of session_frame_index (exactly one per tick),
- Or the cadence of the output clock.

INV-SEAM-001 (clock isolation) guarantees the channel clock MUST NOT observe or be influenced by decoder lifecycle events. This invariant makes that explicit for the continuous_output execution model: the tick schedule remains fixed regardless of content or decoder state.

### R4 — Underflow handling may repeat/black; tick schedule remains fixed

When underflow occurs (e.g. buffer depth below low-watermark), the engine MAY emit repeat (freeze) or pad (black) frames per INV-TICK-GUARANTEED-OUTPUT and INV-DETERMINISTIC-UNDERFLOW-AND-TICK-OBSERVABILITY. Such handling MUST NOT shift the tick schedule. Late ticks still advance session_frame_index by exactly one; future tick deadlines remain anchored to session epoch + rational FPS. No catch-up bursts, no slip.

### R5 — Tick cadence (grid) fixed by session RationalFps; frame-selection cadence may refresh

- **Tick cadence (grid):** When ticks occur is defined exclusively by session epoch + rational output FPS. Authority: house format (ProgramFormat). Same as INV-FPS-RESAMPLE and INV-TICK-DEADLINE-DISCIPLINE-001.
- **Frame-selection cadence:** Policy for which source frame to emit per tick (repeat vs advance, OFF/DROP/CADENCE) MAY be refreshed on segment swap or source change. Such refresh MUST NOT affect when ticks fire or the value of spt(N). Frame-selection cadence governs presentation only; the tick schedule is independent.

---

## Scope

Applies to:

- All sessions driven by PipelineManager with PlayoutExecutionMode::kContinuousOutput.
- The main output pacing loop, OutputClock, and any path that advances session_frame_index or computes tick deadlines.

Does NOT apply to:

- Offline or non-realtime modes (if any).
- Planning or Core logic that does not emit ticks.

---

## Relationship to Other Contracts

- **INV-TICK-DEADLINE-DISCIPLINE-001:** Defines hard deadline discipline and spt(N) anchoring; this invariant states that continuous_output is the execution model for which that discipline applies and that no lifecycle event may violate it.
- **INV-FPS-RESAMPLE:** Tick grid from rational (fps_num, fps_den) only; this invariant ties that to execution_model=continuous_output.
- **INV-SEAM-001:** Clock isolation; this invariant explicitly forbids segment/decoder events from shifting the tick schedule.
- **INVARIANT-AUDIT-HOUSE-FORMAT-TICK-CADENCE:** Clarifies that execution_model=continuous_output is a first-class contract tied to tick cadence (house format).

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_inv_execution_continuous_output_001.cpp`

| Test Name | Invariant(s) | Description |
|-----------|--------------|-------------|
| `SptNIsFixedByEpochAndRationalFps` | INV-EXECUTION-CONTINUOUS-OUTPUT-001 | Given session fps_num/fps_den and epoch, spt(N) is fixed and computable from epoch + N * (fps_den/fps_num); independent of segment identity. |
| `SegmentSwapDoesNotAffectTickSchedule` | INV-EXECUTION-CONTINUOUS-OUTPUT-001 | Tick schedule formula depends only on session FPS and epoch; segment swap may affect frame-selection policy but not spt(N) or tick grid. |
