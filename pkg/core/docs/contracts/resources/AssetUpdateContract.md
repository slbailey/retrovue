# Asset Update Contract

## Purpose

Define the operator interface for updating asset metadata and configuration in RetroVue. This contract ensures consistent, predictable behavior when modifying asset information through the CLI.

## Scope

This contract applies to the `retrovue asset update <asset_id>` command, covering asset metadata updates with various update options and safety measures.

## Design Principles

- **Safety first:** Updates require validation and confirmation for destructive changes
- **Flexibility:** Support multiple update operations (metadata, state, approval status)
- **Clarity:** Command syntax must be intuitive for operators
- **Auditability:** All operations support dry-run and JSON output modes
- **Data integrity:** Validation of metadata and state transitions before changes

## CLI Syntax

The Retrovue CLI MUST expose asset updates using the pattern:

```
retrovue asset update <asset_id> [--state <state>] [--canonical] [--approve] [--unapprove] [--dry-run] [--json] [--test-db]
```

The noun (asset) MUST come before the verb (update).

Renaming, reordering, or collapsing this verb into flags is a breaking change and requires updating this contract.

## Parameters

- **Asset Identifier** (required): `<asset_id>` can be:

  - Full UUID (e.g., `123e4567-e89b-12d3-a456-426614174000`)
  - External ID (e.g., Plex rating key: `plex-12345`)
  - URI path (for filesystem sources)

- **Update Operations** (at least one required):

  - `--state <state>`: Update lifecycle state (`new`, `enriching`, `ready`, `retired`)
  - `--canonical`: Set `canonical=true`
  - `--no-canonical`: Set `canonical=false`
  - `--approve`: Set `approved_for_broadcast=true` (requires `state=ready`)
  - `--unapprove`: Set `approved_for_broadcast=false`

- **Safety Options**:

  - `--dry-run`: Show what would be updated without executing
  - `--force`: Skip validation checks (use with caution)

- **Output Options**:
  - `--json`: Output results in JSON format
  - `--test-db`: Use test database for updates

## Exit Codes

- `0`: Success - asset updated
- `1`: Error (asset not found, invalid identifier, validation failure, etc.)

The command MUST NOT partially apply changes and still exit 0.

If validation fails or asset cannot be found, the overall exit code MUST be non-zero.

## Safety Expectations

### State Transition Validation

- **State Transitions**: State updates must follow valid lifecycle transitions:

  - `new` → `enriching` → `ready` → `retired`
  - Direct transitions (e.g., `new` → `ready`) may require `--force`
  - `retired` assets cannot transition to other states without `--force`

- **Approval Requirements**:
  - `--approve` requires `state=ready`
  - If state is not `ready`, approval update is rejected unless `--force` is provided
  - `--unapprove` can be performed on any state

### Validation Rules

- **Asset Must Exist**: Asset identifier must resolve to an existing asset
- **State Must Be Valid**: State values must be one of: `new`, `enriching`, `ready`, `retired`
- **Ambiguity Handling**: If multiple assets match identifier, exit with code 1 and emit error message
- **Dry-run Precedence**: When both `--dry-run` and `--test-db` are provided, `--dry-run` takes precedence

### Confirmation Models

- State transitions that bypass normal workflow require confirmation unless `--force` is provided
- Approval changes that violate invariants require confirmation unless `--force` is provided
- Hard state resets (e.g., `ready` → `new`) require confirmation unless `--force` is provided

## Output Format

### Human-Readable Output

The human-readable output MUST include:

- **Asset UUID**: Updated asset identifier
- **Changes Applied**: List of fields that were updated
- **New State**: Updated lifecycle state (if changed)
- **New Approval Status**: Updated approval status (if changed)

### JSON Output

When `--json` is passed, all output MUST be valid JSON with the following structure:

```json
{
  "status": "success",
  "asset_uuid": "123e4567-e89b-12d3-a456-426614174000",
  "changes": {
    "state": {
      "old": "enriching",
      "new": "ready"
    },
    "approved_for_broadcast": {
      "old": false,
      "new": true
    }
  },
  "updated_at": "2024-01-01T12:00:00Z"
}
```

## Examples

