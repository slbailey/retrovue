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
- `pkg/air/tests/contracts/Phase10PipelineFlowControlTests.cpp` (TEST_INV_SWITCH_READINESS_002_WriteBarrierNoDeadlock)

## Enforcement Evidence

- **Non-blocking output:** Output FD uses `O_NONBLOCK` — write path cannot block the render loop waiting on a slow consumer.
- **Atomic producer switching:** `OutputBus` performs atomic producer switching (no mutex contention between preview and live paths), eliminating lock-ordering hazards.
- **Single-threaded render loop:** `ProgramOutput` processes frames in a single-threaded render loop — no inter-thread circular wait is possible within the emission path.
- **Bounded buffers:** `VideoLookaheadBuffer` and `AudioLookaheadBuffer` have finite capacity with blocking push — producers yield rather than accumulate unbounded work that could starve downstream.
- Contract tests: `Phase10PipelineFlowControlTests.cpp` (`TEST_INV_SWITCH_READINESS_002_WriteBarrierNoDeadlock`) proves no deadlock under sustained load with concurrent producer switching.
