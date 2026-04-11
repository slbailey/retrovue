# Legacy Tests

This directory contains all the previous test implementations that were moved here during the migration to contract-based testing.

## Structure

- `adapters/` - Tests for adapter implementations (importers, enrichers, etc.)
- `api/` - API endpoint tests
- `app/` - Application service tests
- `cli/` - CLI command tests (pre-contract)
- `contracts_legacy/` - Previous contract test implementations
- `domain/` - Domain model tests
- `fixtures/` - Test fixtures and sample data
- `runtime/` - Runtime system tests
- `test_*.py` - Individual test files
- `conftest.py` - Pytest configuration

## Migration Status

These tests are preserved for reference and potential reuse during the contract migration process.

### Reusable Patterns

Look for these patterns that can be adapted to new contract tests:

- **CLI Testing**: `cli/test_*_cli.py` files contain CLI testing patterns
- **Database Testing**: `app/` and `domain/` tests show database interaction patterns
- **Mocking Patterns**: Various test files show effective mocking strategies
- **Test Data**: `fixtures/` contains reusable test data

### Migration Notes

- Tests marked with `@pytest.mark.xfail` indicate incomplete implementations
- Tests with `pytest.skip()` indicate features not yet implemented
- Contract tests in `contracts_legacy/` show the previous contract testing approach

## Cleanup Plan

This directory will be removed once:

1. All useful patterns have been migrated to new contract tests
2. New contract tests provide equivalent or better coverage
3. Migration is verified complete

## See Also

- [Contract Tests](../contracts/) - New contract-based test structure
- [Contract Documentation](../../docs/contracts/README.md) - Contract standards
