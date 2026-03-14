# Contract: FIVS Lookahead State Distinction (INV-FIVS-LOOKAHEAD-STATE-001)

**Classification:** Semantic contract (Layer 1)
**Parent:** [FIVS Decode Horizon](fivs_decode_horizon.md) · INV-FIVS-LOOKAHEAD-001
**Status:** Active

**Methodology:** Contracts define rules → tests enforce rules → implementation satisfies tests.

---

## 1. Purpose

The fill loop's parking and wake decisions depend on the **lookahead**:
the distance between the decoder's highest frame and the consumer's
requested frame. The lookahead computation produces two fundamentally
different "unknown" states that must be distinguished:

| State | Condition | Meaning |
|-------|-----------|---------|
| **consumer_not_started** | `consumer_requested_frame` is unset/invalid (-1) | Tick loop has not computed its first `selected_src`. Consumer position is unknown. |
| **decoder_behind** | `consumer_requested_frame` is valid AND `highest_decoded_frame < consumer_requested_frame` | Consumer is active but the decoder has fallen behind. Lookahead is negative. |

Conflating these two states causes the fill thread to park when the
decoder is behind the consumer — the exact situation where it must
decode urgently.

---

## 2. Invariant

**INV-FIVS-LOOKAHEAD-STATE-001:** The fill loop must distinguish between
`consumer_not_started` and `decoder_behind`.

### 2.1 Rules

1. **Bootstrap / size-based fallback is allowed ONLY when
   `consumer_requested_frame` is truly unset/invalid.**
   Before the tick loop computes its first `selected_src`, the fill
   thread has no timeline reference. Size-based parking (fill to
   `target_depth_frames_` then park) is the correct fallback.

2. **Once `consumer_requested_frame` is valid, refill decisions must
   be horizon-based only.**
   The fill thread must use `lookahead = highest_decoded - consumer_requested`
   to decide park vs decode. Store size is irrelevant for scheduling
   (it does not reflect timeline position).

3. **If lookahead < 0, the fill thread must decode immediately until
   the horizon is restored.**
   Negative lookahead means the decoder is behind the consumer. Every
   tick is a store miss. The fill thread must burst-decode without
   parking until `lookahead >= lookahead_target`.

4. **Store size must never be used as the scheduling decision for an
   active consumer, except for hard memory cap safety.**
   The only size-based check permitted when the consumer is active is
   `store_size >= hard_cap_frames_` (memory safety). All other parking
   decisions must use lookahead.

---

## 3. Violation

When the fill loop treats negative lookahead as "consumer not started"
and falls back to size-based parking:

- The store may still have `>= target_depth_frames_` from a previous
  burst decode.
- The size fallback says "no need for more."
- The fill thread stays parked while the consumer advances.
- `frame_gap` grows unboundedly negative.
- Result: freeze/jump playback (INV-FIVS-HORIZON violation).

---

## 4. Required Tests

| Test | Rule | Description |
|------|------|-------------|
| **test_consumer_unset_allows_size_fallback** | §2.1 R1 | When consumer position is unset (-1), the fill thread fills to `target_depth_frames_` then parks. Size-based parking is correct here. |
| **test_consumer_valid_positive_lookahead_parks** | §2.1 R2 | When consumer is valid and `lookahead >= lookahead_target`, the fill thread parks. Horizon is satisfied. |
| **test_consumer_valid_small_lookahead_decodes** | §2.1 R3 | When consumer is valid and `0 <= lookahead < lookahead_target`, the fill thread burst-decodes until horizon restored. |
| **test_consumer_valid_negative_lookahead_decodes** | §2.1 R3, R4 | When consumer is valid and `lookahead < 0` (decoder behind), the fill thread must decode immediately. Must NOT fall back to size-based parking even if store has `>= target_depth_frames_` frames. |

---

## 5. Relationship to Other Invariants

- **INV-FIVS-LOOKAHEAD-001**: Defines the lookahead mechanism. This
  contract refines the state machine that drives it.
- **INV-FIVS-HORIZON**: The outcome invariant. If this state distinction
  is wrong, the horizon invariant is violated.
