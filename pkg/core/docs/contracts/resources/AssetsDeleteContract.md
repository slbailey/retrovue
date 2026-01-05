# Assets Delete Contract

## Purpose

Define the operator interface for asset deletion and restoration commands in RetroVue. This contract ensures safe, predictable behavior when managing media assets through the CLI.

## Scope

This contract applies to the `retrovue assets delete` and `retrovue assets restore` commands, covering both soft and hard deletion modes with appropriate safety measures.

## Design Principles

- **Safety first:** Hard deletion requires explicit confirmation and force flags
- **Clarity:** Command syntax must be intuitive for operators
- **Auditability:** All operations support dry-run and JSON output modes
- **Data integrity:** Reference checks prevent accidental deletion of referenced assets

## CLI Syntax

The Retrovue CLI MUST expose these actions using the pattern:

retrovue assets delete ... and retrovue assets restore ....

The noun (assets) MUST come before the verb (delete / restore).

Renaming, reordering, or collapsing these verbs into flags is a breaking change and requires updating this contract.

### Asset Delete

```
retrovue assets delete [--uuid <uuid> | --id <id> | --show <title> | --show <title> --season <number> | --show <title> --season <number> --episode <number> | --title <title> (for assets that do not follow a tv show hierarchy)] [--soft | --hard] [--force] [--yes] [--dry-run] [--json]
```

### Asset Restore

```
retrovue assets restore [--uuid <uuid> | --id <id> | --show <title> | --show <title> --season <number> | --show <title> --season <number> --episode <number> | --title <title> (for assets that do not follow a tv show hierarchy)] [--json]
```

## Parameters

### Delete Command

- **Asset Selector** (exactly one required):

  - `--uuid <uuid>`: Target asset by UUID
  - `--id <id>`: Target asset by database ID
  - `--show <title>`: Target all assets for a particular TV show
  - `--show <title> --season <number>`: Target all assets for a particular season of a particular TV show
  - `--show <title> --season <number> --episode <number>`: Target a specific season and episode of a particular TV show
  - `--title <title>`: Target asset by human searchable title (for assets that do not follow a tv show hierarchy)

- **Deletion Mode**:

  - `--soft`: Soft delete (default) - marks asset as deleted but preserves data
  - `--hard`: Hard delete - permanently removes asset from database

- **Safety Flags**:

  - `--force`: Override reference checks for hard deletion
  - `--yes`: Skip confirmation prompts

- **Output Options**:
  - `--dry-run`: Show what would be deleted without performing the action
  - `--json`: Output results in JSON format

### Restore Command

- `--uuid <uuid>`: Target asset by UUID
- `--id <id>`: Target asset by database ID
- `--show <title>`: Target all assets for a particular TV show
- `--show <title> --season <number>`: Target all assets for a particular season of a particular TV show
- `--show <title> --season <number> --episode <number>`: Target a specific season and episode of a particular TV show
- `--title <title>`: Target asset by human searchable title (for assets that do not follow a tv show hierarchy)
- `--json`: Output results in JSON format

**Note**: Restore operations work with all selector types (UUID, ID, TV show hierarchy, and standalone titles). Only soft-deleted assets can be restored.

## Exit Codes

- `0`: Success
- `1`: Error (asset not found, invalid UUID, validation failure, etc.)

The command MUST NOT partially apply changes and still exit 0.

If any selected asset fails validation, reference checks, or cannot be deleted/restored, the overall exit code MUST be non-zero.

## Safety Expectations

### Soft Delete (Default)

- No confirmation required
- Safe operation - asset marked as deleted but data preserved
- Can be restored using `retrovue assets restore`

### Hard Delete

- **Reference Check**: Hard deletion is refused if asset is referenced by episodes
  - When a hard delete is refused due to active references, the CLI MUST clearly state that the asset is still referenced, and MUST include at least one referencing Episode identifier in either human output or --json output. This is required for operator triage.
- **Confirmation Required**: Must use `--yes` flag to skip interactive confirmation
- **Force Override**: `--force` flag bypasses reference checks (dangerous)
- **Permanent**: Cannot be undone

### Dry Run Mode

- Always safe - shows what would be deleted without performing the action
- Shows reference status and deletion type
- JSON output provides structured preview data
- The top-level object MUST include:
  action ("delete" or "restore")
  mode ("soft", "hard", or "restore")
  assets (array of affected assets)
  skipped (array of assets that could not be acted on, with reasons)
- This structure is considered part of the public contract and MUST be covered by contract tests.

## Examples

