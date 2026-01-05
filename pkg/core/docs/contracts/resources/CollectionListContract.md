# Collection List Contract

## Purpose

Define the behavioral contract for listing collections in the RetroVue system. This contract ensures safe, consistent collection enumeration with proper filtering by source, output formatting, and read-only operation guarantees.

---

## Command Shape

```
retrovue collection list [<source_id>] [--source <source_id>] [--json] [--test-db]
```

### Parameters

- `<source_id>` (positional, optional): Filter to only collections belonging to the specified source. Can be provided as a positional argument OR via `--source` flag.
- `--source <source_id>` (optional): Filter to only collections belonging to the specified source. If both positional and `--source` are provided, `--source` takes precedence.
  - The source identifier can be:
    - Full UUID
    - External ID (e.g., `plex-5063d926`)
    - Case-insensitive display name
    - If multiple sources match the provided name, the command MUST exit with code 1 and emit an error message directing the operator to use an ID
- `--json`: Return machine-readable structured output
- `--test-db`: Query the isolated test database instead of production

**Note**: Either `<source_id>` positional argument OR `--source` flag can be used to filter by source. If neither is provided, all collections across all sources are returned.

---

## Safety Expectations

### Read-Only Operation

- **Non-destructive operation**: Only lists existing collections
- **Idempotent**: Safe to run multiple times
- **No mutation**: MUST NOT create, modify, or delete Collections, Sources, or any ingestion state
- **Production safe**: MUST be safe to run in production at any time
- **Test isolation**: `--test-db` MUST ensure no production data is read and no test data is leaked into production views

### Filtering Behavior

- Without source filter (no positional argument and no `--source`): Returns all collections across all sources
- With source filter (positional argument OR `--source`): Returns only collections belonging to the specified source
- If both positional argument and `--source` are provided, `--source` takes precedence
- Source identification MUST follow the same resolution rules as `source show` (UUID, external ID, or case-insensitive name, with ambiguity handling)
- If source is not found, the command MUST exit with code 1 and emit: "Error: Source 'X' not found."
- If multiple sources match the provided name, the command MUST exit with code 1 and emit: "Error: Multiple sources found with name 'X'. Use source ID to disambiguate: <id1>, <id2>, ..."

---

## Output Format

### Human-Readable Output

**All Collections (no --source):**

```
Collections:
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Name: TV Shows
  Source: My Plex Server (plex-5063d926)
  Type: plex
  Sync Enabled: true
  Ingestible: true
  Path Mappings:
    • /media/tv_shows -> (unmapped)
  Assets: 2,931
  Last Ingest: 2024-01-15 10:30:00
  Created: 2024-01-15 10:30:00

  ID: 8c3d16f8-e8e3-525b-b698-4g6ef0c64e55
  Name: Movies
  Source: My Plex Server (plex-5063d926)
  Type: plex
  Sync Enabled: false
  Ingestible: true
  Assets: 0
  Last Ingest: Never
  Created: 2024-01-15 10:32:00

  ID: 9d4e27g9-f9f4-636c-c7d9-5h7fg1h2i3j4
  Name: Music
  Source: Local Media Library (filesystem-a1b2c3d4)
  Type: filesystem
  Sync Enabled: true
  Ingestible: true
  Assets: 456
  Last Ingest: 2024-01-18 16:20:00
  Created: 2024-01-10 09:15:00

Total: 3 collections
```

**Filtered by Source:**

```
Collections for source "My Plex Server":
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Name: TV Shows
  Source: My Plex Server (plex-5063d926)
  Type: plex
  Sync Enabled: true
  Ingestible: true
  Assets: 2,931
  Last Ingest: 2024-01-15 10:30:00
  Created: 2024-01-15 10:30:00

  ID: 8c3d16f8-e8e3-525b-b698-4g6ef0c64e55
  Name: Movies
  Source: My Plex Server (plex-5063d926)
  Type: plex
  Sync Enabled: false
  Ingestible: true
  Assets: 0
  Last Ingest: Never
  Created: 2024-01-15 10:32:00

Total: 2 collections
```

**No Collections:**

```
No collections found

Total: 0 collections
```

### JSON Output

**All Collections (no --source):**

