# INV-CONTENT-DEFICIT-FILL

## Behavioral Guarantee
If the live path reaches EOF before the scheduled segment end, the gap (content deficit) MUST be filled with pad at real-time cadence until the boundary. Output liveness and TS cadence are preserved; the mux does not stall.

## Authority Model
Core declares the segment boundary. Sink/mux fills the gap at real-time rate. No stall for lack of content.

## Boundary / Constraint
Gap between EOF and boundary MUST be filled at real-time cadence. Mux MUST NOT stall or break TS cadence due to the content gap.

## Violation
Mux stalling or breaking TS cadence due to pre-boundary content gap; gap not filled at real-time cadence. MUST be logged.

## Required Tests
TODO

## Enforcement Evidence
TODO
