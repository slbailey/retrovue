# INV-NO-GHOST-METHODS-001 — No Ghost Method Stubs in Production Code

## Statement
No production module may contain unimplemented method stubs.

## Forbidden Patterns
- `def some_method(self, ...): pass`
- `def some_method(self, ...): raise NotImplementedError("TODO")`
- Any method whose entire body is a no-op, pass, or deferred TODO

## Rationale
Ghost scaffolding creates false API surface. It misleads future readers into believing
a capability exists, may cause silent no-op behavior in production, and violates the
single-authority principle by implying ownership without providing it.

## Enforcement
- Code review: reject any PR introducing a pass/TODO stub in a production module.
- Contract test: INV-NO-GHOST-METHODS-001 in tests/contracts/test_inv_no_ghost_methods.py

## Derived From
LAW-SIMPLICITY

## Added
2026-03-28 — Phase 5g (ghost prohibition sweep)
