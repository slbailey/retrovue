# Asset Show Contract

## Purpose

Define the operator interface for displaying detailed asset information in RetroVue. This contract ensures consistent, predictable behavior when viewing asset details through the CLI.

## Scope

This contract applies to the `retrovue asset show <asset_id>` command, covering asset information display with various identification methods and output formats.

## Design Principles

- **Flexibility:** Support multiple identification methods (UUID, external ID, or display name)
- **Clarity:** Output must be clear and comprehensive for operators
- **Consistency:** JSON output format must be structured and predictable
- **Safety:** Read-only operation with no state changes

## CLI Syntax

The Retrovue CLI MUST expose asset display using the pattern:

```
retrovue asset show <asset_id> [--json] [--test-db]
```

The noun (asset) MUST come before the verb (show).

Renaming, reordering, or collapsing this verb into flags is a breaking change and requires updating this contract.

## Parameters

- **Asset Identifier** (required): `<asset_id>` can be:

  - Full UUID (e.g., `123e4567-e89b-12d3-a456-426614174000`)
  - External ID (e.g., Plex rating key: `plex-12345`)
  - URI path (for filesystem sources)

- **Output Options**:
  - `--json`: Output results in JSON format
  - `--test-db`: Use test database for resolution and validation

## Exit Codes

- `0`: Success - asset found and displayed
- `1`: Error (asset not found, invalid identifier, validation failure, etc.)

The command MUST NOT partially apply changes and still exit 0.

If the asset cannot be found or identifier is invalid, the overall exit code MUST be non-zero.

## Safety Expectations

### Read-Only Operation

- Asset show is a read-only operation with no state changes
- No database writes occur during asset display
- Safe for repeated use without side effects

### Identification Methods

Asset can be identified by:

- **UUID** (primary method): Full UUID string
- **External ID**: External system identifier (e.g., Plex rating key)
- **URI**: File system path or URI (for filesystem sources)

### Ambiguity Handling

- If multiple assets match a non-unique identifier (e.g., URI path), the command MUST exit with code 1 and emit: "Multiple assets match '<identifier>'. Please specify the UUID."
- UUID identification is always unambiguous
- External ID identification must be unique within the system

## Output Format

### Human-Readable Output

The human-readable output MUST include:

- **Asset UUID**: Primary identifier
- **Title**: Asset title (if available)
- **URI**: File system path or URI
- **Size**: File size in bytes
- **Duration**: Duration in milliseconds
- **State**: Lifecycle state (`new`, `enriching`, `ready`, `retired`)
- **Canonical**: Approval status for downstream schedulers
- **Approved for Broadcast**: Broadcast approval status
- **Collection**: Collection name and UUID
- **Technical Metadata**: Video codec, audio codec, container
- **Discovery Timestamp**: When asset was first discovered
- **Delete Status**: Soft delete status (if applicable)
- **Relationships**: Episodes, markers, review queue items (if applicable)

### JSON Output

When `--json` is passed, all output MUST be valid JSON with the following structure:

```json
{
  "uuid": "123e4567-e89b-12d3-a456-426614174000",
  "uri": "/path/to/asset.mp4",
  "size": 1234567890,
  "duration_ms": 3600000,
  "video_codec": "h264",
  "audio_codec": "aac",
  "container": "mp4",
  "state": "ready",
  "canonical": true,
  "approved_for_broadcast": true,
  "is_deleted": false,
  "deleted_at": null,
  "discovered_at": "2024-01-01T12:00:00Z",
  "collection": {
    "uuid": "collection-uuid",
    "name": "TV Shows",
    "source": {
      "uuid": "source-uuid",
      "name": "My Plex Server"
    }
  },
  "episodes": [
    {
      "uuid": "episode-uuid",
      "title": "Episode Title",
      "season_number": 1,
      "episode_number": 1
    }
  ],
  "markers": [],
  "review_queue": [],
  "provider_refs": [
    {
      "provider": "plex",
      "provider_key": "12345"
    }
  ]
}
```

## Examples

```bash
# Show asset by UUID
retrovue asset show 123e4567-e89b-12d3-a456-426614174000

# Show asset by UUID with JSON output
retrovue asset show 123e4567-e89b-12d3-a456-426614174000 --json

# Show asset by external ID
retrovue asset show plex-12345

# Show asset by URI path (filesystem source)
retrovue asset show "/media/movies/The Matrix.mp4"
```

## Database Side Effects

### Read-Only Operation

- **No Database Changes**: Asset show is a read-only operation
- **No State Persistence**: Display does not modify asset records
- **No History Tracking**: Display does not persist viewing history

## Error Conditions

- **Asset Not Found**: Returned when no matching asset exists for the provided identifier
- **Invalid UUID Format**: Raised if the provided UUID cannot be parsed (malformed or not a valid UUIDv4 string)
- **Ambiguous Identifier**: Raised if multiple assets match a non-unique identifier (e.g., URI path)
- **Invalid External ID**: Raised if external ID format is invalid or cannot be resolved

## Contract Test Coverage

The following test methods must enforce this contract:

- `test_asset_show_by_uuid`: Validates asset display by UUID
- `test_asset_show_by_uuid_json`: Validates JSON output format
- `test_asset_show_by_external_id`: Validates asset display by external ID
- `test_asset_show_not_found`: Validates error handling for non-existent assets
- `test_asset_show_invalid_uuid`: Validates error handling for invalid UUID format
- `test_asset_show_ambiguous_identifier`: Validates error handling for ambiguous identifiers

## Implementation Notes

- All display operations must be read-only (no database writes)
- UUID identification must be case-sensitive and exact
- External ID identification must resolve to a single asset
- URI identification must handle filesystem path normalization
- JSON output must include all required fields with correct data types
- Error messages must be clear and actionable for operators

---

## Contract Lifecycle & Governance

This contract is the authoritative rulebook for `retrovue asset show`.  
Follow this lifecycle for any change:

1. **Propose & Edit Contract**

   - Any change to operator-facing behavior must be proposed by editing this contract file first.
   - The change MUST include rationale and updated contract test list entries.

2. **Update Contract Tests**

   - Update or add tests under:
     - `tests/contracts/test_asset_show_contract.py` (CLI/operator surface)
     - `tests/contracts/test_asset_show_data_contract.py` (persistence/data effects)
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
- [Collection Show Contract](CollectionShowContract.md) - Collection display operations