```json
{
  "status": "ok",
  "total": 3,
  "collections": [
    {
      "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
      "external_id": "plex-5063d926-1",
      "name": "TV Shows",
      "source_id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
      "source_name": "My Plex Server",
      "source_type": "plex",
      "sync_enabled": true,
      "ingestible": true,
      "assets_count": 2931,
      "last_ingest_time": "2024-01-15T10:30:00Z",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-20T14:22:00Z",
      "mapping_pairs": [
        { "plex_path": "/media/tv_shows", "local_path": null }
      ]
    },
    {
      "id": "8c3d16f8-e8e3-525b-b698-4g6ef0c64e55",
      "external_id": "plex-5063d926-2",
      "name": "Movies",
      "source_id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
      "source_name": "My Plex Server",
      "source_type": "plex",
      "sync_enabled": false,
      "ingestible": true,
      "assets_count": 0,
      "last_ingest_time": null,
      "created_at": "2024-01-15T10:32:00Z",
      "updated_at": "2024-01-15T10:32:00Z"
    },
    {
      "id": "9d4e27g9-f9f4-636c-c7d9-5h7fg1h2i3j4",
      "external_id": "filesystem-a1b2c3d4-1",
      "name": "Music",
      "source_id": "8c3d12f4-e9a1-4b2c-d6e7-1f8a9b0c2d3e",
      "source_name": "Local Media Library",
      "source_type": "filesystem",
      "sync_enabled": true,
      "ingestible": true,
      "assets_count": 456,
      "last_ingest_time": "2024-01-18T16:20:00Z",
      "created_at": "2024-01-10T09:15:00Z",
      "updated_at": "2024-01-18T16:20:00Z"
    }
  ]
}
```

**Filtered by Source:**

```json
{
  "status": "ok",
  "source": {
    "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
    "name": "My Plex Server",
    "type": "plex"
  },
  "total": 2,
  "collections": [
    {
      "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
      "external_id": "plex-5063d926-1",
      "name": "TV Shows",
      "source_id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
      "source_name": "My Plex Server",
      "source_type": "plex",
      "sync_enabled": true,
      "ingestible": true,
      "assets_count": 2931,
      "last_ingest_time": "2024-01-15T10:30:00Z",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-20T14:22:00Z"
    },
    {
      "id": "8c3d16f8-e8e3-525b-b698-4g6ef0c64e55",
      "external_id": "plex-5063d926-2",
      "name": "Movies",
      "source_id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
      "source_name": "My Plex Server",
      "source_type": "plex",
      "sync_enabled": false,
      "ingestible": true,
      "assets_count": 0,
      "last_ingest_time": null,
      "created_at": "2024-01-15T10:32:00Z",
      "updated_at": "2024-01-15T10:32:00Z"
    }
  ]
}
```

**No Collections:**

```json
{
  "status": "ok",
  "total": 0,
  "collections": []
}
```

---

## Exit Codes

- `0`: Command runs successfully, even if it returns zero results. Also applies in `--test-db` if the query succeeds.
- `1`: Source not found, source name ambiguous (multiple matches), database query failure, or `--test-db` is provided but the test environment/session cannot be acquired

---

## Tests
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__help_flag
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b1_lists_all_collections
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b2_resolves_source_by_uuid
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b2_resolves_source_by_external_id
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b2_resolves_source_by_name
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b3_errors_when_source_missing
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b4_errors_when_source_ambiguous
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b5_filters_collections_by_source
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b6_returns_structured_json
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b7_output_is_deterministic
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b8_reports_no_collections
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b9_is_read_only
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b10_b11_test_db_uses_isolated_session
- [x] tests/contracts/test_collection_list_contract.py::test_collection_list_contract__b12_skips_external_systems

## Data Effects

### Database Queries

1. **Collection Table**: Query persisted Collection records
2. **Source Join**: If `--source` is provided, filter collections by source ID
3. **Asset Counting**: Calculate asset counts from associated Asset rows
4. **Snapshot Consistency**: Snapshot consistency requirements for this command are defined by the Consistent Read Snapshot guarantee in CLI_Data_Guarantees.md. This command MUST comply.
5. **No Mutations**: Read-only operations only

### Side Effects

- No external system calls (importers, Plex APIs, filesystem scans, etc.)
- No database modifications
- No collection state changes
- No source state changes

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST return all known collections unless filtered by `--source`.
- **B-2:** When `--source` is provided, the source identifier MUST be resolved using the same logic as `source show` (UUID, external ID, or case-insensitive name).
- **B-3:** If `--source` is provided and no source matches the identifier, the command MUST exit with code 1 and emit: "Error: Source 'X' not found."
- **B-4:** If `--source` is provided and multiple sources match the provided name (case-insensitive), the command MUST exit with code 1 and emit: "Error: Multiple sources found with name 'X'. Use source ID to disambiguate: <id1>, <id2>, ..."
- **B-5:** When `--source` is provided, only collections belonging to that source MUST be returned.
- **B-6:** `--json` MUST return valid JSON output with the required fields (`status`, `total`, `collections`, and optionally `source` when `--source` is provided). Each collection object in the `collections` array MUST include: `id`, `external_id`, `name`, `source_id`, `source_name`, `source_type`, `sync_enabled`, `ingestible`, `assets_count`, `last_ingest_time` (nullable), `created_at`, and `updated_at`.
- **B-7:** The output MUST be deterministic. Results MUST be sorted by source name ascending (case-insensitive), then by collection name ascending (case-insensitive). If collections share the same names, they MUST be secondarily sorted by id ascending.
- **B-8:** When there are no results, output MUST still be structurally valid (empty table in human mode, empty list in JSON mode).
- **B-9:** The command MUST be read-only and MUST NOT mutate database state, source state, or collection ingest state.
- **B-10:** `--test-db` MUST query the test DB session instead of production.
- **B-11:** `--test-db` MUST keep response shape and exit code behavior identical to production mode.
- **B-12:** The command MUST NOT call external systems (importers, Plex APIs, filesystem scans, etc.). It is metadata-only.

