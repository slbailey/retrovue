# Source List Contract

> **This document is part of the RetroVue Contract System.**  
> Changes to this command MUST follow [CLI_CHANGE_POLICY.md](CLI_CHANGE_POLICY.md).  
> **Status: ENFORCED**

## Purpose

Define the behavioral contract for listing all configured sources in the RetroVue system. This contract ensures safe, consistent source enumeration with proper filtering, output formatting, and read-only operation guarantees.

---

## Command Shape

```
retrovue source list [--type <source_type>] [--json] [--test-db]
```

### Optional Parameters

- `--type <source_type>`:
  - Filter to only sources of that importer type (e.g. `plex`, `filesystem`)
  - `<source_type>` MUST be validated against the same set of known importer types surfaced by `retrovue source list-types` (see `SourceListTypesContract.md`)
  - If `<source_type>` is not a known type, the command MUST NOT return normal output, MUST exit code 1, and MUST emit the error form defined in this contract
- `--json`: Return machine-readable structured output
- `--test-db`: Query the isolated test database instead of production

---

## Safety Expectations

### Read-Only Operation

- **Non-destructive operation**: Only lists existing sources
- **Idempotent**: Safe to run multiple times
- **No mutation**: MUST NOT create, modify, or delete Sources, Collections, or any ingestion state
- **Production safe**: MUST be safe to run in production at any time
- **Test isolation**: `--test-db` MUST ensure no production data is read and no test data is leaked into production views

### Filtering Behavior

- `--type` MUST restrict results to sources whose type exactly matches a known importer type
- `--type` with an unknown type MUST produce no data changes and MUST exit 1 with an error message
- No destructive flags, no mutation, no pagination yet (pagination MAY be added later)

---

## Output Format

### Human-Readable Output

**With Sources:**

```
Configured sources:
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Name: My Plex Server
  Type: plex
  Enabled Collections: 2
  Ingestible Collections: 1
  Created: 2024-01-15 10:30:00
  Updated: 2024-01-20 14:45:00

  ID: 8c3d12f4-e9a1-4b2c-d6e7-1f8a9b0c2d3e
  Name: Local Media Library
  Type: filesystem
  Enabled Collections: 0
  Ingestible Collections: 3
  Created: 2024-01-10 09:15:00
  Updated: 2024-01-18 16:20:00

Total: 2 sources configured
```

**With Type Filter:**

```
Plex sources:
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Name: My Plex Server
  Type: plex
  Enabled Collections: 2
  Ingestible Collections: 1
  Created: 2024-01-15 10:30:00
  Updated: 2024-01-20 14:45:00

Total: 1 plex source configured
```

**No Sources:**

```
No sources configured

Total: 0 sources configured
```

### JSON Output

**With Sources:**

```json
{
  "status": "ok",
  "total": 2,
  "sources": [
    {
      "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
      "name": "My Plex Server",
      "type": "plex",
      "enabled_collections": 2,
      "ingestible_collections": 1,
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-20T14:45:00Z"
    },
    {
      "id": "8c3d12f4-e9a1-4b2c-d6e7-1f8a9b0c2d3e",
      "name": "Local Media Library",
      "type": "filesystem",
      "enabled_collections": 0,
      "ingestible_collections": 3,
      "created_at": "2024-01-10T09:15:00Z",
      "updated_at": "2024-01-18T16:20:00Z"
    }
  ]
}
```

**No Sources:**

```json
{
  "status": "ok",
  "total": 0,
  "sources": []
}
```

---

## Exit Codes

- `0`: Command runs successfully, even if it returns zero results. Also applies in `--test-db` if the query succeeds.
- `1`: Invalid filter (e.g., `--type` specifies a source type that does not exist in the importer registry), database query failure, or `--test-db` is provided but the test environment/session cannot be acquired

---

## Data Effects

### Database Queries

1. **Source Table**: Query persisted Source records
2. **Collection Counting**: Calculate enabled_collections and ingestible_collections from associated Collection rows
3. **Snapshot Consistency**: Snapshot consistency requirements for this command are defined by the Consistent Read Snapshot guarantee in CLI_Data_Guarantees.md. This command MUST comply.
4. **No Mutations**: Read-only operations only

### Side Effects

- No external system calls (importers, Plex APIs, filesystem scans, etc.)
- No database modifications
- No importer registry state changes
- No collection ingest state changes

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST return all known sources unless filtered by `--type`.
- **B-2:** `--type <source_type>` MUST restrict results to sources whose `type` exactly matches `<source_type>`, where `<source_type>` is a valid importer type as defined by `SourceListTypesContract.md`.
- **B-3:** If `<source_type>` is not a valid importer type according to `SourceListTypesContract.md`, the command MUST produce no data output, MUST exit 1, and MUST print the error message:
  `Error: Unknown source type '<value>'. Available types: <comma-separated list from registry>`
