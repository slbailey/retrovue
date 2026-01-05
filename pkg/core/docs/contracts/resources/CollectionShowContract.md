# Collection Show

## Purpose

Define the behavioral contract for displaying detailed information about a single collection. This contract ensures consistent collection identification, clear error handling for ambiguous names, and comprehensive collection metadata display.

---

## Command Shape

```
retrovue collection show <collection_id> [--json] [--test-db]
```

### Required Parameters

- `<collection_id>`: Collection identifier (UUID, external ID, or display name)

### Optional Parameters

- `--json`: Output result in JSON format
- `--test-db`: Direct command to test database environment

---

## Safety Expectations

### Collection Identification

- Collection MUST be searchable by UUID, external ID, or case-insensitive display name
- Collection name matching MUST be case-insensitive
- If multiple collections match the provided name (case-insensitive), the command MUST exit with code 1 and emit: "Multiple collections named '<name>' exist. Please specify the UUID."
- Resolution MUST NOT prefer one collection over another, even if one has exact casing match
- External ID resolution MUST match exactly (no partial matching)

### Ambiguity Resolution

- When name lookup returns multiple matches (case-insensitive), the command MUST NOT display any collection information
- Error message MUST be: "Multiple collections named '<name>' exist. Please specify the UUID."
- Resolution MUST NOT prefer one collection over another based on casing match

---

## Output Format

### Human-Readable Output

**Success Output:**

```
Collection: TV Shows
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  External ID: plex-5063d926-1
  Source: My Plex Server (plex-5063d926)
  Type: plex
  Sync Enabled: true
  Ingestible: true
  Path Mappings:
    Plex Path: /library/sections/1
    Local Path: /media/tv-shows
  Assets: 2,931
  Last Ingest: 2024-01-15 10:30:00
  Created: 2024-01-15 10:30:00
  Updated: 2024-01-20 14:22:00
```

