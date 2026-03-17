# INV-SEAM-PREP-DEADLINE-SAFE-001

## Behavioral Guarantee

For any scheduled seam, prep MUST begin early enough that readiness is guaranteed before seam consumption. If async prep cannot meet the deadline (time-to-seam is shorter than async prep completion time), AIR MUST choose a readiness-preserving path instead of risking continuity loss.

## Authority Model

PipelineManager owns prep timing decisions. The block structure (segment durations) is known at block activation. The seam frame for every segment is computable at activation time. If the time-to-seam for any segment is shorter than the minimum async prep completion time, prep MUST use a synchronous or pre-armed path.

## Boundary / Constraint

- At block activation, if any segment's duration is shorter than the minimum async prep completion window, prep for the segment following it MUST be completed synchronously or pre-armed before the tick loop begins.
- The system MUST NOT rely on async worker thread speed to meet a seam deadline. If async completion cannot be guaranteed, the synchronous path MUST be used.
- This applies regardless of execution speed (deterministic test harness or real-time playout).

## Violation

Seam frame reached with `seam_preparer_has_result=0` because async prep was armed but not completed in time; segment transition does not fire; output continues from exhausted segment instead of transitioning; black/corrupt frames after segment EOF.

## Derives From

`INV-SEAM-CONTINUITY-GUARANTEED-001`, `LAW-LIVENESS`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/SeamContinuityGuaranteedTests.cpp`

## Enforcement Evidence

TODO
