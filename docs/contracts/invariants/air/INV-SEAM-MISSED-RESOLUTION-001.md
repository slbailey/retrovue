# INV-SEAM-MISSED-RESOLUTION-001 (Missed seams resolve to pad-bridge or JIP)

## Behavioral Guarantee

A seam is missed when its declared fence tick is reached AND the incoming segment is not swap-eligible under the active readiness rules. Every missed seam MUST resolve to exactly one of two dispositions: **pad-bridge** — output continues as pad until the incoming segment becomes eligible, at which point the seam executes; or **JIP** — the incoming segment begins at an offset aligned to the current tick position, bypassing the missed content. Hold-last-frame emission beyond the cadence repeat budget is not a valid resolution for a missed seam.

## Authority Model

SeamController observes the fence-tick condition and the readiness verdict for the incoming segment. When both indicate a miss, SeamController MUST select one of the two valid dispositions and emit the corresponding command. The chosen disposition is the boundary's single execution for the purposes of `INV-SEAM-SINGLE-EXECUTION-001`.

## Boundary / Constraint

- The set of valid dispositions for a missed seam is `{pad-bridge, JIP}` and no other.
- The chosen disposition MUST be communicated as a named command to the enforcement surface and as an observable event per `INV-SEAM-OBSERVABLE-001`.
- Cadence-budget-bounded hold-last-frame is permitted only as a pre-miss mechanism; once the fence tick is reached with the incoming segment ineligible, the boundary is missed and MUST resolve.
- Pad-bridge engagement is not an editorial choice — it is a continuity mechanism that preserves output until the Core-supplied successor becomes eligible; `INV-SEAM-EDITORIAL-EXTERNAL-001` applies.

## Violation

Continued hold-last-frame past the cadence repeat budget at a missed seam with no disposition selected; selection of a disposition outside `{pad-bridge, JIP}`; silent elapsing of a missed seam with no disposition command and no event; a missed seam resolution that is not communicated as an observable event.

## Derives From

`INV-CONTINUOUS-FRAME-AUTHORITY-001`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp`

## Enforcement Evidence

TODO
