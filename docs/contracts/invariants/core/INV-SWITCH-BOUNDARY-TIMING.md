# INV-SWITCH-BOUNDARY-TIMING

## Behavioral Guarantee
A producer/source switch MUST complete no later than one frame duration after the declared schedule boundary.

## Authority Model
- Core declares the authoritative boundary timestamp.
- AIR executes the switch relative to that boundary.

## Boundary / Constraint
Switch completion time is measured against the declared boundary timestamp.
Frame duration is defined by the active output FPS.

## Violation
If switch completion time exceeds boundary + one frame duration, a violation MUST be logged.

## Required Tests
- `pkg/core/tests/contracts/test_inv_switch_boundary_timing.py` (Core declares boundary in protocol)
- `pkg/air/tests/contracts/DeadlineSwitchTests.cpp` (AIR executes switch within one frame of boundary)

## Enforcement Evidence
TODO
