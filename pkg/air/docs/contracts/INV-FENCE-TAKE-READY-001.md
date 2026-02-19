# INV-FENCE-TAKE-READY-001: Fence Take Readiness and DEGRADED_TAKE_MODE

## Classification

| Field | Value |
|-------|--------|
| ID | INV-FENCE-TAKE-READY-001 |
| Owner | PipelineManager |
| Layer | Coordination / Broadcast-grade take |

## Definition

At the fence tick, if the next block's first segment is **CONTENT**, the system must satisfy at least one:

1. **Preview buffer primed** to the required threshold (B has frames ready), or  
2. **Explicit fallback engaged** (DEGRADED_TAKE_MODE: hold last committed A frame + silence).

It must **never** take PAD for a content-first block due to priming lag. It must **never** assert or crash at the fence.

## Enforcement

- When the tick loop would emit **PAD** for slot B at the fence and the next block is content-first:
  - **Do not** take PAD for B.
  - **Do not** assert or crash.
  - Log **INV-FENCE-TAKE-READY-001 VIOLATION DEGRADED_TAKE_MODE** with cause and headroom (exactly once per fence event).
  - Enter **DEGRADED_TAKE_MODE**:
    - Ticks continue normally (no tick skipping, no wallclock delay).
    - Output video = hold last committed A frame (`last_good_video_frame_`).
    - Output audio = silence (continuity-preserving).
    - Continue preroll/retry until B meets threshold.
  - When B later meets threshold (pop succeeds), commit B frame, rotate B→A, exit degraded mode.

- **Rotation** runs only when a B frame was **committed this tick** (`committed_b_frame_this_tick`). In degraded mode we do not rotate until B is primed and we pop a frame from B.

## DEGRADED_TAKE_MODE behavior

| Aspect | Behavior |
|--------|----------|
| Video | Last committed A frame (held); no black. |
| Audio | Silence (same path as underflow bridge). |
| Ticks | No skip; no wallclock delay; no fence delay. |
| Preroll | Continues; retry once if headroom ≥ 2000ms and decoder failed. |
| Exit | When B buffer is primed and we pop a B frame → commit it, rotate, clear `degraded_take_active_`. |
| Logging | Violation logged exactly once when entering degraded (first tick at fence with content-first B unprimed). |
| Bounded escalation | After **HOLD_MAX_MS** (5s) in degraded with B still not primed, switch to **standby** (slot `S`): output pad/slate, continuous; no crash. |

## No-unintentional-black guarantee

- Block A must produce a known non-black fingerprint just before the fence (last A frame: `is_pad == false`, `y_crc32 != 0`).
- Held frames (slot `H`) must match the last good A frame fingerprint (`y_crc32`, `is_pad == false`); must **not** match PAD/black.

## Tests

- **DegradedTakeModeContractTests.cpp** — `UnprimedBAtFence_NoBlackNoCrash_HeldThenB`:
  - Simulated fence where B is unprimed (delay hook on block prep): must **not** output black and must **not** crash.
  - Output must be held frame (slot `H`) then cut to B (slot `B`) when B is primed; verified via `FrameFingerprint.commit_slot`.
  - **No-unintentional-black:** Last A frame before fence is non-pad, non-zero `y_crc32`; every `H` frame has same `y_crc32` as last A.
  - **Violation exactly once:** Logger error sink captures lines; assert exactly one line contains `INV-FENCE-TAKE-READY-001 VIOLATION DEGRADED_TAKE_MODE`.
  - Block A must complete; no detach; continuous output continues through degraded take.
- **UnprimedBAtFence_BNeverPrimes_EscalatesToStandby:**
  - B prep never completes (delay hook > test duration). Assert: no crash; output holds (slot `H`) then switches to standby (slot `S`) after HOLD_MAX_MS; output remains continuous.
- Existing PREROLL and decoder-step tracing unchanged.

## References

- `docs/diagnostics/FENCE-PREROLL-LIFECYCLE-AND-INVARIANT.md`
- `docs/diagnostics/FENCE-BLACK-FRAMES-ROOT-CAUSE.md`
