# INV-SEAM-BOUNDARY-COUNT-MATCH-001

**Classification:** Derived enforcement invariant (diagnostic guardrail)

## Behavioral Guarantee

When a multi-segment block activates, the playout engine MUST discover sufficient segment-boundary metadata to make every segment in the block reachable by scheduled transition. Missing boundary discovery for any segment is a contract failure because the engine can strand playout on an earlier segment and fail continuity once that segment is exhausted.

## Authority Model

Core defines the block plan and its ordered segment sequence. AIR owns activation-time boundary discovery and transition preparation. AIR's discovered seam/boundary state MUST fully cover the segment sequence defined by the block plan.

## Boundary / Constraint

- At block activation, discovered boundary/transition metadata MUST cover the full ordered segment sequence in the block plan.
- AIR MUST reject or error-log any activation state that leaves one or more planned segments unreachable.
- The error log MUST identify the block, expected segment count, and discovered reachable transition/boundary count.

## Violation

A multi-segment block activates with incomplete discovered seam/transition state. Playout remains on an earlier segment, later segment transitions never fire, and output eventually degrades to black, corrupt, or undecodable frames after the active segment is exhausted.

## Derives From

`INV-SEAM-CONTINUITY-GUARANTEED-001`, `LAW-LIVENESS`, `LAW-DECODABILITY`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/SeamContinuityGuaranteedTests.cpp`

## Enforcement Evidence

TODO
