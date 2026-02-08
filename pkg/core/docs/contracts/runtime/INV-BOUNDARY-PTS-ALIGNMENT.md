# INV-BOUNDARY-PTS-ALIGNMENT: Block Boundary PTS Alignment

**Component:** AIR / Core (observable at TS output)
**Enforcement:** Runtime (TS/PES output validation)
**Depends on:** INV-CANONICAL-BOOTSTRAP, INV-PLAYOUT-AUTHORITY
**Created:** 2026-02-07

---

## Purpose

Block boundaries in a playout session must align to exact stream PTS
boundaries.  The first video PES packets of the *next* block must carry
a PTS equal to the mathematically derived boundary time in the 90kHz
MPEG-TS clock.  There must be no drift, gap, overlap, or floating-point
contamination in boundary PTS values across the lifetime of a session.

---

## Definitions

| Term | Definition |
|------|------------|
| `output_fps` | Fixed output frame rate for the channel, expressed as an integer or rational `num/den`. Example: `30` means `30/1`. |
| `frame_duration_90k` | `90000 * den / num` for rational `num/den` fps. MUST be an exact integer. A channel configuration where this value is not an exact integer is invalid (see Rounding Rule). |
| `output_frame_index` | Zero-based counter of output video frames emitted since session start. Monotonically increasing, never reset within a session. |
| `boundary_frame_index` | The `output_frame_index` at which a new block begins. |
| `boundary_pts_90k` | `boundary_frame_index * frame_duration_90k`. |
| `first video PTS of block` | The PTS of the first video frame in presentation order belonging to the block. |
| `last video PTS of block` | The PTS of the last video frame in presentation order belonging to the block. |
| `session` | A continuous playout session from first viewer join to last viewer leave. PTS is monotonic within a session. |

---

## Rounding Rule

`frame_duration_90k` MUST be an exact integer.  The value is computed as
`90000 * den / num` where the output frame rate is `num/den`.

Standard broadcast rates:

| output_fps (num/den) | frame_duration_90k | Integer? |
|----------------------|-------------------|----------|
| 30/1                 | 3000              | Yes      |
| 25/1                 | 3600              | Yes      |
| 24/1                 | 3750              | Yes      |
| 60/1                 | 1500              | Yes      |
| 30000/1001 (29.97)   | 3003              | Yes      |

If a channel's output_fps yields a non-integer `frame_duration_90k`,
the channel configuration MUST be rejected at startup.  No rounding
or truncation is permitted — the value is either exact or invalid.

---

## Invariants

### INV-BOUNDARY-PTS-001: Exact Boundary PTS

> For every block boundary, the first video PTS of the next block MUST
> equal `boundary_pts_90k` with **zero tolerance**.
>
> ```
> first_video_pts(block[N]) == boundary_frame_index[N] * frame_duration_90k
> ```

**Rationale:** Any deviation means the stream timeline has drifted from
the mathematical grid.  Downstream demuxers, analyzers, and A/V sync
rely on PTS accuracy to the 90kHz tick.

---

### INV-BOUNDARY-PTS-001A: Relaxed Boundary PTS (fallback)

> If INV-BOUNDARY-PTS-001 cannot be met due to encoder or muxer
> constraints, the first video PTS of the next block MUST be within
> ±1 × `frame_duration_90k` of `boundary_pts_90k`.
>
> ```
> |first_video_pts(block[N]) - boundary_pts_90k| <= frame_duration_90k
> ```

**Status:** **NOT active.**  INV-BOUNDARY-PTS-001 (zero tolerance) is
the default.  This variant exists only as a documented fallback.
Activating 001A requires updating this contract with written
justification for why zero tolerance is unachievable.

---

### INV-BOUNDARY-PTS-002: PTS Monotonicity Across Boundaries

> Video PTS MUST be strictly monotonically increasing across the entire
> session.  No backward PTS jump may occur at a block boundary or at
> any other point within a session.
>
> ```
> For all consecutive video frames i, i+1 in presentation order:
>     pts(frame[i+1]) > pts(frame[i])
> ```

**Rationale:** A backward PTS jump causes decoder flush, visible glitch,
and potential player desync.

---

### INV-BOUNDARY-PTS-003: Continuity Across Boundaries

> There MUST be no discontinuity gap or overlap in video PTS at a block
> boundary.  The first video PTS of the next block MUST be exactly one
> `frame_duration_90k` after the last video PTS of the previous block.
>
> ```
> first_video_pts(block[N+1]) == last_video_pts(block[N]) + frame_duration_90k
> ```
>
> **Presentation order:** "first" and "last" refer to presentation order
> (by PTS value), not emission or decode order.  If B-frames are present,
> decode order may differ from presentation order.  This invariant applies
> to presentation-order PTS values exclusively.

