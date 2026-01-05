# Contract Enforcement Quick Reference

## For Developers

### Making Changes to Governed Interfaces

**❌ DON'T DO THIS:**

```python
# Changing behavior without updating contract
def add_enricher(...):
    # "Quick fix" - changes exit code from 1 to 2
    raise typer.Exit(2)  # BREAKS CONTRACT!
```

**✅ DO THIS INSTEAD:**

1. Edit `docs/contracts/resources/EnricherAddContract.md`
2. Update `tests/contracts/test_enricher_add_contract.py`
3. Update `tests/contracts/test_enricher_add_data_contract.py`
4. Update implementation to match contract
5. Run tests: `pytest tests/contracts --maxfail=1 --disable-warnings -q`

### Current Governed Interfaces

| Command                 | Status       | Contract                        | Tests                                                                                                   |
| ----------------------- | ------------ | ------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `retrovue enricher add` | **ENFORCED** | `docs/contracts/resources/EnricherAddContract.md` | `tests/contracts/test_enricher_add_contract.py`<br>`tests/contracts/test_enricher_add_data_contract.py` |

### CI Enforcement

- Contract tests run on every PR
- Any failure blocks the PR
- Command: `pytest tests/contracts --maxfail=1 --disable-warnings -q`

### Emergency Override Process

1. Create issue documenting emergency
2. Make minimal change
3. Create follow-up issue for contract update
4. Update contract within 48 hours
5. Document in commit messages

## For Reviewers

### Required Checks

- [ ] Contract document updated (if behavior changed)
- [ ] Contract tests updated (if behavior changed)
- [ ] All contract tests pass
- [ ] No direct implementation changes without contract updates

### Red Flags

- Changes to CLI flags without contract updates
- Changes to JSON output without contract updates
- Changes to error codes without contract updates
- "Quick fixes" or "small tweaks" to governed interfaces

## For Contributors

### Adding New Governed Interfaces

1. Create contract in `docs/contracts/`
2. Create contract tests in `tests/contracts/`
3. Implement command to pass tests
4. Update `tests/CONTRACT_MIGRATION.md`
5. Update this reference

### Testing Your Changes

```bash
# Run contract tests
pytest tests/contracts --maxfail=1 --disable-warnings -q

# Run specific contract
pytest tests/contracts/test_enricher_add_contract.py -v

# Run with coverage
pytest tests/contracts --cov=src/retrovue/cli/commands/enricher
```

## Key Files

- `tests/CONTRACT_MIGRATION.md` - Enforcement status
- `docs/contracts/CLI_CHANGE_POLICY.md` - Full policy
- `.github/workflows/test-workflow.yml` - CI configuration
- `docs/contracts/README.md` - Contract standards