- **B-4:** `--json` MUST return valid JSON output with the required fields (`status`, `total`, `sources`).
- **B-5:** The output MUST be deterministic. Results MUST be sorted by source name ascending (case-insensitive). If two sources share the same name, they MUST be secondarily sorted by id ascending.
- **B-6:** When there are no results, output MUST still be structurally valid (empty table in human mode, empty list in JSON mode).
- **B-7:** The command MUST be read-only and MUST NOT mutate database state, importer registry state, or collection ingest state.
- **B-8:** `--test-db` MUST query the test DB session instead of production.
- **B-9:** `--test-db` MUST keep response shape and exit code behavior identical to production mode.
- **B-10:** The command MUST NOT call external systems (importers, Plex APIs, filesystem scans, etc.). It is metadata-only.

---

## Data Contract Rules (D-#)

- **D-1:** The list of sources MUST reflect persisted Source records at the time of query.
- **D-2:** Each returned source MUST include the correct latest type, name, and config-derived identity from the authoritative Source model.
- **D-3:** The enabled_collections and ingestible_collections counts MUST be calculated from persisted Collection rows associated to that source.
- **D-4:** The command MUST NOT infer or fabricate ingest state; it MUST use stored data only.
- **D-5:** The command MUST NOT create or modify Collections while counting or summarizing them.
- **D-6:** Querying via `--test-db` MUST NOT read or leak production data.
- **D-7:** This command MUST comply with the Consistent Read Snapshot guarantee (G-7) defined in CLI_Data_Guarantees.md.

---

## JSON Response Contract

### Required Fields

The JSON response MUST include these top-level fields:

- `"status"`: Always `"ok"` for successful execution
- `"total"`: Integer count of sources returned
- `"sources"`: Array of source objects

### Source Object Fields

Each source in the `"sources"` array MUST include:

- `"id"`: Source UUID
- `"name"`: Human-readable source name
- `"type"`: Source type identifier (e.g., "plex", "filesystem")
- `"enabled_collections"`: Number of collections with sync enabled (`sync_enabled=true`)
- `"ingestible_collections"`: Number of collections currently ingestible (`ingestible=true`)
- `"created_at"`: ISO 8601 timestamp of source creation
- `"updated_at"`: ISO 8601 timestamp of last source update

### Field Evolution Policy

- **Adding new fields**: Allowed (non-breaking change)
- **Removing or renaming existing fields**: Breaking change requiring contract update and migration
- **Changing field types**: Breaking change requiring contract update and migration

---

## Test Responsibilities

### Test Files

Tests for this contract MUST live in:

- `tests/contracts/test_source_list_contract.py` (behavior contract tests)
- `tests/contracts/test_source_list_data_contract.py` (data contract tests)

### Test Coverage

Each B-# and D-# rule MUST be asserted by at least one test.

### CI Enforcement

Once this contract is marked **ENFORCED** in `tests/CONTRACT_MIGRATION.md`, CI MUST run these tests and block merge on failure.

---

## Cross-Domain Interactions

### Read-Only Nature

The `retrovue source list` command is read-only and does not engage:

- Importer logic
- Enricher logic
- Collection mutation logic

### Test Database Behavior

`--test-db` behavior must follow [CLI_Data_Guarantees.md](cross-domain/CLI_Data_Guarantees.md).

### Collection State Alignment

The `enabled_collections` and `ingestible_collections` counts must match the Collection domain definition of `sync_enabled` and `ingestible`, but the command MUST NOT attempt to auto-fix or validate them.

---

## Examples

### Basic Listing

```bash
# List all sources
retrovue source list

# List with JSON output
retrovue source list --json

# Filter by type
retrovue source list --type plex
```

### Test Environment Usage

```bash
# Query test database
retrovue source list --test-db

# Test with JSON output
retrovue source list --test-db --json

# Test with type filter
retrovue source list --test-db --type filesystem
```

### Error Scenarios

```bash
# Invalid source type
retrovue source list --type unknown
# Exit code: 1
# Error: Unknown source type 'unknown'. Available types: plex, filesystem

# Database connection failure
retrovue source list
# Exit code: 1
# Error: Database operation failed: Connection timeout
```

---

## See Also

- [Source Add](SourceAddContract.md) - Creating sources with importer validation
- [Source List Types](SourceListTypesContract.md) - Listing available source types (defines the registry used for --type validation)
- [CLI Data Guarantees](cross-domain/CLI_Data_Guarantees.md) - Cross-domain interaction guarantees
- [CLI Change Policy](CLI_CHANGE_POLICY.md) - CLI governance policy
