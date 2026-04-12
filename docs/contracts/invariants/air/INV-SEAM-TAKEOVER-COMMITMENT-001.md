# INV-SEAM-TAKEOVER-COMMITMENT-001

## Behavioral Guarantee

Once a seam transition is executed, the engine MUST commit to the new segment and MUST NOT re-evaluate pre-transition eligibility criteria for that segment. Eligibility gates apply only to segment transition decisions and MUST NOT influence emission after a segment has been activated.

## Authority Model

PipelineManager owns the transition decision and the post-transition commit. The tick loop emits frames from the active segment. After a swap, the active segment is authoritative — the eligibility gate that governed the transition is no longer relevant.

## Boundary / Constraint

- Pre-seam: eligibility is evaluated to decide whether to switch. This is the decision phase.
- Post-seam: eligibility MUST NOT be re-evaluated for the now-active segment. This is the commit phase.
- If the system re-evaluates eligibility after a swap and finds the now-active segment "ineligible" (because consumption reduced buffer depth), it MUST NOT revert to the previous segment or stall output.
- The two phases — decision and commit — MUST be clearly separated in the control flow.

## Violation

Post-swap eligibility re-evaluation causes the engine to defer, revert, or stall on a segment that was already activated; frame source oscillates between active and incoming after a committed swap; `v_src` flips from `incoming` to `active` after a seam transition has fired.

## Derives From

`INV-SEAM-CONTINUITY-GUARANTEED-001`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/BlockPlan/SeamContinuityGuaranteedTests.cpp`

## Enforcement Evidence

TODO
