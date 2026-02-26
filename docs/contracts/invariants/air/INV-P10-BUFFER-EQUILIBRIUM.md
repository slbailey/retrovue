# INV-P10-BUFFER-EQUILIBRIUM

## Behavioral Guarantee
Buffer depth remains bounded and oscillates around target. Neither unbounded growth nor steady-state drain to zero is permitted.

## Authority Model
Target depth (e.g. default 3) and range [1, 2N] define the equilibrium band; decode gate and mux consumption enforce it.

## Boundary / Constraint
Depth MUST remain in range [1, 2N] during steady-state. Monotonic growth or drain to zero indicates a bug.

## Violation
Unbounded growth (memory leak) or steady-state drain to zero.

## Required Tests
TODO

## Enforcement Evidence
TODO
