# INV-P10-PRODUCER-THROTTLE

## Behavioral Guarantee
When the decode gate **denies** (no capacity), the producer MUST block or yield. It MUST NOT continue generating or enqueueing frames.

## Authority Model
The gate (per RULE-P10-DECODE-GATE) determines admission. This invariant defines required behavior when admission is denied.

## Boundary / Constraint
When capacity is unavailable, producer MUST block or yield. Producer MUST NOT continue producing frames while the gate is closed.

## Violation
When capacity is unavailable, producer continues generating or enqueueing frames (ignoring denial).

## Required Tests
TODO

## Enforcement Evidence
TODO