**Rationale:** A gap inserts silence or black frames; an overlap causes a
frame drop.  Both produce visible artifacts at block transitions.

---

### INV-BOUNDARY-PTS-004: Stream-Time Truth

> This contract defines **stream-time truth**.  Validation is performed
> exclusively by parsing TS/PES timestamps from the output byte stream.
> It does not depend on:
>
> - Client-side buffering or playback state
> - Wall-clock timing or NTP
> - Internal engine counters or log messages
>
> The authoritative record is the PTS value in the PES header of the
> emitted MPEG-TS packets.

**Rationale:** Stream-time truth is observable, reproducible, and
independent of playback environment.  Any test or monitoring tool can
validate compliance by parsing the TS output alone.

---

### INV-BOUNDARY-PTS-005: Integer-Only PTS Derivation

> Boundary PTS MUST be derived exclusively from integer arithmetic:
>
> ```
> boundary_pts_90k = boundary_frame_index * frame_duration_90k
> ```
>
> where both `boundary_frame_index` and `frame_duration_90k` are integers.
> No floating-point arithmetic may participate in computing any boundary
> PTS value.
>
> `output_frame_index` is a session-wide monotonic integer counter.
> It is never reset, cast to float, or derived from wall-clock time.

**Rationale:** Floating-point arithmetic introduces representation error
that accumulates over long sessions.  Integer multiplication of frame
index by frame duration is exact for all practical session lengths
(2^63 ticks at 90kHz ≈ 3.25 million years).

---

## Scope

These invariants apply to **every block boundary** within a playout
session driven by BlockPlanProducer.  They do not apply to:

- **Session start**: PTS epoch is implementation-defined but must be
  consistent with INV-BOUNDARY-PTS-001 at `output_frame_index = 0`.
- **Session teardown**: The final partial block before shutdown is
  excluded.
- **Legacy Phase8AirProducer paths**: Not covered by this contract.

---

## Constraints

### C1: No Wall-Clock Coupling

Boundary PTS is a function of `output_frame_index` and `output_fps`
only.  Wall-clock jitter, scheduling delays, or encoder latency MUST
NOT affect boundary PTS values.

### C2: No PTS Reset at Block Boundary

`output_frame_index` and PTS continue monotonically across block
boundaries.  There is no PTS reset, wrap-around compensation, or MPEG-TS
discontinuity indicator at a block switch.

### C3: Encoder Flush Discipline

If the encoder requires flushing at a block boundary, all flushed
frames MUST carry PTS values that satisfy INV-BOUNDARY-PTS-002 and
INV-BOUNDARY-PTS-003.  No flush may produce a PTS outside the expected
monotonic sequence.

---

## Required Tests

**File:** `pkg/core/tests/contracts/runtime/test_boundary_pts_alignment.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_frame_duration_90k_is_integer_for_standard_rates` | 005 | `frame_duration_90k` is exact integer for 30, 25, 24, 60, 29.97 fps. |
| `test_frame_duration_90k_rejects_non_integer` | 005 | fps values yielding non-integer `frame_duration_90k` are rejected. |
| `test_boundary_pts_exact_at_block_start` | 001 | For a sequence of block boundaries, first PTS equals `boundary_frame_index * frame_duration_90k`. |
| `test_boundary_pts_zero_tolerance` | 001 | Even ±1 tick deviation from `boundary_pts_90k` is a violation. |
| `test_pts_monotonic_across_single_boundary` | 002 | PTS strictly increases across one block transition. |
| `test_pts_monotonic_across_many_boundaries` | 002 | PTS strictly increases across 100+ block transitions. |
| `test_pts_continuity_no_gap` | 003 | `next_block_first_pts == prev_block_last_pts + frame_duration_90k` (no gap). |
| `test_pts_continuity_no_overlap` | 003 | `next_block_first_pts` is not less than `prev_block_last_pts + frame_duration_90k` (no overlap). |
| `test_boundary_pts_integer_only` | 005 | Boundary PTS computation uses only integer operands and produces integer result. |
| `test_boundary_pts_no_float_contamination` | 005 | Injecting float into boundary computation is rejected or produces identical integer result. |
| `test_pts_independent_of_wall_clock` | 004, C1 | Boundary PTS is identical regardless of wall-clock delays between blocks. |
| `test_no_pts_reset_at_boundary` | C2 | `output_frame_index` continues across boundary; no reset to 0. |
| `test_long_session_no_drift` | 001, 005 | After 10,000+ blocks, boundary PTS matches `frame_index * frame_duration_90k` exactly. |
