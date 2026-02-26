# INV-P10-BACKPRESSURE-SYMMETRIC

## Behavioral Guarantee
Audio and video advance together; neither stream leads the other by more than one frame duration. When backpressure is applied, both streams are throttled symmetrically.

## Authority Model
Single backpressure signal applies to both audio and video decode gates.

## Boundary / Constraint
A/V delta MUST remain ≤ one frame duration at all times. When one stream is blocked, the other MUST also block.

## Violation
A/V delta exceeds one frame duration; one stream decoding while the other is blocked.

## Required Tests
TODO

## Enforcement Evidence
TODO
