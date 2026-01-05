# CLI Change Policy

> **This document is part of the RetroVue Contract System.**  
> For enforcement status, see `tests/CONTRACT_MIGRATION.md`.

This document establishes the governance policy for RetroVue CLI interfaces. Once a command is marked as **ENFORCED** in `tests/CONTRACT_MIGRATION.md`, it becomes a governed interface with strict change controls.

## Governed Interfaces

**Status Source:** Governed interfaces are listed in `tests/CONTRACT_MIGRATION.md`. See that document for the authoritative list of enforced contracts and their current status.

**Definition:** A governed interface is any command marked as **ENFORCED** in `tests/CONTRACT_MIGRATION.md`.

**NO DIRECT CHANGES ALLOWED**

Any change to a governed interface MUST follow this process:

1. **Contract First**: Edit the contract document in `docs/contracts/resources/`
2. **Update Tests**: Modify both contract test files to match the new contract
3. **Verify**: Ensure all contract tests pass
4. **Update Status**: Update `tests/CONTRACT_MIGRATION.md` if needed

## What Requires Contract Updates

### CLI Behavior Changes

- Adding/removing command flags
- Changing flag names or types
- Modifying help text or usage
- Changing error messages or exit codes
- Altering confirmation prompts

### Output Format Changes

- JSON output structure changes
- Human-readable output format changes
- Adding/removing output fields
- Changing field names or types

### Data Behavior Changes

- Database schema changes
- Transaction semantics
- Rollback behavior
- Validation rules
- Default values

### Error Handling Changes

- New error conditions
- Different error codes
- Changed error messages
- Exception handling modifications

## Enforcement

### CI Enforcement

- Contract tests run on every PR
- Any contract test failure blocks the PR
- Legacy tests are excluded from CI

### Code Review Enforcement

- Reviewers MUST check that contract changes are documented
- Contract tests MUST be updated for any behavior changes
- No "quick fixes" or "small tweaks" without contract updates

## Examples

### ❌ FORBIDDEN: Direct Implementation Changes

```python
# DON'T DO THIS - changing behavior without contract update
def add_enricher(...):
    # Changed from exit code 1 to 2 without updating contract
    raise typer.Exit(2)  # This breaks the contract!
```

### ✅ REQUIRED: Contract-First Changes

1. Update `docs/contracts/resources/EnricherAddContract.md`:

   ```markdown
   ## Behavior Rules

   - **B-5:** On validation failure, the command MUST exit with code `2`
   ```

2. Update `tests/contracts/test_enricher_add_contract.py`:

   ```python
   def test_enricher_add_invalid_type_returns_error(self):
       # ... test code ...
       assert result.exit_code == 2  # Updated to match contract
   ```

3. Update implementation to match contract

## Benefits

### Prevents Drift

- CLI behavior stays consistent with documentation
- No undocumented "improvements" that break expectations

### Maintains Stability

- Users can rely on consistent behavior
- Scripts and automation won't break unexpectedly

### Enables Evolution

- Changes are deliberate and documented
- Contract serves as the source of truth

## Adding New Governed Interfaces

To add a new governed interface:

1. Create contract document in `docs/contracts/resources/`
2. Create contract tests in `tests/contracts/`
3. Implement the command to pass all tests
4. Update `tests/CONTRACT_MIGRATION.md` to mark as **ENFORCED**

## Emergency Overrides

In rare emergency situations, the following process applies:

1. Create an issue documenting the emergency
2. Make the minimal change required
3. Immediately create a follow-up issue to update the contract
4. Update contract and tests within 48 hours
5. Document the emergency in commit messages

**Emergency overrides should be extremely rare and require team lead approval.**
