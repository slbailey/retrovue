# Asset Resolve Contract

## Purpose

Define the operator interface for resolving asset issues in RetroVue. This contract ensures consistent, predictable behavior when operators need to approve assets or advance their lifecycle state.

## Scope

This contract applies to the `retrovue asset resolve <asset_uuid>` command, covering the minimal operator write path added in Milestone 3C to unblock assets for broadcast.

## Design Principles

- **Minimal Surface**: Provides only the essential operations needed to unblock assets
- **Safety**: Updates are constrained to specific state transitions
- **Flexibility**: Supports read-only mode when no flags provided
- **Consistency**: JSON output format must be structured and predictable
- **Atomicity**: All updates occur within a single Unit of Work

## CLI Syntax

The Retrovue CLI MUST expose asset resolution using the pattern:

```
retrovue asset resolve <asset_uuid> [--approve] [--ready] [--json]
```

The noun (asset) MUST come before the verb (resolve).

Renaming, reordering, or collapsing this verb into flags is a breaking change and requires updating this contract.

## Parameters

- **Asset UUID** (required): `<asset_uuid>` must be a valid UUID string

- **Resolution Flags** (at least one required for mutation):
  - `--approve`: Set `approved_for_broadcast = true`
  - `--ready`: Set `state = 'ready'` (permitted from `enriching` state)

- **Output Options**:
  - `--json`: Output results in JSON format
  - Default: Human-readable format

### Read-Only Mode

When **no resolution flags** are provided, the command operates in read-only mode:
- Displays current asset information
- No database writes occur
- Helpful for inspecting asset state before making changes

## Exit Codes

- `0`: Success - asset resolved or displayed
- `1`: Error (asset not found, invalid UUID, database error, etc.)

The command MUST NOT partially apply changes and still exit 0.

## Safety Expectations

### Update Constraints

**Approval Flag** (`--approve`):
- Sets `approved_for_broadcast = true`
- No validation constraints on current state
- Updates `updated_at` timestamp

**State Flag** (`--ready`):
- Sets `state = 'ready'`
- Intended for transitioning from `enriching` → `ready`
- No validation prevents other transitions (relying on operator judgment)
- Updates `updated_at` timestamp

**Combined Use**:
- Both flags can be used together: `--approve --ready`
- Allows complete resolution in a single command

### Unit of Work

- All updates occur within a single database transaction
- **NO COMMIT**: The command does not call `commit()`
- Unit of Work session context handles commit/rollback
- Changes are atomic - either all succeed or all are rolled back

## Output Format

### Human-Readable Output

**Read-Only Mode** (no flags):
```
<uuid>  <state>      approved=<true|false>  <uri>
```

Example:
```
11111111-1111-1111-1111-111111111111  enriching   approved=False  /media/a.mp4
```

**Update Mode** (with flags):
```
Asset <uuid> updated
```

Example:
```
Asset 11111111-1111-1111-1111-111111111111 updated
```

### JSON Output

**Read-Only Mode** (no flags):
```json
{
  "status": "ok",
  "asset": {
    "uuid": "11111111-1111-1111-1111-111111111111",
    "collection_uuid": "22222222-2222-2222-2222-222222222222",
    "uri": "/media/a.mp4",
    "state": "enriching",
    "approved_for_broadcast": false
  }
}
```

**Update Mode** (with flags):
```json
{
  "status": "ok",
  "asset": {
    "uuid": "11111111-1111-1111-1111-111111111111",
    "collection_uuid": "22222222-2222-2222-2222-222222222222",
    "uri": "/media/a.mp4",
    "state": "ready",
    "approved_for_broadcast": true
  }
}
```

**Required Fields:**
- `status`: Always `"ok"` for successful operations
- `asset`: Asset object with required fields

**Asset Object Fields:**
- `uuid`: Asset UUID (string)
- `collection_uuid`: Collection UUID (string)
- `uri`: Asset URI/path (string)
- `state`: Lifecycle state
- `approved_for_broadcast`: Boolean approval status

