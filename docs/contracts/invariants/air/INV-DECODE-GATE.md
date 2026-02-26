# INV-DECODE-GATE

## Behavioral Guarantee
Decode is **admitted** only when buffer has capacity (at least one slot free). The admission condition is binary: capacity present or not. No hysteresis — resume condition MUST equal admission condition (one slot free).

## Authority Model
Downstream buffer capacity defines the gate; the rule is the condition under which decode is permitted.

## Boundary / Constraint
Decode is permitted if and only if at least one slot is free. Hysteresis (e.g. low-water / high-water thresholds that delay resume after capacity returns) MUST NOT be used.

## Violation
Decoding when no capacity exists (gate closed). Using hysteresis so that resume differs from the admission condition.

## Required Tests
TODO

## Enforcement Evidence
TODO
