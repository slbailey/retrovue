# CLI Contract Tests

This directory contains contract tests for the RetroVue CLI implementation against the documented interface in `docs/contracts/README.md`.

## Test Structure

- `test_source_cli.py` - Tests for `retrovue source` commands
- `test_collection_cli.py` - Tests for `retrovue collection` commands
- `test_ingest_cli.py` - Tests for `retrovue ingest` commands
- `test_enricher_cli.py` - Tests for `retrovue enricher` commands
- `test_producer_cli.py` - Tests for `retrovue producer` commands
- `test_channel_cli.py` - Tests for `retrovue channel` commands
- `utils.py` - Test utilities for CLI testing

## Test Status

### ✅ PASSING (16 tests)

- Source commands are fully implemented and working
- Channel commands have basic CRUD operations working
- Help system works correctly with type-specific help

### ❌ XFAIL (29 tests)

- Enricher commands completely missing
- Producer commands completely missing
- Collection commands missing (partial implementation under source)
- Ingest command not registered in main CLI
- Channel commands missing enricher attachment features

### ⏭️ SKIPPED (17 tests)

- Destructive commands (remove/delete operations)
- Commands that would mutate real data
- Behavior validation tests

## CI Integration

The GitHub Actions workflow (`.github/workflows/test-workflow.yml`) runs these tests with:

- **Python 3.11 and 3.12** matrix testing
- **Linting** with ruff and mypy
- **CLI contract tests** with pytest

### Expected Behavior

- **✅ PASSING tests** = Green (implementation matches contract)
- **❌ XFAIL tests** = Green (known debt, expected to fail)
- **⏭️ SKIPPED tests** = Green (intentionally skipped)

### When XFAIL Tests Start Passing

When implementation is completed and XFAIL tests start passing, they will:

1. **Pass** (turn green)
2. **Stay green** (no longer marked as XFAIL)
3. **Enforce the contract** going forward

## Running Tests Locally

```bash
# Run all CLI contract tests
pytest tests/cli/test_*_cli.py -v

# Run specific command group
pytest tests/cli/test_source_cli.py -v

# Run with detailed output
pytest tests/cli/test_*_cli.py -v --tb=short
```

## Test Philosophy

These tests encode the **documented contract** as the source of truth. They will:

- **Force acknowledgment** of implementation gaps via XFAIL markers
- **Prevent regression** once features are implemented
- **Guide implementation** with clear TODO comments
- **Enforce compliance** with the documented interface

The tests are designed to be **deterministic** and **CI-ready**.