```bash
## Delete Asset Examples

### By UUID

# Soft delete (safe, reversible)
retrovue assets delete --uuid 123e4567-e89b-12d3-a456-426614174000 --yes

# Preview hard deletion (dry run)
retrovue assets delete --uuid 123e4567-e89b-12d3-a456-426614174000 --hard --dry-run

# Hard delete with confirmation (irreversible)
retrovue assets delete --uuid 123e4567-e89b-12d3-a456-426614174000 --hard --yes

# Force hard delete (bypasses reference checks; dangerous)
retrovue assets delete --uuid 123e4567-e89b-12d3-a456-426614174000 --hard --force --yes

# Dry-run with JSON preview (for scripting)
retrovue assets delete --uuid 123e4567-e89b-12d3-a456-426614174000 --dry-run --json

### By Database ID

# (Example shown for clarity; replace with actual asset ID)
retrovue assets delete --id 1234 --yes

### By Title, Show, Season, or Episode

# Delete all assets for a TV show (by title)
retrovue assets delete --show "The Simpsons" --yes

# Delete all assets for a specific season of a TV show
retrovue assets delete --show "The Simpsons" --season 4 --yes

# Delete all assets for a specific episode of a TV show
retrovue assets delete --show "The Simpsons" --season 4 --episode 12 --yes

# Delete asset by standalone title (not tied to show/season/episode hierarchy)
retrovue assets delete --title "Cool 90s Commercial Block" --yes

## Restore Asset Examples

# Restore by UUID (works for a soft-deleted asset)
retrovue assets restore 123e4567-e89b-12d3-a456-426614174000

# Restore all assets for a TV show (by title)
retrovue assets restore --show "The Simpsons" --yes

# Restore all assets for a specific season
retrovue assets restore --show "The Simpsons" --season 4 --yes

# Restore all assets for a specific episode
retrovue assets restore --show "The Simpsons" --season 4 --episode 12 --yes

# Restore asset by general title
retrovue assets restore --title "Cool 90s Commercial Block" --yes
```

## Database Side Effects

### Soft Delete

- Sets `is_deleted = true` on the Asset record
- Asset remains in database but is excluded from normal queries
- Associated metadata and file references preserved

### Hard Delete

- Permanently removes Asset record from database
- Cascading deletes may affect related records
- File system cleanup may be triggered (implementation dependent)

### Restore

- Sets `is_deleted = false` on the Asset record
- Asset becomes available for normal operations again

## Scheduler Impact

- Soft-deleted assets are excluded from scheduling and playback
- Restored assets become available for scheduling again
- Hard-deleted assets are permanently removed from all scheduling operations

## Error Conditions

- **Asset Not Found**: Returned when no matching asset exists for the provided selector (`--uuid`, `--id`, or title+show+season+episode combination).
- **Invalid UUID Format**: Raised if the provided UUID cannot be parsed (malformed or not a valid UUIDv4 string).
- **Missing Selector**: Triggered if none of `--uuid`, `--id`, or a valid set of title-based selectors (`--show`, `--title`, with optional `--season` and `--episode`) are provided.
- **Multiple Selectors**: Raised if more than one mutually exclusive selector is provided (e.g., both `--uuid` and `--id`, or combined with title-based selectors).
- **Reference Violation**: For hard deletion, raised if the asset is still referenced by one or more episodes, unless the `--force` flag is supplied to override this protection.
- **Not Soft-Deleted**: For restore commands, raised if attempting to restore an asset that is not currently soft-deleted.
- **Partial Match Ambiguity**: Raised if title-based selectors match multiple assets and the operation is inherently ambiguous without further narrowing.
- **Delete/Restore Not Allowed**: Raised if current asset state, permissions, or business rules prohibit the requested operation (e.g., attempts to restore a hard-deleted asset).
- **Referenced By Episodes**: During deletion, clearly indicates if the asset is blocked from hard delete by existing episode references, and lists referencing episode IDs if possible.

## Contract Test Coverage

The following test methods enforce this contract:

### Delete Command Tests

