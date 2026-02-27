# INV-AIR-MEDIA-TIME — Media Time Authority Contract

**Status:** Active
**Owner:** TickProducer (pkg/air/src/blockplan/TickProducer.cpp)
**Enforcement:** Runtime (PipelineManager tick loop)
**Test Suite:** MediaTimeContractTests

---

## Statement

Block execution and segment transitions MUST be governed by decoded media time,
not by output cadence, guessed frame durations, or rounded FPS math.

---

## Invariants

### INV-AIR-MEDIA-TIME-001 — Media Time Authority

For any block execution:

```
decoded_media_time(t) >= block_start_time
AND
decoded_media_time(t) <= block_end_time
```

Block completion MUST occur when:

```
decoded_media_time >= block_end_time
```

NOT when:

```
frames_decoded * rounded_frame_duration >= block_duration
```

**Rationale:** Integer-rounded frame durations accumulate error proportional to
frame count. For 23.976fps (true period 41.7084ms, rounded to 42ms), 36,000
frames accumulate +10.5 seconds of phantom time. This causes segment boundaries
to fire early and asset underrun checks to trigger before content is exhausted.

### INV-AIR-MEDIA-TIME-002 — No Cumulative Drift

Let:

```
T_decoded(n) = sum of actual decoded frame durations (from PTS or timebase)
T_expected(n) = n * (1 / input_fps)
```

Then for all n during a block:

```
|T_decoded(n) - T_expected(n)| <= epsilon
```

Where:

```
epsilon <= max(input_frame_duration)
```

Drift MUST NOT grow unbounded with n.

**Implementation:** After every successful decode, `block_ct_ms_` and
`next_frame_offset_ms_` are anchored to the decoder's PTS. Rounding error is
bounded to a single frame period and cannot accumulate across frames.

### INV-AIR-MEDIA-TIME-003 — Fence Alignment

At block completion:

```
|decoded_media_time - block_end_time| <= max(input_frame_duration)
```

Decoder EOF, block fence, and transition MUST converge within one output tick
window.

**Implementation:** `frames_per_block_` is computed as
`ceil(duration_ms * output_fps / 1000.0)` using exact floating-point arithmetic,
not truncated integer division. This ensures the output fence aligns with actual
block duration.

### INV-AIR-MEDIA-TIME-004 — Cadence Independence

Output cadence (OutputClock FPS) MUST NOT affect:

- block duration
- media consumption rate
- segment boundary timing

Cadence may affect frame repetition, but never media time advancement.

**Implementation:** `block_ct_ms_` and `next_frame_offset_ms_` are derived from
decoded PTS, which is independent of output cadence. The cadence system
(PipelineManager's `decode_budget_` / `cadence_ratio_`) controls *when* to decode,
but media time tracking after decode uses PTS, not output tick counting.

### INV-AIR-MEDIA-TIME-005 — Pad Is Never Primary

Padding or frame holding MUST NOT occur unless:

```
decoded_media_time >= block_end_time
```

Pad or hold logic is a safety fallback, not a timing mechanism.

**Implementation:** Asset underrun checks compare `next_frame_offset_ms_`
(PTS-anchored) against `asset_info->duration_ms`. Segment boundary checks
compare `block_ct_ms_` (PTS-anchored) against `boundary.end_ct_ms`. Both are
grounded in media time, preventing premature pad activation.

---

## Failure Paths

Failure paths (decode failure, pad injection, no-decoder) still use
`+= input_frame_duration_ms_` as a fallback. These are single-occurrence,
non-accumulating: once a failure triggers padding, the block is completing
anyway. The invariant applies to the success path where frames are decoded.

---

## Derivation

| Invariant | Derives From |
|-----------|-------------|
| INV-AIR-MEDIA-TIME-001 | Clock Law (MasterClock is sole time authority) |
| INV-AIR-MEDIA-TIME-002 | INV-P8-012 (Deterministic Replay) |
| INV-AIR-MEDIA-TIME-003 | INV-P8-003 (Contiguous Coverage) |
| INV-AIR-MEDIA-TIME-004 | INV-P8-006 (Producer Time Blindness) |
| INV-AIR-MEDIA-TIME-005 | Output Liveness Law (pad is fallback, not primary) |

---

## Error Budget

| Variable | Max error per frame | Source |
|----------|-------------------|--------|
| `block_ct_ms_` | 1ms (integer truncation of PTS us→ms) + `input_frame_duration_ms_` (look-ahead) | PTS anchoring |
| `next_frame_offset_ms_` | 1ms + `input_frame_duration_ms_` | PTS anchoring |
| `frames_per_block_` | 0 (exact floating-point computation) | `ceil(duration_ms * output_fps / 1000.0)` |

Error is bounded per-frame and never accumulates across frames.

---

## Test Scenarios

See `tests/contracts/BlockPlan/MediaTimeContractTests.cpp` for deterministic
verification using simulated decoder PTS (no video files required).

1. **23.976fps Long-Form Drift** — 30 minutes, verify no cumulative drift
2. **29.97fps Edge Case** — verify no oscillation or fence jitter
3. **30fps Native Control** — zero drift, no pad
4. **Fence Hold Safety** — EOF 1 tick early, verify hold behavior