## Examples

```bash
# Display asset information (read-only)
retrovue asset resolve 11111111-1111-1111-1111-111111111111

# Approve asset for broadcast
retrovue asset resolve 11111111-1111-1111-1111-111111111111 --approve

# Mark asset as ready
retrovue asset resolve 11111111-1111-1111-1111-111111111111 --ready

# Approve and mark ready in one operation
retrovue asset resolve 11111111-1111-1111-1111-111111111111 --approve --ready

# Display asset information as JSON
retrovue asset resolve 11111111-1111-1111-1111-111111111111 --json

# Update and output as JSON
retrovue asset resolve 11111111-1111-1111-1111-111111111111 --approve --json
```

## Database Side Effects

### Read-Only Mode

When no flags are provided:
- **No Database Changes**: Displays asset information without modifying
- Queries existing asset by UUID
- Returns information for display

### Update Mode

When flags are provided:
- **Field Updates**: Updates specified fields on the Asset record
- **Timestamp Update**: Updates `updated_at` to current timestamp
- **Session Tracking**: Adds asset to session (no commit)
- **Atomic Operation**: All updates occur within a single transaction

### Transaction Boundaries

- All updates within a single operation MUST occur within a single Unit of Work
- **NO COMMIT**: Command does not call `commit()`
- UoW context manager handles commit/rollback
- If any update fails, all changes MUST be rolled back

## Error Conditions

- **Asset Not Found**: Raised when asset UUID does not exist in database
- **Invalid UUID Format**: Raised when UUID cannot be parsed as valid UUID
- **Database Error**: Raised if database operation fails

Error messages must be clear and actionable:
```
Error: Asset not found
Error: <uuid> is not a valid UUID
Error: <database-specific error message>
```

## Contract Test Coverage

The following test methods must enforce this contract:

- `test_resolve_enriching_asset_with_approve_and_ready`: Validates dual flag operation
- `test_missing_asset_exits_one`: Validates error handling for non-existent assets
- `test_read_only_mode_displays_info`: Validates read-only mode (if implemented)
- `test_json_output_format`: Validates JSON output structure
- `test_single_approve_flag`: Validates approve-only operation
- `test_single_ready_flag`: Validates ready-only operation

## Implementation Notes

- Read-only mode uses `get_asset_summary()` usecase
- Update mode uses `update_asset_review_status()` usecase
- Both usecases operate within the same session context (from `retrovue.infra.uow.session`)
- No commit is performed - UoW context manager handles it
- Updates are atomic within the transaction
- JSON output must include all required fields with correct data types
- Error messages must be clear and actionable for operators

## Milestone 3C Context

This command was added in Milestone 3C as the minimal operator write path to unblock assets for broadcast:

- Ingest creates/updates Assets and may downgrade them to `enriching` or leave them not approved
- Operators use `asset attention` to list assets needing attention
- Operators use `asset resolve` to resolve individual assets
- **Note**: 3C does not run enrichers; it only unblocks assets for broadcast
- Re-enrichment, if needed, is a separate step

---

## Contract Lifecycle & Governance

This contract is the authoritative rulebook for `retrovue asset resolve`.  
Follow this lifecycle for any change:

1. **Propose & Edit Contract**

   - Any change to operator-facing behavior must be proposed by editing this contract file first.
   - The change MUST include rationale and updated contract test list entries.

2. **Update Contract Tests**

   - Update or add tests under:
     - `tests/contracts/test_asset_resolve_contract.py` (CLI/operator surface)
     - `tests/contracts/test_asset_resolve_data_contract.py` (persistence/data effects)
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
- [Asset Attention Contract](AssetAttentionContract.md) - Find assets needing attention
- [Asset execution model](../../domain/Asset.md#execution-model) - Lifecycle and state transitions

