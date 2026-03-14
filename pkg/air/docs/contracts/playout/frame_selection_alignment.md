# Contract: Frame Selection Alignment

## Rule

The frame emitted on a playout tick must align with the scheduler's
selected source frame index.

The pipeline must never emit a frame that is ahead of the scheduler.

## Definitions

**selected_src**
: The frame index requested by the scheduler for this tick.

**actual_src_emitted**
: The frame index of the frame emitted to the encoder.

## Invariants

1. **actual_src_emitted <= selected_src**

2. If a real frame is emitted:
   **actual_src_emitted == selected_src**

3. If the frame is unavailable:
   PAD may be emitted.

4. Future frames must never be emitted.
   **actual_src_emitted > selected_src** is illegal.

## Rationale

The playout pipeline is clock-driven. The scheduler defines the
authoritative frame index. The decoder may run ahead, but the consumer
must align to the scheduler before emitting frames.

Allowing future frames causes timeline acceleration and playback drift.
