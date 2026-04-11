# Destructive Operation Confirmation Contract

> **This document is part of the RetroVue Contract System.**  
> For enforcement status, see `tests/CONTRACT_MIGRATION.md`.

This contract defines the standardized confirmation and authorization flow for all destructive CLI commands in RetroVue. It ensures consistent user experience, prevents accidental data loss, and maintains production safety across all destructive operations.

## Purpose

Destructive operations (delete, remove, wipe, etc.) require explicit user confirmation to prevent accidental data loss. This contract standardizes:

- When confirmation is required
- How confirmation prompts are presented
- What constitutes valid confirmation
- How `--force` and `--confirm` flags behave
- Exit codes and output for cancellation
- Batch/wildcard operation confirmation
- Production safety enforcement

## Scope

This contract applies to ALL destructive CLI commands that:
- Remove or delete data permanently
- Modify system state in irreversible ways
- Could cause data loss if executed accidentally

**Examples:**
- `retrovue source delete`
- `retrovue collection wipe`
- `retrovue enricher remove`
- `retrovue channel delete`
- `retrovue playlist delete`

## Command Shape

All destructive commands MUST support these standardized flags:

```
retrovue <noun> <verb> [--force] [--confirm] [--dry-run] [--json] [other-args]
```

**Required Flags:**
- `--force`: Skip all confirmation prompts and proceed immediately
- `--confirm`: Required flag to proceed with destructive operation
- `--dry-run`: Preview changes without executing (inherited from base CLI contract)
- `--json`: Output in structured format (inherited from base CLI contract)

## Confirmation Rules (C-#)

### C-1: Confirmation Requirement
**Rule:** Destructive operations MUST require explicit confirmation unless `--force` is provided.

**Behavior:**
- If `--force` is NOT provided, the command MUST prompt for confirmation
- If `--force` IS provided, the command MUST skip confirmation and proceed
- The `--confirm` flag is REQUIRED for non-interactive execution

### C-2: Confirmation Prompt Content
**Rule:** Confirmation prompts MUST include:
- Clear description of what will be deleted/removed
- Impact summary (number of affected entities)
- Explicit warning about data loss
- Required response format

**Example Format:**
```
⚠️  WARNING: This will permanently delete the following:
   • Source: "My Plex Server" (ID: abc-123)
   • Collections: 15 collections will be deleted
   • Assets: ~2,500 assets will be removed

This action cannot be undone. Type "yes" to confirm deletion:
```

### C-3: Affirmative Response Validation
**Rule:** Confirmation MUST require typing "yes" exactly (case-sensitive).

**Behavior:**
- Only "yes" (lowercase) is accepted as confirmation
- "y", "YES", "Yes", "ok", "confirm" are NOT accepted
- Empty input is treated as cancellation
- Invalid input shows error and re-prompts

### C-4: Cancellation Behavior
**Rule:** Cancellation MUST return exit code `0` with clear message.

**Behavior:**
- User types anything other than "yes" → cancellation
- User presses Ctrl+C → cancellation
- User presses Enter with empty input → cancellation
- Output: "Operation cancelled."
- Exit code: `0` (success, no error occurred)

### C-5: Force Flag Behavior
**Rule:** `--force` MUST skip all confirmation prompts and proceed immediately.

**Behavior:**
- No interactive prompts shown
- No waiting for user input
- Proceeds directly to execution
- Still respects `--dry-run` if provided

### C-6: Confirm Flag Behavior
**Rule:** `--confirm` flag MUST be required for non-interactive execution.

**Behavior:**
- Required when `--force` is NOT provided
- Allows scripted/automated execution
- Must be explicitly provided by operator
- Cannot be inferred or defaulted

### C-7: Batch/Wildcard Confirmation
**Rule:** Multi-target operations MUST present aggregated confirmation prompt.

**Behavior:**
- Single prompt for all matched targets
- Shows total impact across all targets
- Requires single "yes" confirmation for all
- If any target fails safety check, show which ones were skipped

**Example:**
```
⚠️  WARNING: This will permanently delete 3 sources:
   • Source: "test-plex-1" (ID: abc-123) - 5 collections, ~500 assets
   • Source: "test-plex-2" (ID: def-456) - 3 collections, ~300 assets
   • Source: "test-plex-3" (ID: ghi-789) - 8 collections, ~800 assets

Total impact: 16 collections, ~1,600 assets will be removed.
This action cannot be undone. Type "yes" to confirm deletion:
```

### C-8: Production Safety Enforcement
**Rule:** Production safety rules MUST NOT be bypassed by confirmation.

**Behavior:**
- Protected entities MUST be skipped even with `--force`
- Safety checks run BEFORE confirmation prompts
- Confirmation only applies to non-protected entities
- Clear reporting of what was skipped and why

### C-9: Dry Run Integration
**Rule:** `--dry-run` MUST be supported and show confirmation prompt preview.

**Behavior:**
- Shows what confirmation prompt would look like
- Displays impact summary without executing
- Returns exit code `0` with preview output
- Does not require `--confirm` flag

### C-10: JSON Output Integration
**Rule:** JSON output MUST include confirmation status and impact summary.

**Behavior:**
- `--dry-run --json`: Shows preview in structured format
- `--force --json`: Shows execution results in structured format
- Includes `"confirmation_required": true/false`
- Includes `"impact_summary"` object with counts

