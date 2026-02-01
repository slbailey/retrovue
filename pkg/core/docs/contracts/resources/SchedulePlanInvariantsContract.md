# Schedule Plan Invariants Contract

## Coverage Invariants

**INV_PLAN_MUST_HAVE_FULL_COVERAGE:** All SchedulePlans must satisfy full 24-hour coverage (00:00–24:00) with no gaps. Plans are automatically initialized with a default test filler zone (SyntheticAsset, 00:00–24:00) if no zones are provided. Plans must contain one or more Zones whose combined coverage spans 00:00–24:00 with no gaps.

## Frame Budget Invariants

**INV-SCHED-GRID-FILLER-PADDING:** For every grid block, the frame budget must balance exactly:

```
frames(program_content) + frames(filler) == grid_block_frames
```

This invariant ensures:
- Filler is deterministic padding with explicit frame count
- Filler always starts at frame 0 (no carry-over state)
- Filler EOF is expected success, not an error
- Safety rails are for violations, not normal operation

See [ScheduleManagerContract.md](../runtime/ScheduleManagerContract.md#inv-sched-grid-filler-padding-deterministic-filler-frame-budget) for complete specification.

## Runtime Switching Invariants

**INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION:** CORE must ensure the successor segment is promoted to live no later than `ct_exhaust_us - switch_lead_us`.

Key principles:
- Switching is scheduled in CT domain (no UTC conversions)
- Each segment has `ct_start_us`, `frame_count`, and `frame_duration_us`
- `ct_exhaust_us = ct_start_us + (frame_count * frame_duration_us)`
- Actual exhaustion overrides intended timing

Note: INV-SCHED-GRID-FILLER-PADDING guarantees frame budget correctness at schedule time.
This invariant governs runtime switching timing.

See [ScheduleManagerContract.md](../runtime/ScheduleManagerContract.md#inv-playout-switch-before-exhaustion-ct-domain-switching) for complete specification.

**INV-PLAYOUT-NO-PAD-WHEN-PREVIEW-READY:** If AIR is emitting pad frames and preview has frames ready, CORE must switch immediately.

This invariant ensures:
- Pad frames are a safety rail, not a pacing mechanism
- Recovery is immediate when successor content is available
- "3 seconds of black" cannot happen if preview is ready

See [ScheduleManagerContract.md](../runtime/ScheduleManagerContract.md#inv-playout-no-pad-when-preview-ready-emergency-fast-path) for complete specification.

## References

- [Domain: SchedulePlan](../../domain/SchedulePlan.md) for detailed domain documentation
- [ScheduleManagerContract](../runtime/ScheduleManagerContract.md) for runtime scheduling invariants