- `test_delete_asset_by_uuid_soft_delete`: Validates that a single asset can be soft-deleted by UUID, including state change and output.
- `test_delete_asset_by_uuid_soft_delete_with_confirmation`: Checks enforcement of confirmation flag and user confirmation prompt before deletion.
- `test_delete_asset_confirmation_prompt`: Validates interactive confirmation when --yes is not provided.
- `test_delete_asset_confirmation_cancelled`: Ensures proper handling when user cancels confirmation.
- `test_delete_asset_by_uuid_dry_run`: Confirms operation output in dry-run mode, verifying no changes are made and output is accurate.
- `test_delete_asset_by_uuid_dry_run_json`: Ensures dry-run output produces valid and complete JSON.
- `test_delete_asset_by_id`: Confirms asset can be deleted by integer database ID as selector.
- `test_delete_asset_multiple_criteria_error`: Ensures mutually exclusive selector constraint is enforced and error output is clear.
- `test_delete_asset_mixed_selectors_error`: Ensures error when combining incompatible selectors (e.g., --uuid with --show).
- `test_delete_asset_missing_selector`: Checks contract for requiring at least one valid selector, returning the right error.
- `test_delete_asset_hard_delete_with_existing_references`: Validates reference check enforcement for hard deletes and lists referencing episode IDs in output.
- `test_delete_asset_hard_delete_with_force`: Validates the use of `--force` flag allows hard-deleting assets with active references.
- `test_delete_asset_nonexistent`: Enforces contract for attempts to delete missing asset (by UUID or ID).
- `test_delete_asset_invalid_uuid`: Validates error on malformed UUIDs.
- `test_delete_asset_no_selector`: Ensures invocation fails with appropriate error when no selector is provided.
- `test_delete_asset_partial_match_ambiguity`: Validates correct error for non-unique title-based matches.
- `test_delete_asset_show_bulk_operation`: Validates deletion of multiple assets for a TV show.

### Restore Command Tests

- `test_restore_asset_success`: Confirms soft-deleted asset can be restored successfully, and available in normal operations.
- `test_restore_asset_requires_soft_deleted_state`: Validates that only soft-deleted assets may be restored, and errors otherwise.
- `test_restore_asset_json_output`: Confirms correct JSON output for restore operation, including all contract fields.
- `test_restore_asset_nonexistent`: Checks contract for handling restore of non-existent asset.
- `test_restore_asset_invalid_uuid`: Covers malformed UUID input.
- `test_restore_asset_partial_match_ambiguity`: Ensures ambiguity error if selector resolves to multiple possible assets.
- `test_restore_asset_show_bulk_operation`: Validates restoration of multiple soft-deleted assets for a TV show.

## Implementation Notes

- All database operations must be atomic and wrapped in proper transactions.
- Selector resolution must enforce mutual exclusivity and return actionable error messages for violation.
- Reference checks for hard deletes must use the complete set of episode-asset relationships.
- Support both CLI flag-based and prompt-based confirmation for destructive acts.
- JSON output (including dry-run) must use consistent field names, camelCase or snake_case per API norm, and explicit booleans for state.
- Error and info messages must be clear, informative, and actionable for operators (suggest next action where possible).
- Dry-run mode must show exact outcome, including which assets would be affected, and which are protected and why.

---

## Contract Lifecycle & Governance

This contract is the authoritative rulebook for `retrovue assets delete` and `retrovue assets restore`.  
Follow this lifecycle for any change:

1. **Propose & Edit Contract**

   - Any change to operator-facing behavior must be proposed by editing this contract file first.
   - The change MUST include rationale and updated contract test list entries.

2. **Update Contract Tests**

   - Update or add tests under:
     - `tests/contracts/test_assets_delete_contract.py` (CLI/operator surface)
     - `tests/contracts/test_assets_delete_data_contract.py` (persistence/data effects)
   - Each test MUST include a `# CONTRACT:` comment referencing the specific clause in this file it enforces.

3. **Implement**

   - Only after tests are updated should implementation changes be made.
   - Implementation must aim to make the contract tests pass.

4. **Changelog & Versioning**
   - Increment the contract version or date at the top of this file when making breaking changes.
   - Add a changelog entry below.

---

## Changelog

| Version | Date       | Summary                                         |
| ------- | ---------- | ----------------------------------------------- |
| 1.0     | 2025-10-26 | Baseline contract provided by operator (Steve). |

---

## Traceability Matrix (sample)

| Contract Clause                      | Test File                                             | Test Name                                                |
| ------------------------------------ | ----------------------------------------------------- | -------------------------------------------------------- |
| Dry-run output structure             | `tests/contracts/test_assets_delete_contract.py`      | `test_delete_asset_by_uuid_dry_run`                      |
| Hard-delete reference protection     | `tests/contracts/test_assets_delete_contract.py`      | `test_delete_asset_hard_delete_with_existing_references` |
| Restore behavior (soft-deleted only) | `tests/contracts/test_assets_delete_data_contract.py` | `test_restore_asset_success`                             |

---

## Enforcement Rule

The contract defines required behavior. Tests are the enforcement mechanism.  
Implementation must be updated only after the contract and tests are updated.
