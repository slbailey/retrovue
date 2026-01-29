# Asset List Contract

## Purpose

Define the operator interface for listing assets in RetroVue. This contract ensures consistent, predictable behavior when browsing assets through the CLI with various filtering options.

## Scope

This contract applies to the `retrovue asset list` command, covering asset listing with filtering by collection, state, and other criteria.

## Design Principles

- **Flexibility:** Support multiple filtering options (collection, state, type, etc.)
- **Clarity:** Output must be clear and well-organized for operators
- **Consistency:** JSON output format must be structured and predictable
- **Safety:** Read-only operation with no state changes

## CLI Syntax

The Retrovue CLI MUST expose asset listing using the pattern:

```
retrovue asset list [--collection <collection_id>] [--state <state>] [--canonical] [--approved] [--json] [--test-db]
```

The noun (asset) MUST come before the verb (list).

Renaming, reordering, or collapsing this verb into flags is a breaking change and requires updating this contract.

## Parameters

### Filtering Options

- **Collection Filter**:

  - `--collection <collection_id>`: Filter assets by collection (UUID, external ID, or name)
  - Collection name matching MUST be case-insensitive
  - If multiple collections match the provided name (case-insensitive), the command MUST exit with code 1 and emit: "Multiple collections named '<name>' exist. Please specify the UUID."

- **State Filter**:

  - `--state <state>`: Filter assets by lifecycle state (`new`, `enriching`, `ready`, `retired`)
  - Must be one of the valid lifecycle states

- **Approval Filters**:

  - `--canonical`: Filter assets where `canonical=true`
  - `--approved`: Filter assets where `approved_for_broadcast=true`

- **Output Options**:
  - `--json`: Output results in JSON format
  - `--test-db`: Use test database for queries

## Exit Codes

- `0`: Success - assets listed (even if empty result)
- `1`: Error (invalid filter, validation failure, ambiguous collection name, etc.)

The command MUST NOT partially apply changes and still exit 0.

If filtering parameters are invalid or collection resolution is ambiguous, the overall exit code MUST be non-zero.

## Safety Expectations

### Read-Only Operation

- Asset list is a read-only operation with no state changes
- No database writes occur during asset listing
- Safe for repeated use without side effects

### Collection Resolution

- Collection can be identified by UUID, external ID, or case-insensitive name
- Collection name matching MUST be case-insensitive
- If multiple collections match the provided name (case-insensitive), the command MUST exit with code 1
- Resolution MUST NOT prefer one collection over another based on casing match

### Filtering Behavior

- Multiple filters can be combined (AND logic)
- Empty result sets are valid (exit code 0, empty list in output)
- Filtering by state must validate that the provided state is valid

## Output Format

### Human-Readable Output

The human-readable output MUST include:

- **Summary**: Total count of matching assets
- **Asset List**: Each asset with key information:
  - UUID
  - URI (file path)
  - Title (if available)
  - State
  - Size
  - Duration
  - Collection name

### JSON Output

When `--json` is passed, all output MUST be valid JSON with the following structure:

```json
{
  "status": "success",
  "total": 42,
  "assets": [
    {
      "uuid": "123e4567-e89b-12d3-a456-426614174000",
      "uri": "/path/to/asset.mp4",
      "size": 1234567890,
      "duration_ms": 3600000,
      "state": "ready",
      "canonical": true,
      "approved_for_broadcast": true,
      "collection": {
        "uuid": "collection-uuid",
        "name": "TV Shows"
      },
      "discovered_at": "2024-01-01T12:00:00Z"
    }
  ],
  "filters": {
    "collection": "collection-uuid",
    "state": "ready",
    "canonical": true,
    "approved": true
  }
}
```

## Examples

```bash
# List all assets
retrovue asset list

# List assets in a specific collection
retrovue asset list --collection "TV Shows"

# List ready assets
retrovue asset list --state ready

# List approved canonical assets
retrovue asset list --canonical --approved

# List assets with JSON output
retrovue asset list --collection "TV Shows" --state ready --json

# List assets in collection by UUID
retrovue asset list --collection 123e4567-e89b-12d3-a456-426614174000
```

## Database Side Effects

### Read-Only Operation

- **No Database Changes**: Asset list is a read-only operation
- **No State Persistence**: Listing does not modify asset records
- **No History Tracking**: Listing does not persist query history

## Error Conditions

- **Invalid State**: Raised if `--state` value is not one of: `new`, `enriching`, `ready`, `retired`
- **Collection Not Found**: Raised if collection identifier does not match any collection
- **Ambiguous Collection Name**: Raised if multiple collections match the provided name (case-insensitive)
- **Invalid Collection UUID**: Raised if collection UUID format is invalid

## Contract Test Coverage

The following test methods must enforce this contract:

- `test_asset_list_all`: Validates listing all assets
- `test_asset_list_by_collection`: Validates filtering by collection
- `test_asset_list_by_state`: Validates filtering by state
- `test_asset_list_by_canonical`: Validates filtering by canonical status
- `test_asset_list_by_approved`: Validates filtering by approval status
- `test_asset_list_combined_filters`: Validates combining multiple filters
- `test_asset_list_json_output`: Validates JSON output format
- `test_asset_list_collection_not_found`: Validates error handling for non-existent collection
- `test_asset_list_ambiguous_collection`: Validates error handling for ambiguous collection name
- `test_asset_list_invalid_state`: Validates error handling for invalid state filter

## Implementation Notes

- All listing operations must be read-only (no database writes)
- Collection name matching must be case-insensitive
- Filtering must use AND logic when multiple filters are provided
- Empty result sets are valid and should exit with code 0
- JSON output must include filter information for transparency
- Error messages must be clear and actionable for operators

---

## Contract Lifecycle & Governance

This contract is the authoritative rulebook for `retrovue asset list`.  
Follow this lifecycle for any change:

1. **Propose & Edit Contract**

   - Any change to operator-facing behavior must be proposed by editing this contract file first.
   - The change MUST include rationale and updated contract test list entries.

2. **Update Contract Tests**

   - Update or add tests under:
     - `tests/contracts/test_asset_list_contract.py` (CLI/operator surface)
     - `tests/contracts/test_asset_list_data_contract.py` (persistence/data effects)
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
- [Collection List Contract](CollectionListContract.md) - Collection listing operations

