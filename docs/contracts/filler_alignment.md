# Filler Alignment — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

---

## Overview

Filler alignment governs how a filler asset is positioned within a time gap in a scheduled block. A gap arises when primary content does not fill the block's grid allocation, or when no interstitial assets are available for a break opportunity.

Two alignment modes exist: `"start"` and `"end"`. The mode is a per-channel configuration property declared under `channel.filler.alignment` in the resolved configuration.

### Authority Boundary

This contract owns:
- The offset computation for filler segments based on alignment mode
- The looping behavior when a gap exceeds the filler asset's duration
- The statelessness requirement for end-aligned filler
- The determinism guarantee for both modes
- The segment representation requirements for filler in the playlog

This contract does NOT own:
- When filler is inserted (owned by `traffic_manager.md` and break detection)
- The filler asset itself (path, duration — owned by channel configuration)
- EPG visibility of filler (owned by `INV-EPG-FILLER-INVISIBLE-001`)
- Block-level duration conservation (owned by `INV-BLOCK-SEGMENT-CONSERVATION-001`)

---

## Configuration

```yaml
channel:
  filler:
    path: "/opt/retrovue/assets/filler.mp4"
    duration_ms: 3650000
    alignment: "start"    # "start" | "end"
```

The `alignment` field is optional. When omitted, the default is `"start"`.

---

## 1. Alignment Mode: `"start"`

### Behavior

Filler playback begins at the current wrapping offset and plays forward for the required gap duration. The wrapping offset advances across consecutive filler segments within a channel session, providing visual continuity. When the offset reaches the end of the filler asset, it wraps to the beginning.

### Offset Computation

Given:
- `gap_ms` — the duration to fill
- `filler_duration_ms` — the total duration of the filler asset
- `wrapping_offset_ms` — the accumulated offset from prior filler segments (initial value: 0)

The filler segment (or segments, if wrapping is required) MUST be produced as follows:

While `remaining_ms > 0`:
1. `playable_ms = min(remaining_ms, filler_duration_ms - wrapping_offset_ms)`
2. Emit a segment with `asset_start_offset_ms = wrapping_offset_ms` and `segment_duration_ms = playable_ms`
3. `wrapping_offset_ms = (wrapping_offset_ms + playable_ms) % filler_duration_ms`
4. `remaining_ms = remaining_ms - playable_ms`

### State

The wrapping offset is stateful within a channel session. It carries across consecutive filler segments and across consecutive breaks within the same block. This provides visual continuity: the filler does not restart from the beginning on every gap.

---

## 2. Alignment Mode: `"end"`

### Behavior

Filler playback MUST end exactly at the block seam. The filler asset is positioned so that its final frame coincides with the end of the gap. The viewer sees the closing portion of the filler, not the opening.

### Offset Computation — Gap Fits Within Filler

Given:
- `gap_ms` — the duration to fill
- `filler_duration_ms` — the total duration of the filler asset
- `gap_ms <= filler_duration_ms`

A single filler segment MUST be produced:
- `asset_start_offset_ms = filler_duration_ms - gap_ms`
- `segment_duration_ms = gap_ms`

### Offset Computation — Gap Exceeds Filler (Looping)

Given:
- `gap_ms > filler_duration_ms`

The gap MUST be filled with one or more full filler loops followed by a final partial segment:

1. Compute `full_loops = gap_ms // filler_duration_ms`
2. Compute `remaining_ms = gap_ms % filler_duration_ms`
3. If `remaining_ms > 0`: emit a segment with `asset_start_offset_ms = filler_duration_ms - remaining_ms` and `segment_duration_ms = remaining_ms`
4. Emit `full_loops` segments, each with `asset_start_offset_ms = 0` and `segment_duration_ms = filler_duration_ms`

The partial segment (step 3) MUST precede the full loops (step 4) in playback order. This ensures the final frame of the last full loop coincides with the block seam, and the filler asset's ending is what the viewer sees at the transition point.

### State

End-aligned filler is stateless. Each gap is processed independently. No wrapping offset is maintained across gaps. No offset from a prior filler segment influences the computation.

---

## 3. Determinism

Both alignment modes MUST be deterministic. Given identical inputs (`gap_ms`, `filler_duration_ms`, `alignment`, and — for `"start"` mode — `wrapping_offset_ms`), the output MUST be identical: same number of segments, same `asset_start_offset_ms` values, same `segment_duration_ms` values, in the same order.

No randomness, wall-clock reads, or external state may influence the computation.

---

## 4. Segment Representation

Every filler segment produced by either alignment mode MUST be represented as an explicit `ScheduledSegment` in the playlog with:

| Field | Requirement |
|-------|-------------|
| `segment_type` | MUST be `"filler"` |
| `asset_uri` | MUST reference the configured filler asset path |
| `asset_start_offset_ms` | MUST be the computed offset into the filler asset (integer ms) |
| `segment_duration_ms` | MUST be the computed playback duration (integer ms) |

All duration and offset values MUST be integer milliseconds. Float values MUST NOT be used.

---

## 5. Duration Conservation

The sum of all filler segment durations produced for a single gap MUST exactly equal `gap_ms`. No frames may be unaccounted for. No frames may overflow the gap.

This is a restatement of `INV-TRAFFIC-FILL-EXACT-001` applied to the filler alignment computation specifically. The alignment mode MUST NOT affect the total filled duration.

---

## 6. Interaction with Traffic Manager

The traffic manager (`traffic_manager.md`) owns the decision of when to invoke filler. This contract owns how filler segments are constructed once invoked. The traffic manager MUST pass the resolved `alignment` value to the filler construction logic. The traffic manager MUST NOT override, ignore, or default the alignment independently.

When `alignment` is `"start"`, the existing wrapping-offset filler loop behavior applies unchanged.

When `alignment` is `"end"`, the traffic manager MUST use the stateless end-aligned computation defined in §2.

---

## Invariants

| ID | Title |
|----|-------|
| INV-FILLER-ALIGNMENT-001 | Filler offset computation matches declared alignment mode |
| INV-FILLER-ALIGNMENT-DETERMINISTIC-001 | Same inputs produce identical filler segments |
| INV-FILLER-ALIGNMENT-END-STATELESS-001 | End-aligned filler carries no state across gaps |

---

## Required Tests

- `pkg/core/tests/contracts/test_filler_alignment.py`

---

## Enforcement Evidence

TODO
