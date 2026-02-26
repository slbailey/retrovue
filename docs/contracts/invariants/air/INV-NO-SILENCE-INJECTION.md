# INV-NO-SILENCE-INJECTION

## Behavioral Guarantee
No synthetic silence is injected during steady-state. Producer audio is the only audio source once steady-state has begun.

## Authority Model
Steady-state entry disables silence injection; producer is the sole audio source.

## Boundary / Constraint
Silence injection MUST be disabled when steady-state begins. MUST NOT inject silence or fabricate audio packets during steady-state.

## Violation
Injected silence after steady-state has begun.

## Required Tests
TODO

## Enforcement Evidence
TODO
