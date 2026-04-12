# INV-BLOCK-ALIGNMENT-001: Block Start Aligned to Grid Boundary

**Classification:** INVARIANT (Coordination)
**Owner:** BlockPlanProducer / burn_in _compose_block
**Enforcement Phase:** Block generation, before segment composition
**Depends on:** INV-JIP-WALLCLOCK-001, INV-WALLCLOCK-FENCE-001
**Created:** 2026-02-09

---

## Definition

> `block.start_utc_ms` MUST be aligned to the configured grid boundary
> (default: 30-minute, i.e. :00/:30 UTC).
>
> Formally:
>
>     (block.start_utc_ms - cycle_origin_utc_ms) % block_duration_ms == 0
>
> This MUST hold for ALL blocks, including the first JIP block.

---

## Scope

Alignment is a property of the block container, not the content within it.

Alignment MUST NOT depend on:

- `jip_offset_ms`
- `asset_start_offset_ms`
- segment start offsets or composition results
- filler/pad duration
- "effective start" of the first decoded segment

JIP inherently starts mid-block.  A non-zero `jip_offset_ms` is normal
and MUST NOT be treated as misalignment.

---

## Enforcement

The alignment check MUST run:

1. On the block's absolute `start_utc_ms` (= `_next_block_start_ms`).
2. Before applying JIP offsets to segments.
3. Before composing segments (episode, filler, pad).

---

## Corollary: Block Duration Never Reduced

Per INV-JIP-WALLCLOCK-001, `block_dur_ms` is always `BLOCK_DURATION_MS`.
JIP only adjusts content offsets within the block; the block container
is `[start_utc_ms, start_utc_ms + BLOCK_DURATION_MS)`.  Because both
start and duration are grid-aligned, `end_utc_ms` is also grid-aligned.
Subsequent blocks inherit `end_utc_ms` as their start, preserving alignment.

---

## Regression

Prior to this invariant, `burn_in.py` shortened `block_dur_ms` by
`jip_offset_ms` for JIP blocks, producing a misaligned `end_utc_ms`.
The misaligned end cascaded to block B's `start_utc_ms`, triggering:

    "BURN_IN: start not aligned to 30-min boundary (offset=1702903)"

on block B even though block A's start was correctly aligned.

The old alignment check (a) only ran on non-JIP blocks, and (b) used a
derived offset instead of validating `start_utc_ms` directly.

---

## Test Coverage

| Test | Invariant | What it proves |
|------|-----------|----------------|
| `test_jip_block_start_and_end_aligned` | INV-BLOCK-ALIGNMENT-001 | JIP block start and end on grid boundaries |
| `test_block_b_aligned_after_jip_block_a` | INV-BLOCK-ALIGNMENT-001 | Block B inherits aligned end from JIP block A |
| `test_30min_jip_at_19_01_into_19_00_block` | INV-BLOCK-ALIGNMENT-001 | Regression: 30-min block, JIP at 19:01 into 19:00 block, all aligned |
