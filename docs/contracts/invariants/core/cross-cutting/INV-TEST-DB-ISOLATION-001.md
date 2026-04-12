# INV-TEST-DB-ISOLATION-001

## Behavioral Guarantee

The test suite MUST NOT execute against a production database. Test infrastructure MUST fail immediately if `TEST_DATABASE_URL` is not explicitly configured.

## Authority Model

`server/tests/conftest.py` `_force_test_db` fixture is the sole enforcement point for test database routing.

## Boundary / Constraint

The `_force_test_db` fixture MUST raise a fatal error if `TEST_DATABASE_URL` is not set. Silent fallback to `DATABASE_URL` MUST NOT occur. No pytest session may proceed without an explicit test database target.

## Violation

- Test session starts and executes queries against `DATABASE_URL` because `TEST_DATABASE_URL` was absent.
- Test-created records (sources, containers, assets) appear in the production database.

## Required Tests

- `server/tests/test_conftest_guard.py`

## Enforcement Evidence

TODO
