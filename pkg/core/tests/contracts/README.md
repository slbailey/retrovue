# Contract Tests

This directory contains contract tests that enforce the behavioral contracts defined in `docs/contracts/`.

## Structure

Each contract has exactly two test files:

- `test_{noun}_{verb}_contract.py` - CLI behavior tests (B-# rules)
- `test_{noun}_{verb}_data_contract.py` - Data behavior tests (D-# rules)

## Naming Convention

Tests follow the pattern: `test_{domain}_{operation}_contract.py`

Examples:

- `test_enricher_add_contract.py` - Tests CLI behavior for `retrovue enricher add`
- `test_enricher_add_data_contract.py` - Tests data effects for `retrovue enricher add`
- `test_source_discover_contract.py` - Tests CLI behavior for `retrovue source discover`
- `test_source_discover_data_contract.py` - Tests data effects for `retrovue source discover`

## Contract Rules

Each test file MUST:

1. Reference specific contract rule IDs (B-# or D-#) in docstrings
2. Test exactly what the contract specifies
3. Not test behavior not defined in the contract
4. Provide bidirectional traceability between contracts and implementation

## Legacy Tests

All previous tests have been moved to `_legacy/` to preserve existing work while establishing the new contract-based testing structure.

## Migration Strategy

1. **Phase 1**: Move existing tests to `_legacy/` (✅ Complete)
2. **Phase 2**: Create contract tests one domain at a time
3. **Phase 3**: Migrate useful test patterns from `_legacy/` to new contract tests
4. **Phase 4**: Remove `_legacy/` when migration is complete

## See Also

- [Contract Documentation](../../docs/contracts/README.md) - Contract standards and patterns
- [Legacy Tests](_legacy/) - Previous test implementations
