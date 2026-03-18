# INV-CONTROL-PLANE-CADENCE

## Behavioral Guarantee
Control-plane (PAT/PMT, PCR) MUST be emitted on a cadence independent of media availability. The mux MUST NOT wait indefinitely for media before emitting control-plane. Stop() MUST complete in bounded time regardless of media queue state.

## Authority Model
`MpegTSOutputSink` owns this guarantee. Boot window emits TS immediately without waiting for media. Null-packet loop maintains transport cadence when media is absent.

## Boundary / Constraint
Control-plane MUST be emitted on schedule regardless of media. Stop() MUST complete within 3s when no media is fed. Running state MUST transition correctly: not-running before Start(), running after Start() (even with no media), not-running after Stop().

## Violation
Mux waiting indefinitely for media without emitting control-plane; Stop() exceeding 3s bound (deadlock); running state not managed without media. MUST be logged.

## Derives From
`LAW-LIVENESS`

## Required Tests
- `pkg/air/tests/contracts/BlockPlan/SharedInvControlPlaneCadenceContractTests.cpp` (`Compliant_StopWithNoMedia_CompletesWithinBound`) — Start() with no media, Stop() within 3s, no deadlock
- `pkg/air/tests/contracts/BlockPlan/SharedInvControlPlaneCadenceContractTests.cpp` (`Compliant_RunningStateManagedWithoutMedia`) — running state transitions correctly without media

## Enforcement Evidence
TODO
