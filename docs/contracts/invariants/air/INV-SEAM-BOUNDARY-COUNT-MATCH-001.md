# INV-SEAM-BOUNDARY-COUNT-MATCH-001

## Behavioral Guarantee

When a multi-segment block activates, the playout engine MUST recognize and prepare transitions for every segment in the block. If the engine believes the block has fewer segments than it actually contains, segment transitions will not fire — the engine remains stuck on the first segment, eventually emitting black frames or corrupted output after that segment's content is exhausted.

## Authority Model

The playout engine owns segment boundary discovery at block activation. The block plan (from Core) defines the segment count. The engine's boundary computation MUST produce one boundary per segment.

## Boundary / Constraint

- At block activation, the number of discovered segment boundaries MUST equal the number of segments in the block plan.
- If a boundary count mismatch is detected, the engine MUST log an ERROR identifying the block, expected count, and actual count.
- A multi-segment block with only one discovered boundary will never transition past its first segment.

## Violation

Block activation produces fewer boundaries than segments; segment transition never fires for a multi-segment block; output remains on segment 0 after its EOF; black frames or invalid H.264 output (missing PPS) after first segment exhaustion.

## Derives From

`LAW-LIVENESS`, `LAW-DECODABILITY`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/BoundaryCountMatchTests.cpp`

## Enforcement Evidence

TODO
