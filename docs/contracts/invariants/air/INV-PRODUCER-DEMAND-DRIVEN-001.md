# INV-PRODUCER-DEMAND-DRIVEN-001

## Behavioral Guarantee

A producer MUST NOT advance decode beyond a bounded lookahead unless frames are being consumed by the tick loop. Decode progress is coupled to consumption. If no consumer is active and no imminent seam requires preparation, decode MUST idle.

## Authority Model

The tick loop is the sole time authority. Producers, buffers, and fill loops are subordinate to tick consumption. The fill loop MUST NOT run independently of demand.

## Boundary / Constraint

- Decode advancement MUST be driven by tick consumption or bounded seam-prep lookahead.
- If no consumer is pulling frames from a buffer, the fill loop MUST NOT continue decoding.
- Unbounded buffer growth without consumption is a violation.
- CPU consumed by decode MUST be proportional to output rate, not decode capacity.

## Violation

Fill loop decoding frames with no active consumer; buffer depth growing without consumption (`total_popped=0`); CPU burn from speculative decode; audio depth accumulating to tens of seconds with zero consumption.

## Derives From

`LAW-CLOCK`

## Required Tests

- `runtime/tests/contracts/BlockPlan/DemandDrivenProducerTests.cpp`

## Enforcement Evidence

TODO
