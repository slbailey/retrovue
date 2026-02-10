# INV-JOIN-IN-PROGRESS-BLOCKPLAN: Join-In-Progress for BlockPlan Bootstrap

**Component:** Core / BlockPlanProducer
**Enforcement:** Runtime (`channel_manager.py`)
**Depends on:** INV-FEED-QUEUE-DISCIPLINE, INV-FEED-EXACTLY-ONCE
**Created:** 2026-02-07

---

## Purpose

When the first viewer tunes into a channel, Core must begin playout at the
correct position within the channel's cyclic content schedule — not from the
beginning.  Join-In-Progress (JIP) is the computation that determines
**which block** in the cycle is active and **how far into it** playback
should begin, as if the channel had been airing continuously since a known
reference time.

JIP applies exclusively to the BlockPlan bootstrap path
(`BlockPlanProducer` + `PlayoutSession`).  It does not apply to
Playlist-driven playout or legacy producer paths.

---

## Scope

JIP covers the first two seeded blocks and the cursor state established
before steady-state feeding begins.  Once seeding is complete,
steady-state feeding proceeds identically to a non-JIP session
(INV-FEED-QUEUE-* governs).

JIP operates on the `playout_plan` (a `list[dict]`) directly.  It never
accesses, requires, or assumes the existence of a `Playlist` object or
`manager._playlist`.

---

## Definitions

| Term | Meaning |
|------|---------|
| **Playout plan** | Ordered list of entries defining the content cycle.  Each entry has `asset_path`, optional `asset_start_offset_ms` (default 0), and optional `duration_ms` (default `block_duration_ms`). |
| **Cycle** | One complete traversal of all playout plan entries.  The cycle repeats round-robin indefinitely. |
| **Cycle length** | Sum of the resolved duration of every entry in the playout plan (milliseconds). |
| **Cycle origin** | A wall-clock UTC epoch (milliseconds) anchoring cycle position 0 to a real-world time.  Typically derived from the channel's programming day start. |
| **Elapsed** | `(at_station_time_utc_ms - cycle_origin_utc_ms)`, the wall-clock duration since the cycle anchor. |
| **Cycle position** | `elapsed_ms mod cycle_length_ms` — the offset within the current cycle iteration. |
| **Active entry** | The playout plan entry whose time window contains the cycle position. |
| **Active entry index** | The 0-based index of the active entry within the playout plan. |
| **Block offset** | `cycle_position_ms - sum(durations[0..active_entry_index-1])` — the elapsed time within the active entry. |

---

## Required Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| `at_station_time` | `datetime` (UTC) | `MasterClock.now_utc()` | Wall-clock time of the first viewer join. |
| `playout_plan` | `list[dict[str, Any]]` | Schedule service or test harness | Ordered cycle entries.  Each entry has `asset_path` and optionally `duration_ms` and `asset_start_offset_ms`. |
| `block_duration_ms` | `int` | `BlockPlanProducer` configuration | Default block duration when an entry lacks `duration_ms`. |
| `cycle_origin_utc_ms` | `int` | Configuration or derived from `programming_day_start` | Wall-clock epoch (ms) when the cycle was at position 0. |

---

## Required Outputs

| Output | Type | Description |
|--------|------|-------------|
| `active_entry_index` | `int` | 0-based index of the active playout plan entry. |
| `block_offset_ms` | `int` | Milliseconds elapsed within the active entry since its start. |

These two values fully determine the initial seeding state:

- **First seeded block (block_a):**
  - Generated from `playout_plan[active_entry_index]`
  - `block_start_utc_ms` = `floor(join_utc_ms / block_duration_ms) * block_duration_ms`
    (grid-aligned wall-clock boundary)
  - `block_duration_ms` = entry's resolved duration (full, never reduced)
  - `end_utc_ms` = `block_start_utc_ms + block_duration_ms`
  - Segment within the block:
    - `asset_start_offset_ms` = entry's own `asset_start_offset_ms` + `block_offset_ms`
    - `segment_duration_ms` = entry's resolved duration - `block_offset_ms`
  - The block owns its full grid slot.  The segment is shorter than the
    block by `block_offset_ms`.  The remaining time at the block's tail
    is filled by the TAKE fallback chain (freeze/pad per
    INV-TICK-GUARANTEED-OUTPUT).

