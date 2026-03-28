# INV-PRODUCTION-BOUNDARY-001 — Production Modules Contain Only Production Code

## Statement
Production modules may not contain mocks, test fixtures, test harnesses, or
abstract protocol definitions that exist solely for test use.

## Mandatory Placement
- Mocks/fakes/stubs: `tests/fixtures/<domain>_fixtures.py`
- Abstract interface definitions (Protocols): `retrovue/runtime/protocols.py`
- Test harnesses: `tests/` directory only

## Forbidden Patterns
- `class MockXxx` in `pkg/core/src/retrovue/runtime/*.py`
- `class MockXxx` in `pkg/core/src/retrovue/scheduling/*.py`
- Any class named `Mock*`, `Fake*`, `Stub*`, or `Test*` in a production module
- A class that is only instantiated in tests, living in a production module

## Rationale
When mocks live in production modules, the boundary between what runs in
production and what runs in tests becomes invisible. Auditing production
behavior requires reading through test code. Mocks may silently activate
in production if a flag check is wrong or missing.

## Enforcement
- Code review: reject any PR placing a mock/fixture/harness in a production module.
- Static check: grep for `class Mock` in `src/retrovue/` (should return empty).

## Derived From
LAW-SIMPLICITY

## Added
2026-03-28 — Phase 7d (mock relocation sweep)
