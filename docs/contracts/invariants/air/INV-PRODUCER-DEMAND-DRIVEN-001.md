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

### Steady-state reserve-floor outcome (cadence-shaped readiness)

Under steady-state content playout (not bootstrap/transition and not PAD-authoritative
ticks), producer service MUST maintain a minimum pre-pop audio reserve above one tick
of demand so ordinary cadence-shaped decoder-ready gaps do not deterministically cause
repeated underflow-silence on adjacent ticks.

Let:

- `due_samples_this_tick` = OutputClock-authoritative audio demand for tick `T`.
- `pre_pop_reserve_samples(T)` = `total_samples_pushed - total_samples_popped`
  at the pop boundary for tick `T`.

Required outcome:

- `pre_pop_reserve_samples(T) >= steady_min_reserve_samples`
- with default `steady_min_reserve_samples >= 2 * due_samples_this_tick`

This is an outcome contract, not an implementation prescription.

## Violation

Fill loop decoding frames with no active consumer; buffer depth growing without consumption (`total_popped=0`); CPU burn from speculative decode; audio depth accumulating to tens of seconds with zero consumption.
Repeated steady-state `AUDIO_UNDERFLOW_SILENCE` driven by ordinary cadence-shaped
decoder-ready gaps when reserve collapses below the minimum safe floor.

## Derives From

`LAW-CLOCK`

## Required Tests

- `runtime/tests/contracts/BlockPlan/DemandDrivenProducerTests.cpp`
- `runtime/tests/contracts/BlockPlan/AudioClockAuthorityContractTests.cpp` (`SteadyStateReserveFloor_CoversOneNoSupplyTickPair`)

## Enforcement Evidence

TODO