```bash
# Update asset state to ready
retrovue asset update 123e4567-e89b-12d3-a456-426614174000 --state ready

# Approve asset for broadcast
retrovue asset update 123e4567-e89b-12d3-a456-426614174000 --approve

# Update state and approve in one operation
retrovue asset update 123e4567-e89b-12d3-a456-426614174000 --state ready --approve

# Dry-run to preview changes
retrovue asset update 123e4567-e89b-12d3-a456-426614174000 --state ready --dry-run

# Update with JSON output
retrovue asset update 123e4567-e89b-12d3-a456-426614174000 --state ready --json
```

## Database Side Effects

### State Updates

- **State Change**: Updates `state` field on Asset record
- **Timestamp Update**: Updates `updated_at` timestamp (if field exists)

### Approval Updates

- **Approval Change**: Updates `approved_for_broadcast` field on Asset record
- **Canonical Change**: Updates `canonical` field if approval status changes

### Transaction Boundaries

- All updates within a single operation MUST occur within a single Unit of Work
- If any update fails, all changes MUST be rolled back
- Dry-run mode MUST NOT perform any database writes

## Error Conditions

- **Asset Not Found**: Returned when no matching asset exists for the provided identifier
- **Invalid UUID Format**: Raised if the provided UUID cannot be parsed
- **Ambiguous Identifier**: Raised if multiple assets match identifier
- **Invalid State**: Raised if `--state` value is not one of: `new`, `enriching`, `ready`, `retired`
- **Invalid State Transition**: Raised if state transition is not allowed (e.g., `retired` → `ready` without `--force`)
- **Approval Without Ready State**: Raised if `--approve` is used but asset is not in `ready` state (unless `--force`)
- **No Updates Specified**: Raised if no update flags are provided

## Contract Test Coverage

The following test methods must enforce this contract:

- `test_asset_update_state`: Validates state update
- `test_asset_update_approve`: Validates approval update
- `test_asset_update_multiple_fields`: Validates updating multiple fields
- `test_asset_update_dry_run`: Validates dry-run mode
- `test_asset_update_json_output`: Validates JSON output format
- `test_asset_update_not_found`: Validates error handling for non-existent asset
- `test_asset_update_invalid_state`: Validates error handling for invalid state
- `test_asset_update_invalid_transition`: Validates error handling for invalid state transitions
- `test_asset_update_approve_without_ready`: Validates error handling for approval without ready state
- `test_asset_update_no_updates_specified`: Validates error handling when no updates are specified

## Implementation Notes

- All update operations must be wrapped in Unit of Work boundaries
- State transitions must be validated before database writes
- Approval updates must enforce invariant: `approved_for_broadcast=true` requires `state=ready`
- Dry-run mode must show exact changes without performing database writes
- JSON output must include both old and new values for changed fields
- Error messages must be clear and actionable for operators

---

## Contract Lifecycle & Governance

This contract is the authoritative rulebook for `retrovue asset update`.  
Follow this lifecycle for any change:

1. **Propose & Edit Contract**

   - Any change to operator-facing behavior must be proposed by editing this contract file first.
   - The change MUST include rationale and updated contract test list entries.

2. **Update Contract Tests**

   - Update or add tests under:
     - `tests/contracts/test_asset_update_contract.py` (CLI/operator surface)
     - `tests/contracts/test_asset_update_data_contract.py` (persistence/data effects)
   - Each test MUST include a `# CONTRACT:` comment referencing the specific clause in this file it enforces.

3. **Implement**

   - Only after tests are updated should implementation changes be made.
   - Implementation must aim to make the contract tests pass.

4. **Changelog & Versioning**
   - Increment the contract version or date at the top of this file when making breaking changes.
   - Add a changelog entry below.

---

## Changelog

| Version | Date       | Summary                   |
| ------- | ---------- | ------------------------- |
| 1.0     | 2025-01-27 | Initial contract created. |

---

## See Also

- [Asset Contract](AssetContract.md) - Overview of all Asset operations
- [Asset Domain Documentation](../../domain/Asset.md) - Core domain model
- [Collection Update Contract](CollectionUpdateContract.md) - Collection update operations

