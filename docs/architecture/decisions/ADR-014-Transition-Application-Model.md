# Transition Application Model

**Status:** Proposed
**Date:** 2026-02-28
**Owner:** AIR (frame production path)
**Related:** ADR-013 (Seam Resolution Model)

## Scope

This document defines the contract semantics for visual and audio transitions
at segment boundaries. It governs how transition effects (fade-in, fade-out)
are applied to emitted frames. It does not govern frame authority, segment
selection, or seam resolution — those are defined in ADR-013.

## Definitions

**transition_in:** A per-segment declaration that the segment's initial frames
undergo a ramp from full attenuation (black + silence) to full presence over a
specified duration. Declared by Core in the playout plan. AIR applies it; AIR
never overrides, invents, or suppresses it.

**transition_out:** A per-segment declaration that the segment's final frames
undergo a ramp from full presence to full attenuation over a specified duration.
Same ownership rules as transition_in.

**seg_ct:** Per-segment elapsed time in milliseconds. Defined as the difference
between the frame's block-level continuity time and the segment boundary start
time. seg_ct = 0 at the first frame of the segment. seg_ct advances
monotonically within a segment and does not reset except at segment boundaries.

**alpha:** A scalar in [0, 1] representing the visual and audio presence of a
frame. alpha = 0 is fully attenuated (black video, silent audio). alpha = 1 is
fully present (unmodified content). Alpha is a pure function of seg_ct, the
transition specification, and the segment duration. It depends on no other
state.

**production path:** Any code path that produces a frame for eventual emission.
This includes initial decoding (priming) and subsequent decoding. All
production paths are subject to transition semantics without exception.

## Alpha Computation

Alpha is a pure function. Given a segment with duration S (ms), transition_in
specification (type, duration D_in), and transition_out specification (type,
duration D_out):

### Fade-in alpha

If transition_in = Fade(D_in) and D_in > 0:

    alpha_in(seg_ct) =
        0                           if seg_ct <= 0
        seg_ct / D_in               if 0 < seg_ct < D_in
        1                           if seg_ct >= D_in

If transition_in = None: alpha_in(seg_ct) = 1 for all seg_ct.

### Fade-out alpha

If transition_out = Fade(D_out) and D_out > 0, with fade_start = S - D_out:

    alpha_out(seg_ct) =
        1                           if seg_ct < fade_start
        1 - (seg_ct - fade_start) / D_out    if fade_start <= seg_ct < S
        0                           if seg_ct >= S

If transition_out = None: alpha_out(seg_ct) = 1 for all seg_ct.

### Combined alpha

    alpha(seg_ct) = min(alpha_in(seg_ct), alpha_out(seg_ct))

The min operator handles the degenerate case where a segment is shorter than
D_in + D_out. In that case the fade-in and fade-out regions overlap, and the
frame receives the more attenuated of the two values. This is the correct
behavior: a very short segment fades in and out without ever reaching full
presence.

### Transition type extensibility

Only Fade and None are defined. Additional transition types (if ever introduced)
must define their own alpha function with the same signature: a pure function of
seg_ct, transition parameters, and segment duration.

## Placement of Transition Semantics

Transition application is part of **frame production**. It is not part of frame
selection and not part of seam resolution.

### Rationale

- **Frame selection** determines which segment's content occupies a tick. It
  answers: "whose frame is this?" Frame selection is governed by authority
  invariants (ADR-013). Transition semantics have no bearing on which segment
  is selected.

- **Seam resolution** determines when and whether authority transfers between
  segments. It answers: "does the swap commit?" Seam resolution is governed by
  the same-tick authority rule (ADR-013). A frame's alpha value has no bearing
  on swap eligibility.

- **Frame production** transforms decoded content into the frame that will be
  encoded and emitted. It answers: "what does this frame look like?" Transition
  alpha is applied here — after decode, before encode. This is the sole
  location where transition semantics act.

The three concerns are orthogonal. A frame may satisfy all authority invariants
(origin(T) = active(T)) while violating transition invariants (wrong alpha),
or vice versa. They are verified independently.

## First-Frame Obligation

The first emitted frame of a segment (seg_ct = 0) MUST satisfy transition
semantics.

If transition_in = Fade(D) with D > 0, then at seg_ct = 0:

    alpha(0) = 0

