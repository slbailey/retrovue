# SegmentTransitionContract

**Component**: Playout Engine (Python Core ↔ C++ AIR)
**Version**: 1.0.0
**Status**: Active
**Copyright (c) 2025 RetroVue**

## Overview

This contract governs fade-based transitions at ad-break insertion points (breakpoints)
within a program block. Two classes of breakpoints exist in RetroVue:

### Breakpoint Classes

#### First-Class Breakpoints
- **Source**: Chapter markers embedded in the media file (`chapter_markers_ms`)
- **Characteristics**: Deliberate editorial cuts placed at natural scene boundaries
- **Transition policy**: `TRANSITION_NONE` — clean cuts are appropriate here

#### Second-Class Breakpoints
- **Source**: Computed by dividing episode duration evenly when no chapter markers exist
  (`episode_duration_ms / (num_breaks + 1)`)
- **Characteristics**: Arbitrary, may fall mid-scene
- **Transition policy**: `TRANSITION_FADE` — fade to/from black softens the jarring cut

## TransitionType Enum

```proto
enum TransitionType {
  TRANSITION_NONE = 0;   // Clean cut (first-class breakpoints, default)
  TRANSITION_FADE = 1;   // Linear fade to/from black and silence
}
```

## Segment Transition Fields

Added to `BlockSegment` proto message:

| Field | Number | Type | Description |
|-------|--------|------|-------------|
| `transition_in` | 8 | `TransitionType` | Fade applied at segment start |
| `transition_in_duration_ms` | 9 | `uint32` | Duration of fade-in in milliseconds |
| `transition_out` | 10 | `TransitionType` | Fade applied at segment end |
| `transition_out_duration_ms` | 11 | `uint32` | Duration of fade-out in milliseconds |

## Fade Behavior

### Video (YUV420P)
- Y plane: multiply each sample by `alpha` (fades toward 0 = black)
- U plane: blend each sample toward 128 (neutral chroma) by factor `(1 - alpha)`
- V plane: blend each sample toward 128 (neutral chroma) by factor `(1 - alpha)`

For fade-out: `alpha` decreases linearly from 1.0 → 0.0 over `transition_out_duration_ms`
For fade-in: `alpha` increases linearly from 0.0 → 1.0 over `transition_in_duration_ms`

### Audio (S16 Interleaved)
- Multiply each int16_t sample by `alpha`
- Amplitude decreases to silence (0) on fade-out; increases from silence on fade-in

## Default Duration

- **Default**: 500ms (configurable via `fade_duration_ms` parameter on `expand_program_block()`)
- Stored per-segment so each segment transition can have a distinct duration
- Python expander passes `fade_duration_ms` through to all second-class breakpoint segments

## Application Rules

Only second-class breakpoints receive transitions:

1. **Content segment ending at a second-class breakpoint**:
   → `transition_out = TRANSITION_FADE`, `transition_out_duration_ms = fade_duration_ms`

2. **Content segment starting after a filler that followed a second-class breakpoint**:
   → `transition_in = TRANSITION_FADE`, `transition_in_duration_ms = fade_duration_ms`

3. **Content segments at first-class breakpoints**: `TRANSITION_NONE` on both ends

## Invariants

### INV-TRANSITION-001: Source Fidelity
First-class breakpoints (from `chapter_markers_ms`) MUST receive `TRANSITION_NONE`.
Second-class breakpoints (computed interval division) MUST receive `TRANSITION_FADE`.
There is no override mechanism — the classification is deterministic from source data.

### INV-TRANSITION-002: Symmetry
If a content segment has `transition_out = TRANSITION_FADE`, the content segment
immediately following the filler at that breakpoint MUST have `transition_in = TRANSITION_FADE`
with the same `fade_duration_ms`. Filler segments themselves carry no transition fields.

### INV-TRANSITION-003: Duration Bounds
`transition_in_duration_ms` and `transition_out_duration_ms` MUST be:
- Zero when `transition_type = TRANSITION_NONE`
- Greater than zero and less than the segment duration when `transition_type = TRANSITION_FADE`

### INV-TRANSITION-004: Frame-Accurate Application
The C++ engine MUST apply the fade using segment-relative CT (content time), not
wall-clock time. The fade boundary is computed as:
- Fade-out start: `segment.end_ct_ms - transition_out_duration_ms`
- Fade-in end: `segment.start_ct_ms + transition_in_duration_ms`

Alpha at frame with `ct_before`:
- Fade-out: `alpha = (end_ct_ms - ct_before) / transition_out_duration_ms`
- Fade-in: `alpha = (ct_before - start_ct_ms) / transition_in_duration_ms`
Both clamped to [0.0, 1.0].

### INV-TRANSITION-005: No First-Class Mutation
C++ AIR MUST NOT modify the transition classification. It applies whatever Core
declares. Core (Python) is the sole authority for breakpoint classification.