- **Second seeded block (block_b):**
  - Generated from `playout_plan[(active_entry_index + 1) % len(playout_plan)]`
  - Uses the entry's own `asset_start_offset_ms` (no JIP offset added)
  - Full entry duration; `segment_duration_ms == block_duration_ms`
  - Presentation time contiguous with block_a:
    `start_utc_ms = block_a.end_utc_ms`

- **Cursor after seeding:**
  - `_next_block_start_ms = block_b.end_utc_ms`
  - `_block_index = active_entry_index + 2` (ordinal counter for block IDs only;
    does not determine playlist entry selection)

---

## Invariants

### INV-JIP-BP-001: Single Computation on First Viewer

> JIP is computed exactly once per session lifetime, at the 0-to-1
> viewer transition.  It is never recomputed mid-session.  No timer,
> sleep, or polling loop triggers JIP.

**Rationale:** JIP establishes the starting position.  Once playout begins,
the block sequence is self-advancing via BLOCK_COMPLETE events.

---

### INV-JIP-BP-002: Offset Within Bounds

> `block_offset_ms` is in the half-open interval
> `[0, active_entry_duration_ms)`, where `active_entry_duration_ms`
> is the resolved duration of the active playout plan entry.

**Rationale:** An offset equal to the entry's duration means we should be
on the *next* entry, not at the end of this one.  An offset of 0 is
valid and means we are joining exactly at a block boundary.

---

### INV-JIP-BP-003: Deterministic Mapping

> For identical values of `(playout_plan, block_duration_ms,
> cycle_origin_utc_ms, at_station_time)`, JIP always produces
> identical `(active_entry_index, block_offset_ms)`.

**Rationale:** Reproducibility.  Two viewers joining at the same
wall-clock instant on the same channel see the same content from the
same position.

---

### INV-JIP-BP-004: Continuous Sequence (No Rewind)

> The block sequence delivered to AIR starting from the JIP point
> is identical to the suffix of the sequence that would have been
> produced by continuous airing since `cycle_origin_utc_ms`.
> No block in the cycle is repeated or skipped.

**Rationale:** A viewer joining at time T sees the same content
(and in the same order) as a hypothetical viewer who has been
watching since the cycle origin.  "No rewind" means the JIP
point is strictly determined by elapsed wall-clock time.

---

### INV-JIP-BP-005: First Seed Carries Segment Offset, Second Seed Starts Clean

> The first seeded block (block_a) has its segment's
> `asset_start_offset_ms` increased by `block_offset_ms` and its
> `segment_duration_ms` decreased by `block_offset_ms`.
> The block's own duration (`end_utc_ms - start_utc_ms`) is NOT
> reduced; it remains equal to `block_duration_ms`.
> The second seeded block (block_b) uses its plan entry's own
> `asset_start_offset_ms` unmodified, with full entry duration and
> `segment_duration_ms == block_duration_ms`.

**Rationale:** Only the first block's segment is partial — content
begins at the JIP offset and ends before the block boundary.  The
block itself occupies its full grid-aligned wall-clock slot.  The
time between segment exhaustion and the block fence is filled by the
TAKE fallback chain (INV-TICK-GUARANTEED-OUTPUT).  All subsequent
blocks have `segment_duration_ms == block_duration_ms`.

---

### INV-JIP-BP-006: First Block Duration Immutable, First Segment Reduced

> The first seeded block's duration (`end_utc_ms - start_utc_ms`)
> MUST equal `block_duration_ms`.  It is NOT reduced by JIP offset.
>
> The first segment's playable duration within the block is
> `block_duration_ms - block_offset_ms`.  This is shorter than the
> block by exactly `block_offset_ms`.
>
> The time between segment exhaustion and the block's fence tick is
> filled by the TAKE fallback chain (freeze/pad per
> INV-TICK-GUARANTEED-OUTPUT).  This tail pad is an expected
> consequence of JIP, not a content underrun.

**Rationale:** The viewer joins mid-block.  The first segment begins
at the JIP offset and plays the remaining portion of the active entry.
The block's temporal envelope is fixed to the wall-clock grid — it
occupies its full `block_duration_ms` slot regardless of how much
content the segment contains.  This ensures all blocks chain with
identical duration, fence computation is uniform, and no cumulative
drift occurs from shortened first blocks.

---

### INV-JIP-BP-007: Cursor Consistency After Seeding