### JSON Output

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926-1",
  "name": "TV Shows",
  "source_id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "source_name": "My Plex Server",
  "source_type": "plex",
  "sync_enabled": true,
  "ingestible": true,
  "path_mappings": {
    "plex_path": "/library/sections/1",
    "local_path": "/media/tv-shows"
  },
  "stats": {
    "assets_count": 2931
  },
  "last_ingest_time": "2024-01-15T10:30:00Z",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-20T14:22:00Z"
}
```

---

## Exit Codes

- `0`: Collection found and displayed successfully
- `1`: Validation error, collection not found, or ambiguous name (multiple matches)

---

## Data Effects

### Database Changes

- No database modifications occur (read-only operation)
- No side effects on collection state or relationships

### Side Effects

- Database query for collection lookup
- Path mapping validation (if applicable)
- Prerequisites validation check (if applicable)

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST accept `<collection_id>` as any of: full UUID, external ID (e.g. Plex library key), or case-insensitive display name. Collection name matching MUST be case-insensitive.
- **B-2:** If multiple collections match the provided name (case-insensitive), the command MUST exit with code 1 and emit: "Multiple collections named '<name>' exist. Please specify the UUID." Collection name matching MUST be case-insensitive. Resolution MUST NOT prefer one collection over another, even if one has exact casing match.
- **B-3:** If no collection matches the provided identifier, the command MUST exit with code 1 and emit: "Error: Collection 'X' not found."
- **B-4:** When `--json` is supplied, output MUST include fields: `"id"`, `"external_id"`, `"name"`, `"source_id"`, `"source_name"`, `"source_type"`, `"sync_enabled"`, `"ingestible"`, `"path_mappings"`, `"stats"`, `"last_ingest_time"`, `"created_at"`, and `"updated_at"`.
- **B-5:** The command MUST display `sync_enabled` and `ingestible` status clearly in both human-readable and JSON output, as these are critical prerequisites for ingest operations.
- **B-6:** If `ingestible=false`, the output SHOULD include diagnostic information about why the collection is not ingestible (e.g., missing path mappings, invalid configuration).
- **B-7:** UUID resolution MUST be exact match (case-sensitive).
- **B-8:** External ID resolution MUST be exact match (case-sensitive).
- **B-9:** Display name resolution MUST be case-insensitive, matching against the `name` field of collections.
- **B-10:** When run with `--test-db`, no changes may affect production or staging databases.

---

## Data Contract Rules (D-#)

- **D-1:** Collection lookup MUST be read-only and MUST NOT modify any database state.
- **D-2:** Collection resolution MUST query the authoritative collection table(s) and MUST NOT rely on cached or stale data.
- **D-3:** External ID lookup MUST resolve against the collection's `external_id` field.
- **D-4:** Display name lookup MUST resolve against the collection's `name` field using case-insensitive matching.
- **D-5:** UUID lookup MUST resolve against the collection's primary key UUID field.
- **D-6:** If multiple collections share the same name (case-insensitive), the query MUST return all matching collections for ambiguity detection. Resolution MUST NOT prefer one collection over another based on casing match.
- **D-7:** Path mapping information MUST be retrieved from the PathMapping table associated with the collection.
- **D-8:** Source information MUST be retrieved from the Source table via foreign key relationship.
- **D-9:** Asset count statistics MUST reflect the current state of assets in the database.
- **D-10:** The `last_ingest_time` field MUST be retrieved from the collection record and MUST reflect the timestamp of the most recent successful ingest operation.
- **D-11:** All operations run with `--test-db` MUST be isolated from production database storage, tables, and triggers.

---

## Test Coverage Mapping

- `B-1..B-10` → `test_collection_show_contract.py`
- `D-1..D-11` → `test_collection_show_data_contract.py`

Each rule above MUST have explicit test coverage in its respective test file, following the contract test responsibilities in [README.md](./README.md).  
Each test file MUST reference these rule IDs in docstrings or comments to provide bidirectional traceability.

Future related tests (integration or scenario-level) MAY reference these same rule IDs for coverage mapping but must not redefine behavior.

---

## Error Conditions

### Validation Errors

- Collection not found: "Error: Collection 'invalid-name' not found."
- Ambiguous name: "Multiple collections named 'Movies' exist. Please specify the UUID."
- Invalid UUID format: "Error: Invalid collection ID format. Expected UUID, external ID, or collection name."

---

## Examples

### Basic Collection Show

```bash
# Show collection by UUID
retrovue collection show 4b2b05e7-d7d2-414a-a587-3f5df9b53f44

# Show collection by external ID
retrovue collection show plex-5063d926-1

# Show collection by name
retrovue collection show "TV Shows"

# Show collection with JSON output
retrovue collection show "TV Shows" --json
```

### Error Cases

```bash
# Invalid: Collection not found
retrovue collection show "Non-existent Collection"
# Error: Collection 'Non-existent Collection' not found.

# Invalid: Ambiguous name
retrovue collection show "Movies"
# Error: Multiple collections named 'Movies' exist. Please specify the UUID.

# Valid: Use ID to disambiguate
retrovue collection show 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
# Success: Shows collection details
```

### Test Environment Usage

```bash
# Test collection show in isolated environment
retrovue collection show "Test Collection" --test-db

# Test with JSON output
retrovue collection show "Test Collection" --test-db --json
```

---

## Relationship to Collection Ingest

The `collection show` command is a prerequisite operation for `collection ingest`:

- **Pre-flight Validation**: Operators use `collection show` to verify `sync_enabled` and `ingestible` status before attempting ingest
- **Diagnostic Tool**: When ingest fails due to prerequisites, `collection show` provides diagnostic information
- **ID Resolution**: Both commands use the same ID resolution logic (UUID, external ID, or name)
- **Ambiguity Handling**: Both commands handle ambiguous names consistently

---

## See Also

- [Collection Ingest](CollectionIngestContract.md) - Ingest operations that depend on collection identification
- [Collection Contract](CollectionContract.md) - Overview of all collection operations
- [Source Discover](SourceDiscoverContract.md) - Collection discovery operations
