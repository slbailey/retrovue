# INV-SEAM-EDITORIAL-EXTERNAL-001 (SeamController makes no editorial decisions)

## Behavioral Guarantee

SeamController MUST NOT choose, reorder, substitute, or originate the content that follows a seam. The identity of the successor segment is supplied by Core editorial state through the block plan. SeamController consumes that identity as an input and decides only when and how the transition executes — never what.

## Authority Model

Core owns editorial sequencing. The block plan carries the declared successor segment identity across the Core → AIR boundary. SeamController's decision space is bounded to `{cutover, pad-bridge, JIP}` — timing and disposition only. Successor identity is read, not written, by SeamController.

## Boundary / Constraint

- The successor segment identity for every declared boundary MUST originate in Core's block plan.
- SeamController MUST NOT reroute a scheduled transition to a successor not declared in the active block plan.
- SeamController MUST NOT substitute content of its own selection for a Core-declared segment, including at missed seams.
- Pad-bridge engagement at a missed seam (per `INV-SEAM-MISSED-RESOLUTION-001`) is a continuity mechanism, not editorial substitution; pad is not treated as content by this invariant.

## Violation

SeamController emits a command whose successor segment identity is not present in the active block plan; a scheduled transition rerouted to skip or replace a Core-declared segment with an alternative; a missed seam "resolved" by selecting arbitrary content rather than pad-bridge or JIP over the declared successor.

## Derives From

`LAW-RUNTIME-AUTHORITY`, `LAW-CONTENT-AUTHORITY`

## Required Tests

- `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp`

## Enforcement Evidence

TODO