### C-11: Error Handling
**Rule:** Confirmation errors MUST be handled gracefully.

**Behavior:**
- Invalid confirmation input shows error message
- Re-prompts for correct input (max 3 attempts)
- After 3 failed attempts, treat as cancellation
- Clear error messages for each failure

### C-12: Implementation Requirements
**Rule:** Confirmation logic MUST be implemented in reusable helper functions.

**Behavior:**
- Shared confirmation module for all commands
- Testable without mocking stdin/stdout
- Consistent behavior across all commands
- Clear separation between confirmation and execution logic

### C-13: Test Requirements
**Rule:** Confirmation behavior MUST be fully testable.

**Behavior:**
- Unit tests for confirmation logic
- Integration tests for full command flow
- Mock stdin/stdout for interactive testing
- Test all confirmation scenarios (valid, invalid, cancel)

### C-14: Documentation Requirements
**Rule:** Each destructive command MUST reference this contract.

**Behavior:**
- Command contracts MUST reference "DestructiveOperationConfirmation (C-1 through C-14)"
- Cannot redefine confirmation behavior locally
- Must inherit all confirmation rules from this contract
- Can add command-specific impact details only

## Exit Codes

| Code | Meaning | Usage |
|------|---------|-------|
| `0` | Success or Cancellation | Operation completed successfully or user cancelled |
| `1` | Validation Error | Invalid arguments, missing required flags |
| `2` | Partial Success | Some targets succeeded, others failed safety checks |
| `3` | External Dependency Error | Database unavailable, network issues |

## Examples

### Single Target Confirmation
```bash
# Interactive confirmation
$ retrovue source delete plex-server-1
⚠️  WARNING: This will permanently delete:
   • Source: "Plex Server" (ID: abc-123)
   • Collections: 15 collections
   • Assets: ~2,500 assets
This action cannot be undone. Type "yes" to confirm: no
Operation cancelled.

# Force execution
$ retrovue source delete plex-server-1 --force
Successfully deleted source: Plex Server

# Non-interactive execution
$ retrovue source delete plex-server-1 --confirm
Successfully deleted source: Plex Server
```

### Batch Target Confirmation
```bash
# Wildcard confirmation
$ retrovue source delete "test-*"
⚠️  WARNING: This will permanently delete 3 sources:
   • Source: "test-plex-1" (ID: abc-123) - 5 collections, ~500 assets
   • Source: "test-plex-2" (ID: def-456) - 3 collections, ~300 assets
   • Source: "test-plex-3" (ID: ghi-789) - 8 collections, ~800 assets
Total impact: 16 collections, ~1,600 assets
This action cannot be undone. Type "yes" to confirm: yes
Successfully deleted 3 sources.
```

### Dry Run Preview
```bash
$ retrovue source delete plex-server-1 --dry-run
⚠️  DRY RUN: This would permanently delete:
   • Source: "Plex Server" (ID: abc-123)
   • Collections: 15 collections
   • Assets: ~2,500 assets
This action cannot be undone. Type "yes" to confirm: yes
[DRY RUN] Would delete source: Plex Server
```

## Implementation Guidance

### Reusable Confirmation Module
```python
# Example implementation structure
class DestructiveOperationConfirmation:
    def require_confirmation(self, operation: str, targets: List[Target], 
                           force: bool = False, dry_run: bool = False) -> bool:
        """Standard confirmation flow for destructive operations."""
        
    def format_impact_summary(self, targets: List[Target]) -> str:
        """Format impact summary for confirmation prompt."""
        
    def validate_confirmation(self, response: str) -> bool:
        """Validate user confirmation response."""
```

### Command Integration
```python
# Example command integration
def delete_source(source_id: str, force: bool = False, confirm: bool = False):
    targets = get_deletion_targets(source_id)
    
    if not force:
        if not confirm:
            confirmation = DestructiveOperationConfirmation()
            if not confirmation.require_confirmation("delete source", targets):
                return  # User cancelled
    
    execute_deletion(targets)
```

## Test Coverage Mapping

| Rule Range | Enforced By | Test File |
|------------|-------------|-----------|
| `C-1..C-6` | Confirmation flow tests | `test_destructive_confirmation_contract.py` |
| `C-7..C-10` | Integration tests | `test_destructive_confirmation_data_contract.py` |
| `C-11..C-14` | Implementation tests | Various command contract tests |

## Dependencies

- **Base CLI Contract**: Global flags (`--dry-run`, `--json`, `--test-db`)
- **Unit of Work Contract**: Transaction management for atomic operations
- **Command-Specific Contracts**: SourceDelete, CollectionWipe, EnricherRemove, etc.

## See Also

- [Unit of Work Contract](UnitOfWorkContract.md) - Transaction management
- [Source Delete Contract](../resources/SourceDeleteContract.md) - Example implementation
- [CLI Change Policy](../resources/CLI_CHANGE_POLICY.md) - Governance rules
- [Contract Test Guidelines](../resources/CONTRACT_TEST_GUIDELINES.md) - Testing standards

---

## Traceability

- **Linked Tests:** `tests/contracts/_ops/test_destructive_confirmation_contract.py`
- **Dependencies:** All destructive command contracts
- **Last Audit:** 2025-10-28
- **Status:** DRAFT (not yet ENFORCED)
