# INV-SINK-NO-DEADLOCK

## Behavioral Guarantee
System MUST NOT enter circular wait. Forward progress must be possible without requiring a terminal state to break the cycle.

## Authority Model
Design of mux, producers, and buffers must avoid circular dependencies that block all progress.

## Boundary / Constraint
No configuration or steady-state condition may result in all participants waiting on each other with no unblock path.

## Violation
No forward progress without terminal state; circular wait detected.

## Required Tests
TODO

## Enforcement Evidence
TODO