> After seeding two blocks, the cursor state satisfies:
> - `_next_block_start_ms == block_b.end_utc_ms`
> - `_block_index` is an ordinal counter used only for block ID
>   generation; it does NOT determine playlist entry selection.
>
> Playlist entry selection is derived from `_next_block_start_ms` via
> `compute_jip_position()`, which maps wall-clock position to the
> correct cycle entry.  The next call to `_generate_next_block()`
> produces the entry at the wall-clock position corresponding to
> `_next_block_start_ms`, with `start_utc_ms` equal to
> `block_b.end_utc_ms`.

**Rationale:** Steady-state feeding must resume seamlessly from the
position established by JIP seeding.  Entry selection derives from
wall-clock position (LAW-DOWNWARD-CONCRETIZATION), not from an
ordinal block counter which is an execution-layer artifact.

---

### INV-JIP-BP-008: Steady-State Feeding Unchanged

> After JIP seeding completes, the feeding discipline is governed
> entirely by INV-FEED-QUEUE-001 through INV-FEED-QUEUE-005.
> JIP introduces no additional state, callbacks, or control paths
> into the steady-state feeding loop.

**Rationale:** JIP is a bootstrap concern.  Once the session is seeded,
the existing event-driven feeding machinery (BLOCK_COMPLETE-driven,
pending-block-slot retry) handles all subsequent blocks.

---

## Constraints

### C1: Canonical AIR Bootstrap Preserved

The gRPC sequence is unchanged:
`GetVersion` -> `AttachStream` -> `StartBlockPlanSession` -> `SubscribeBlockEvents` -> `FeedBlockPlan`

JIP affects only **which blocks** are passed to `StartBlockPlanSession`
(seed) and what offsets they carry.  It does not alter the RPC sequence
or introduce new RPCs.

### C2: No Playlist Dependency

JIP operates on `playout_plan: list[dict]`.  `BlockPlanProducer` must
never read or require `manager._playlist`.  A runtime tripwire
(`assert self._playlist is None` or equivalent guard) should exist in
the burn-in path to enforce this boundary.

### C3: No New Coordinate Systems

JIP uses wall-clock UTC milliseconds for schedule decisions and integer
counters (`start_utc_ms`, `end_utc_ms`, `_block_index`) for execution
— the same coordinate spaces already used by BlockPlanProducer.

---

## Required Tests

**File:** `pkg/core/tests/contracts/test_jip_blockplan_contract.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_jip_offset_within_bounds` | INV-JIP-BP-002 | For various elapsed times, `block_offset_ms` is in `[0, entry_duration)`. |
| `test_jip_deterministic_mapping` | INV-JIP-BP-003 | Same inputs produce identical outputs across multiple calls. |
| `test_jip_sequence_matches_continuous` | INV-JIP-BP-004 | Block sequence from JIP point matches the tail of a continuous sequence from origin. |
| `test_jip_first_block_offset_second_block_clean` | INV-JIP-BP-005 | First block's segment carries computed offset; block duration is full; second block has entry's natural offset. |
| `test_jip_first_block_duration_immutable` | INV-JIP-BP-006 | First block's `end_utc_ms - start_utc_ms == block_duration_ms`; first segment's duration equals `block_duration_ms - offset`. |
| `test_jip_cursor_consistent_after_seeding` | INV-JIP-BP-007 | `_block_index` and `_next_block_start_ms` allow correct next-block generation. |
| `test_jip_steady_state_feeding_unchanged` | INV-JIP-BP-008 | After JIP seed, BLOCK_COMPLETE triggers normal feeding with no JIP side-effects. |
| `test_jip_cycle_wraparound` | INV-JIP-BP-003, 004 | Elapsed time exceeding multiple full cycles still resolves correctly. |
| `test_jip_variable_duration_entries` | INV-JIP-BP-002, 005 | Plan with heterogeneous per-entry `duration_ms` values computes correct index and offset. |
| `test_jip_exact_boundary_offset_zero` | INV-JIP-BP-002, 006 | Join landing exactly on a grid boundary yields `offset = 0`, full block, and `segment_duration_ms == block_duration_ms`. |
| `test_jip_single_entry_plan` | INV-JIP-BP-003, 007 | Plan with one entry: every join resolves to index 0 with correct offset; cursor wraps. |
| `test_jip_only_on_first_viewer` | INV-JIP-BP-001 | Second viewer join does not re-trigger JIP or alter block sequence. |