The first emitted frame is fully attenuated: black video and silent audio.

There is no exemption for the first frame. The transition contract is defined
over the continuous domain [0, S] and discretized by the frame rate. seg_ct = 0
is a valid input to the alpha function and must produce the correct output.

A first frame emitted at full presence when transition_in = Fade(D > 0) is a
transition invariant violation regardless of how the frame was produced.

## Priming Path Rule

All production paths — including priming — MUST apply transition semantics.
There is no priming bypass.

A primed frame is a produced frame. It will be emitted at some tick T with some
seg_ct value. The alpha for that seg_ct must be applied before the frame
enters any buffer or queue. A primed frame that bypasses transition application
will emit at the wrong alpha, violating the transition contract.

This rule is unconditional. There is no "priming is just preparation" exemption.
If a frame will be emitted, it must carry the correct alpha at the time of
emission.

## Post-Encode Alpha Mutation

Post-encode alpha mutation is never allowed.

Alpha is applied to raw frame data (decoded pixels and PCM audio) as a
destructive operation. Once the frame is encoded, the alpha is baked into the
compressed representation. There is no mechanism to adjust alpha after encode,
and no such mechanism shall be introduced.

This is distinct from ADR-013's post-encode origin mutation (the frame-authority
vacuum exception). Origin is metadata — a tag indicating which segment produced
the frame. Alpha is content — the actual pixel and sample values. Origin can be
restamped without touching encoded data. Alpha cannot.

| Concern | Post-encode mutation | Governed by |
|---|---|---|
| Origin (authority metadata) | Permitted under vacuum exception only | ADR-013 |
| Alpha (frame content) | Never permitted | This document |

## Invariant Separation

Authority invariants and transition invariants are independent verification
surfaces. Neither subsumes the other.

### Authority invariants (ADR-013)

These verify that the frame emitted at tick T was produced by the segment that
holds authority at tick T.

    origin(T) = active(T)

A violation means the wrong segment's content was emitted. This is an authority
error. The frame's visual appearance is irrelevant to this check.

### Transition invariants (this document)

These verify that the frame emitted at tick T carries the correct alpha for its
seg_ct value.

    observed_alpha(T) = alpha(seg_ct(T))

A violation means the frame has the wrong visual/audio attenuation. The frame
may have correct authority (origin = active) but incorrect appearance. This is a
transition error.

### Independence

A frame can be:
- Authority-correct and transition-correct (nominal)
- Authority-correct and transition-incorrect (visual defect, no authority error)
- Authority-incorrect and transition-correct (authority error, no visual defect)
- Authority-incorrect and transition-incorrect (both errors)

Each class of violation is diagnosed and reported independently. Authority
violations are governed by ADR-013 and its invariants. Transition violations
are governed by this document.

## PAD Segment Transitions

PAD segments produce synthetic frames (black video, silent audio). These frames
are already at alpha = 0 by construction. Applying a fade-in or fade-out to a
PAD segment is a no-op: attenuating black and silence produces black and
silence. PAD frames are exempt from transition application as an optimization,
not as a semantic exception. The observable output is identical whether
transition alpha is applied or not.

If a future PAD implementation produces non-black frames (e.g., slate, logo),
this exemption must be revisited.

## Constraints on Core

Core declares transition specifications per segment. The following constraints
apply to those declarations:

1. Transition durations MUST be non-negative.
2. Transition durations SHOULD be shorter than the segment duration. If
   D_in + D_out > S, the segment never reaches full presence. This is
   semantically valid but likely unintended. Core may warn but AIR will
   faithfully execute it.
3. Transition specifications are immutable once the segment enters the
   execution horizon. AIR reads them at segment preparation time and does not
   re-query.

## Summary of Obligations

| Rule | Statement |
|---|---|
| Alpha is a pure function | alpha depends only on seg_ct, transition spec, and segment duration |
| Transition is production-phase | Applied after decode, before encode, during frame production |
| First frame is not exempt | seg_ct = 0 produces alpha = 0 when fade-in is declared |
| Priming is not exempt | All production paths apply transition semantics |
| Post-encode alpha mutation is forbidden | Alpha is baked into raw frame data before encode |
| Authority and transition are independent | origin(T) = active(T) and alpha correctness are separate invariants |
| PAD exemption is observational | PAD is already at alpha = 0; exemption is optimization, not semantics |
