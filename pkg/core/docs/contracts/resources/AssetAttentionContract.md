    # Asset Attention Contract

## Purpose

Define the operator interface for listing assets that need attention in RetroVue. This contract ensures consistent, predictable behavior when querying for assets requiring operator review.

## Scope

This contract applies to the `retrovue asset attention` command, covering the listing of assets that need attention based on lifecycle state and broadcast approval status.

## Design Principles

- **Clarity**: Output must clearly indicate which assets need attention and why
- **Safety**: Read-only operation with no state changes
- **Flexibility**: Support filtering by collection and limiting results
- **Consistency**: JSON output format must be structured and predictable

## CLI Syntax

The Retrovue CLI MUST expose asset attention listing using the pattern:

```
retrovue asset attention [--collection <collection_uuid>] [--limit <number>] [--json]
```

The noun (asset) MUST come before the verb (attention).

Renaming, reordering, or collapsing this verb into flags is a breaking change and requires updating this contract.

## Parameters

### Filtering Options

- **Collection Filter**: 
  - `--collection <collection_uuid>`: Filter assets by collection UUID
  - Only assets from the specified collection are returned

- **Limit**: 
  - `--limit <number>`: Maximum number of results to return (default: 100)
  - Used to prevent overwhelming output for large result sets

### Output Options

- `--json`: Output results in JSON format
- Default: Human-readable tabular format

## Exit Codes

- `0`: Success - assets listed (even if empty result)
- `1`: Error (invalid collection UUID, database error, etc.)

The command MUST NOT partially apply changes and still exit 0.

## Safety Expectations

### Read-Only Operation

- Asset attention is a read-only operation with no state changes
- No database writes occur during asset listing
- Safe for repeated use without side effects

### Attention Criteria

Assets appear in attention list when **all** of the following are true:
- Not soft-deleted (`is_deleted = false`)
- **AND** (`state = 'enriching'` **OR** `approved_for_broadcast = false`)

This ensures operators see:
1. Assets that are still being processed (`enriching` state)
2. Assets that are ready but not approved for broadcast
3. Assets that may have been downgraded during ingest

## Output Format

### Human-Readable Output

The human-readable output MUST display one asset per line with:

```
<uuid>  <state>      approved=<true|false>  <uri>
```

Example:
```
11111111-1111-1111-1111-111111111111  enriching   approved=False  /media/a.mp4
33333333-3333-3333-3333-333333333333  ready       approved=False  /media/b.mp4
```

**Special Case: Empty Result**
When no assets need attention, output:
```
No assets need attention
```

### JSON Output

When `--json` is passed, all output MUST be valid JSON with the following structure:

```json
{
  "status": "ok",
  "total": 2,
  "assets": [
    {
      "uuid": "11111111-1111-1111-1111-111111111111",
      "collection_uuid": "22222222-2222-2222-2222-222222222222",
      "uri": "/media/a.mp4",
      "state": "enriching",
      "approved_for_broadcast": false,
      "discovered_at": "2025-10-30T12:00:00Z"
    },
    {
      "uuid": "33333333-3333-3333-3333-333333333333",
      "collection_uuid": "22222222-2222-2222-2222-222222222222",
      "uri": "/media/b.mp4",
      "state": "ready",
      "approved_for_broadcast": false,
      "discovered_at": "2025-10-30T12:10:00Z"
    }
  ]
}
```

**Required Fields:**
- `status`: Always `"ok"` for successful queries
- `total`: Number of assets in the result set
- `assets`: Array of asset objects with required fields

**Asset Object Fields:**
- `uuid`: Asset UUID (string)
- `collection_uuid`: Collection UUID (string)
- `uri`: Asset URI/path (string)
- `state`: Lifecycle state (`new`, `enriching`, `ready`, `retired`)
- `approved_for_broadcast`: Boolean approval status
- `discovered_at`: ISO 8601 timestamp string

## Examples

```bash
# List all assets needing attention
retrovue asset attention

# List assets needing attention in a specific collection
retrovue asset attention --collection 22222222-2222-2222-2222-222222222222

# Limit results to 50 items
retrovue asset attention --limit 50

# Output as JSON
retrovue asset attention --json

# Filter by collection and output as JSON
retrovue asset attention --collection 22222222-2222-2222-2222-222222222222 --json
```

## Database Side Effects

### Read-Only Operation

- **No Database Changes**: Asset attention is a read-only operation
- **No State Persistence**: Listing does not modify asset records
- **No History Tracking**: Listing does not persist query history

### Query Behavior

- Results ordered by `discovered_at` descending (newest first)
- Soft-deleted assets are excluded
- Query uses indexed fields for performance

## Error Conditions

- **Invalid Collection UUID**: Raised if `--collection` value is not a valid UUID format
- **Collection Not Found**: Raised if specified collection UUID does not exist (should this exit 0 or 1? Current implementation treats missing collection as valid - returns empty list)
- **Database Error**: Raised if database query fails

## Contract Test Coverage

The following test methods must enforce this contract:

- `test_help_flag_exits_zero`: Validates help flag behavior
- `test_no_assets_needing_attention_prints_message_and_exits_zero`: Validates empty result handling
- `test_json_output_when_assets_present`: Validates JSON output format
- `test_collection_filter`: Validates collection filtering (if implemented)
- `test_limit_parameter`: Validates limit parameter (if implemented)

## Implementation Notes

- All listing operations must be read-only (no database writes)
- Query uses `state = 'enriching' OR approved_for_broadcast = false` with `is_deleted = false`
- Results are ordered by `discovered_at DESC`
- Limit is applied after ordering
- Empty result sets are valid and should exit with code 0
- JSON output must include all required fields with correct data types
- Error messages must be clear and actionable for operators

---

## Contract Lifecycle & Governance

This contract is the authoritative rulebook for `retrovue asset attention`.  
Follow this lifecycle for any change:

1. **Propose & Edit Contract**

   - Any change to operator-facing behavior must be proposed by editing this contract file first.
   - The change MUST include rationale and updated contract test list entries.

2. **Update Contract Tests**

   - Update or add tests under:
     - `tests/contracts/test_asset_attention_contract.py` (CLI/operator surface)
     - `tests/contracts/test_asset_attention_data_contract.py` (persistence/data effects)
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
- [Asset Resolve Contract](AssetResolveContract.md) - Resolve asset issues