---

## Data Contract Rules (D-#)

- **D-1:** The list of collections MUST reflect persisted Collection records at the time of query.
- **D-2:** Each returned collection MUST include the correct latest metadata (sync_enabled, ingestible, etc.) from the authoritative Collection model.
- **D-3:** Asset counts MUST be calculated from persisted Asset rows associated to each collection.
- **D-4:** Source information MUST be retrieved from the Source table via foreign key relationship.
- **D-5:** The command MUST NOT infer or fabricate collection state; it MUST use stored data only.
- **D-6:** The command MUST NOT create or modify Collections while listing or summarizing them.
- **D-7:** Querying via `--test-db` MUST NOT read or leak production data.
- **D-8:** This command MUST comply with the Consistent Read Snapshot guarantee (G-7) defined in CLI_Data_Guarantees.md.
- **D-9:** When `--source` is provided, the source lookup MUST occur before collection querying, and collections MUST be filtered by the resolved source ID.

---

## Test Coverage Mapping

- `B-1..B-12` → `test_collection_list_contract.py`
- `D-1..D-9` → `test_collection_list_data_contract.py`

Each rule above MUST have explicit test coverage in its respective test file, following the contract test responsibilities in [README.md](./README.md).  
Each test file MUST reference these rule IDs in docstrings or comments to provide bidirectional traceability.

Future related tests (integration or scenario-level) MAY reference these same rule IDs for coverage mapping but must not redefine behavior.

---

## Error Conditions

### Validation Errors

- Source not found: "Error: Source 'invalid-name' not found."
- Ambiguous source name: "Error: Multiple sources found with name 'My Server'. Use source ID to disambiguate: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44, 8c3d16f8-e8e3-525b-b698-4g6ef0c64e55"
- Database query failure: Exit code 1 with diagnostic information

---

## Examples

### Basic Listing

```bash
# List all collections
retrovue collection list

# List with JSON output
retrovue collection list --json

# List collections for a specific source by name (using --source flag)
retrovue collection list --source "My Plex Server"

# List collections for a specific source by name (using positional argument)
retrovue collection list "My Plex Server"

# List collections for a specific source by UUID (using --source flag)
retrovue collection list --source 4b2b05e7-d7d2-414a-a587-3f5df9b53f44

# List collections for a specific source by UUID (using positional argument)
retrovue collection list 4b2b05e7-d7d2-414a-a587-3f5df9b53f44

# List collections for a specific source by external ID (using --source flag)
retrovue collection list --source plex-5063d926

# List collections for a specific source by external ID (using positional argument)
retrovue collection list plex-5063d926

# List collections with JSON output (positional source)
retrovue collection list "My Plex Server" --json

# List collections with JSON output (using --source flag)
retrovue collection list --source "My Plex Server" --json
```

### Test Environment Usage

```bash
# Query test database
retrovue collection list --test-db

# Test with JSON output
retrovue collection list --test-db --json

# Test with source filter
retrovue collection list --test-db --source "Test Source"
```

### Error Scenarios

```bash
# Source not found
retrovue collection list --source "Non-existent Source"
# Exit code: 1
# Error: Source 'Non-existent Source' not found.

# Ambiguous source name
retrovue collection list --source "My Server"
# Exit code: 1
# Error: Multiple sources found with name 'My Server'. Use source ID to disambiguate: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44, 8c3d16f8-e8e3-525b-b698-4g6ef0c64e55

# Database connection failure
retrovue collection list
# Exit code: 1
# Error: Database operation failed: Connection timeout
```

---

## Relationship to Other Collection Operations

The `collection list` command provides collection discovery and enumeration:

- **Discovery Tool**: Operators use `collection list` to discover collections before using `collection show` or `collection update`
- **Source Filtering**: When filtering by source, operators can see all collections for a specific source
- **Status Overview**: Shows `sync_enabled` and `ingestible` status at a glance, helping operators identify collections that need configuration
- **Bulk Operations**: Provides collection IDs for use in bulk operations or scripting

---

## See Also

- [Collection Show](CollectionShowContract.md) - Displaying detailed collection information
- [Collection Update](CollectionUpdateContract.md) - Updating collection configuration and state
- [Collection Ingest](CollectionIngestContract.md) - Ingest operations
- [Source List](SourceListContract.md) - Listing sources
- [Source Show](SourceContract.md) - Source identification patterns
- [CLI Data Guarantees](cross-domain/CLI_Data_Guarantees.md) - Cross-domain interaction guarantees
