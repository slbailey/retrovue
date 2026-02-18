# INV-BREAK-PAD-EXACT-001: Ad Break Segment Sum Equals Allocated Duration

**Classification:** INVARIANT (Frame Budget)
**Owner:** `_interleave_segments()` in `planning_pipeline.py`
**Enforcement Phase:** Transmission log assembly, after `fill_breaks()`
**Depends on:** `fill_breaks()`, `FilledBreak.allocated_ms`, `FilledBreak.filled_ms`
**Created:** 2026-02-18

---

## Definition

> For every `FilledBreak` b in a `FilledBlock`, the sum of durations of its filled
> items PLUS any black pad segment emitted for that break MUST exactly equal the
> break's allocated duration:
>
>     sum(item.duration_ms for item in b.items) + break_gap_ms == b.allocated_ms
>
> where `break_gap_ms = b.allocated_ms - b.filled_ms`.
>
> No frames may be unaccounted for. No frames may overflow the allocation.

---

## Scope

This invariant applies to **every break in every block** at the point
`_interleave_segments()` is called during `assemble_transmission_log()`.

It MUST hold even when:

- The asset library returns no candidates (`items = []`).
- Partial fill occurs (only one spot filled, remainder as pad).
- An asset fills the break exactly (break_gap_ms = 0, no pad emitted).

---

## Enforcement

`_interleave_segments()` emits break content as follows for each `FilledBreak`:

1. Compute `break_gap_ms = next_break.allocated_ms - next_break.filled_ms`.
2. If `break_gap_ms > 0` and items exist: **distribute the gap evenly** across all
   items as micro-pad segments inserted after each item (INV-BREAK-PAD-DISTRIBUTED-001).
3. For each `BreakItem`: emit a segment with `segment_type` equal to `item.asset_type`
   (normalised: values not in `{"filler", "promo", "ad"}` are coerced to `"filler"`),
   then emit a black pad segment.

### Distribution Algorithm (INV-BREAK-PAD-DISTRIBUTED-001)

Given N items in a break with `break_gap_ms` of leftover time:

```
base_pad_ms  = break_gap_ms // N
extra_ms     = break_gap_ms % N
pad_sizes[i] = base_pad_ms          (for i in 0 .. N-extra_ms-1)
pad_sizes[i] = base_pad_ms + 1      (for i in N-extra_ms .. N-1)
```

Each `pad_sizes[i]` is emitted as a `segment_type: "pad"` segment immediately after
the corresponding break item. Pads of 0ms are suppressed (no segment emitted).

**Rationale:** Lumping all leftover frames at the end of a break creates a visible
dead-air gap. Distributing them as micro-pads between spots creates natural "breathers"
between ads — matching broadcast convention.

**Example:** 3 ads, 2000ms gap (60 frames at 30fps) → 666ms + 667ms + 667ms
(20 + 20 + 20 frames), one after each ad.

**Example:** 4 ads, 1333ms gap (40 frames) → 333ms + 333ms + 333ms + 334ms
(10 + 10 + 10 + 10 frames), remainder applied to last pad.

Pad segments are emitted **inside the break**, interleaved with items.
They are not deferred to block-level pad.

---

## Corollary: Block-Level Pad Is Unchanged

`fill_breaks()` MUST NOT adjust `block.pad_ms` to absorb unfilled break time.
Unfilled break time belongs to the break; block-level pad covers only the
content-to-block-duration shortfall inherent in programming structure.

The overall block budget identity therefore holds:

    content_ms + sum(break.allocated_ms for break in block.filled_breaks) + block.pad_ms
    == block.block_duration_ms

Where `sum(break.allocated_ms)` is the full allocated break time for all breaks,
regardless of how much was filled by assets vs. black pad.

---

## Regression

Prior to this invariant, unfilled break time was silently absorbed into block-level pad,
producing blocks where break gaps were invisible in the segment list. This caused
frame-count mismatches in downstream playout when the scheduler expected exactly
`break.allocated_ms` of content between content segment boundaries.

The fix: unfilled time is now explicitly represented as an inline `pad` segment within
the break, making the gap visible and auditable in the transmission log's segment list.

---

## Test Coverage

| Test | Invariant | What it proves |
|------|-----------|----------------|
| `test_break_pad_fills_unfilled_time` | INV-BREAK-PAD-EXACT-001 | Partial fill → pad segments emitted for remainder |
| `test_break_fully_filled_no_pad` | INV-BREAK-PAD-EXACT-001 | Exact fill → no pad segments emitted |
| `test_empty_break_all_pad` | INV-BREAK-PAD-EXACT-001 | Zero assets → entire break is one pad |
| `test_block_pad_unaffected_by_unfilled_break` | INV-BREAK-PAD-EXACT-001 | block.pad_ms unchanged when break is partially filled |
| `test_distributed_pad_3_items` | INV-BREAK-PAD-DISTRIBUTED-001 | 3 items, 2000ms gap → 666+667+667ms pads |
| `test_distributed_pad_4_items` | INV-BREAK-PAD-DISTRIBUTED-001 | 4 items, 1333ms gap → 333+333+333+334ms pads |
| `test_distributed_pad_exact_division` | INV-BREAK-PAD-DISTRIBUTED-001 | N items, gap divisible by N → equal pads |

---

## See Also

- `planning_pipeline.py` — `_interleave_segments()`, `fill_breaks()`, `_fill_one_break()`
- `docs/contracts/resources/TrafficManagementContract.md`
- `docs/contracts/resources/SchedulePlanInvariantsContract.md` — INV-SCHED-GRID-FILLER-PADDING
