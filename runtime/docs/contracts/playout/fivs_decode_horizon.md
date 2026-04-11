# Contract: FIVS Decode Horizon (INV-FIVS-HORIZON)

**Classification:** Semantic contract (Layer 1)
**Parent:** [Frame-Indexed Video Store](frame_indexed_video_store.md) · INV-FIVS-LOOKAHEAD-001
**Status:** Active

**Methodology:** Contracts define rules → tests enforce rules → implementation satisfies tests.

---

## 1. Purpose

The video decode pipeline must maintain a **forward decode horizon**
relative to the frame index requested by the playout clock.

When the tick loop requests frame N from the store, the decoder must
have already decoded at least `N + lookahead_target`. If the decoder
falls behind, the tick loop experiences store misses, which cause
frame repetition (freeze) and timeline discontinuities (jump).

This contract codifies the invariant that the decoder must always
stay ahead of the consumer by at least `lookahead_target` frames.

---

## 2. Definitions

| Term | Definition |
|------|------------|
| **highest_decoded_frame** | `FrameIndexedVideoStore::LatestIndex()` — the highest source_frame_index inserted into the store. |
| **consumer_requested_frame** | `consumer_selected_src_` — the source_frame_index the tick loop most recently requested (or will request next). |
| **lookahead_target** | Configured minimum number of frames the decoder must stay ahead of the consumer. |
| **frame_gap** | `highest_decoded_frame - consumer_requested_frame`. Positive = decoder ahead. Zero or negative = horizon failure. |
| **horizon** | The condition `frame_gap >= lookahead_target`. |

---

## 3. Invariant

**INV-FIVS-HORIZON:** The video decode pipeline must maintain:

```
highest_decoded_frame >= consumer_requested_frame + lookahead_target
```

Equivalently:

```
frame_gap >= lookahead_target
```

at all times during steady-state playback (after bootstrap completes).

### 3.1 Violations cause

- **Frame repetition:** Tick loop requests frame N, store does not have it,
  tick loop repeats frame N-1 (freeze).
- **Freeze/jump playback:** Repeated frames followed by decoder catching up
  causes visible freeze then fast-forward jump.
- **Negative frame_gap:** `highest_decoded_frame < consumer_requested_frame`
  means the decoder is behind the consumer — every frame request is a miss.
  Negative frame_gap in diagnostic logs (INV-HANDOFF-DIAG) is proof of
  horizon failure.

### 3.2 Pre-conditions

- The invariant applies after bootstrap phase completes (`FillPhase::kSteady`).
- During bootstrap, the decoder is filling from empty and the invariant
  is not yet established.
- The invariant assumes the decoder can sustain decode rate >= source fps
  (INV-DECODE-RATE-001).

---

## 4. Enforcement

The fill thread in `VideoLookaheadBuffer::FillLoop()` is responsible for
maintaining this invariant. When `frame_gap < lookahead_target`, the fill
thread MUST decode continuously (burst) without parking on the condvar.

The fill thread MUST NOT:
- Sleep between decodes when the horizon is not satisfied.
- Park on a condvar when `frame_gap < lookahead_target`.
- Use store size as the parking criterion (size does not reflect timeline position).

The fill thread MUST:
- Check `frame_gap` after every decode and continue immediately if below target.
- Only park when `frame_gap >= lookahead_target` (or memory safety cap reached).
- Wake immediately when `frame_gap` drops below `lookahead_target` (via condvar
  notification from `EvictBelow()` or `UpdateConsumerPosition()`).

---

## 5. Observability

| Event | When | Purpose |
|-------|------|---------|
| **FIVS_LOOKAHEAD_STATUS** | Every 100 frames pushed | Confirm `frame_gap` and horizon health. |
| **FIVS_HORIZON_VIOLATION** | `frame_gap < 0` on any store miss | Prove the decoder fell behind the consumer. |

---

## 6. Required Tests

| Test | Invariant proved | Description |
|------|------------------|-------------|
| **test_horizon_maintenance** | INV-FIVS-HORIZON | Simulate tick loop advancing `consumer_requested_frame`. After each advance, verify `highest_decoded_frame >= consumer_requested_frame + lookahead_target`. |
| **test_no_consumer_starvation** | INV-FIVS-HORIZON | Simulate concurrent decode and consume. After decoder fills to `lookahead_target`, every `Get(requested_index)` must return the requested frame (not nullopt, not a stale frame). |
| **test_negative_gap_detection** | INV-FIVS-HORIZON | Insert frames, advance consumer past the highest decoded frame. Verify `frame_gap < 0`. This proves the diagnostic can detect horizon failure. |

---

## 7. Relationship to INV-FIVS-LOOKAHEAD-001

INV-FIVS-LOOKAHEAD-001 specifies that the fill thread's parking decision
is driven by timeline lookahead (not store size). INV-FIVS-HORIZON is the
**consequence**: if the fill thread correctly uses lookahead-driven parking,
then the decode horizon is maintained. If the horizon is violated, either:

1. The fill thread is not burst-decoding when `frame_gap < lookahead_target`, or
2. The decoder cannot sustain source fps (INV-DECODE-RATE-001 violation), or
3. The condvar wake path is broken (fill thread sleeps despite low lookahead).

INV-FIVS-HORIZON is the **observable proof** that INV-FIVS-LOOKAHEAD-001 is
working correctly. The lookahead contract defines mechanism; the horizon
contract defines the required outcome.
