# INV-SEAM-SINGLE-EXECUTION-001 (Exactly one execution per declared boundary)

## Behavioral Guarantee

For every segment boundary declared in the active block plan, SeamController MUST issue exactly one seam execution during that boundary's on-air window. A seam MUST NOT be executed twice for the same declared boundary. A declared boundary MUST NOT elapse without a disposition being committed as either a successful execution or a missed-seam resolution per `INV-SEAM-MISSED-RESOLUTION-001`.

## Authority Model

SeamController maintains per-boundary execution state. Each declared boundary transitions through a monotonic state sequence that ends in `committed`. SeamController MUST mark a boundary `committed` once execution is issued; subsequent ticks MUST NOT reissue for the same boundary. Downstream enforcement surfaces MUST ignore any second execution command for an already-committed boundary.

## Boundary / Constraint

- Each declared segment boundary is identified by its position in the block plan's ordered segment sequence; `INV-SEAM-BOUNDARY-COUNT-MATCH-001` requires the discovered boundary set to cover the declared sequence.
- The per-boundary state sequence is monotonic and terminal at `committed`; reversal is prohibited.
- Valid dispositions at `committed` are `cutover`, `pad-bridge`, and `JIP`; see `INV-SEAM-MISSED-RESOLUTION-001` for the missed subset.
- A boundary whose fence tick is reached without a disposition committed MUST be surfaced as a missed-seam disposition; it MUST NOT silently elapse.

## Violation

Two seam execution commands issued for the same declared boundary; a boundary's fence tick elapsing with no disposition committed; a boundary reverted from `committed` by reissue; a boundary disposition lying outside `{cutover, pad-bridge, JIP}`.

## Derives From

`LAW-SWITCHING`, `INV-SEAM-BOUNDARY-COUNT-MATCH-001`

## Required Tests

- `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp`

## Enforcement Evidence

TODO
