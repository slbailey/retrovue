# Source Add

## Purpose

Define the behavioral contract for adding new content sources to RetroVue. This contract ensures safe, consistent source creation with proper validation, configuration handling, and importer interface compliance verification.

---

## Command Shape

```
retrovue source add --type <type> --name <name> [options] [--discover] [--test-db] [--dry-run] [--json]
```

### Required Parameters

- `--type`: Source type identifier ("plex", "filesystem")
- `--name`: Human-readable name for the source

### Type-Specific Parameters

**Plex Sources:**

- `--base-url`: Plex server base URL (required for plex type)
- `--token`: Plex authentication token (required for plex type)

**Filesystem Sources:**

- `--base-path`: Base filesystem path to scan (required for filesystem type)

### Optional Parameters

- `--enrichers`: Comma-separated list of enrichers to use
- `--discover`: Automatically discover and persist collections after source creation
- `--test-db`: Direct command to test database environment
- `--dry-run`: Show what would be created without executing
- `--json`: Output result in JSON format

---

## Safety Expectations

### Confirmation Model

- No confirmation prompts required for source creation
- `--dry-run` shows configuration validation and external ID generation
- `--force` flag not applicable (non-destructive operation)

### Validation Requirements

- Source type must be valid and correspond to a discovered importer
- Importer must be interface compliant (ImporterInterface). Implementations that subclass BaseImporter are considered compliant by construction. Non-compliant importers MUST cause the command to fail with exit code 1.
- Required parameters must be provided for each source type according to importer's configuration schema
- Configuration must be validated against importer's `get_config_schema()` method
- External ID must be unique (format: "type-hash")
- Configuration must be valid before database operations
- `--discover` option only applies to sources with discoverable collections (as declared by the importer)

### Dry-run Behavior

- In `--dry-run` mode, no database writes MAY occur
- On valid input, exit code MUST be 0 and output MUST match the normal `--json` shape
- On invalid input, exit code MUST be 1 and MUST emit the same human-readable error used in non-dry-run mode
- Dry-run human-readable output includes External ID for validation purposes (unlike normal output)

### Test Database Behavior

- In `--test-db` mode, ALL database writes MUST be isolated to a non-production test environment
- `--test-db` MUST NOT leak any writes to production databases or persistent storage
- When `--test-db` is combined with `--dry-run`, dry-run behavior takes precedence (no writes occur)
- Behavior, output format, and exit codes MUST remain identical to production mode
- External system calls (e.g., Plex API) in `--test-db` mode MAY use mock/stub implementations

---

## Output Format

### Human-Readable Output

**Without `--discover`:**

```
Successfully created plex source: My Plex Server
  Name: My Plex Server
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Type: plex
  Enrichers: ffprobe,metadata
```

**With `--discover`:**

```
Successfully created plex source: My Plex Server
  Name: My Plex Server
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Type: plex
  Enrichers: ffprobe,metadata

Discovering collections from Plex server...
  Discovered and persisted 3 collections (all disabled by default)

Use 'retrovue collection update <name> --sync-enable' to enable collections for sync
```

### JSON Output

**Note:** The `ingestible` field is not included in source creation output because ingestibility is determined at the collection level, not the source level. Source creation only validates that the importer interface is compliant and configuration is valid.

**Without `--discover`:**

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926",
  "name": "My Plex Server",
  "type": "plex",
  "config": {
    "servers": [
      { "base_url": "https://plex.example.com", "token": "***REDACTED***" }
    ]
  },
  "enrichers": ["ffprobe", "metadata"],
  "importer_name": "PlexImporter"
}
```

**With `--discover`:**

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926",
  "name": "My Plex Server",
  "type": "plex",
  "config": {
    "servers": [
      { "base_url": "https://plex.example.com", "token": "***REDACTED***" }
    ]
  },
  "enrichers": ["ffprobe", "metadata"],
  "importer_name": "PlexImporter",
  "collections_discovered": 3,
  "collections": [
    {
      "external_id": "1",
      "name": "Movies",
      "sync_enabled": false
    },
    {
      "external_id": "2",
      "name": "TV Shows",
      "sync_enabled": false
    },
    {
      "external_id": "3",
      "name": "Music",
      "sync_enabled": false
    }
  ]
}
```

---

## Exit Codes

- `0`: Source created successfully
- `1`: Validation error, missing parameters, or creation failure

---

## Data Effects

### Database Changes

1. **Source Table**: New record inserted with:

   - Generated UUID primary key
   - External ID in format "type-hash"
   - Source name and type
   - Configuration JSON
   - Created/updated timestamps

2. **Collection Discovery** (Plex sources with `--discover` only):
   - Automatic discovery of Plex libraries within the same Unit of Work
   - SourceCollection records created with `sync_enabled=False`
   - PathMapping records created with empty `local_path`
   - All discovery operations must be atomic with source creation

### Side Effects

- External ID generation (must be unique)
- Plex API calls for collection discovery (if `--discover` provided and not using `--test-db`)
- Filesystem path validation (filesystem sources)

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST validate source type against available importers before proceeding.
- **B-2:** Required parameters MUST be validated before any database operations.
- **B-3:** External ID MUST be generated in format "type-hash" and MUST be unique. External ID is stored internally and available in JSON output but is not displayed in human-readable output.
- **B-4:** When `--json` is supplied, output MUST include fields `"id"`, `"external_id"`, `"name"`, `"type"`, `"config"`, `"enrichers"`, and `"importer_name"`.
- **B-5:** On validation failure, the command MUST exit with code `1` and print a human-readable error message.
- **B-5a:** On discovery failure (when `--discover` is provided), the command MUST exit with code `1` and rollback all changes, including source creation.
- **B-6:** The `--dry-run` flag MUST show configuration validation and external ID generation without executing. In dry-run mode, no database writes MAY occur. On valid input, exit code MUST be 0 and output MUST match the normal `--json` shape. On invalid input, exit code MUST be 1 and MUST emit the same human-readable error used in non-dry-run mode.
- **B-6a:** The `--test-db` flag MUST isolate ALL database writes to a non-production test environment. `--test-db` MUST NOT leak any writes to production databases or persistent storage.
- **B-6b:** When `--test-db` is combined with `--dry-run`, dry-run behavior takes precedence (no writes occur).
- **B-6c:** Behavior, output format, and exit codes MUST remain identical to production mode when using `--test-db`.
- **B-7:** The `--discover` flag MUST trigger immediate collection discovery if (and only if) the importer for this source type declares that it supports discovery. If discovery is not supported, the flag MUST be ignored with a warning, not treated as an error.
- **B-8:** When `--discover` is provided with `--json`, output MUST include `"collections_discovered"` and `"collections"` fields.
- **B-9:** Collection discovery MUST NOT occur unless `--discover` is explicitly provided.
- **B-10:** Source type MUST correspond to a discovered importer that implements `ImporterInterface`.
- **B-11:** Configuration parameters MUST be validated against importer's `get_config_schema()` method.
- **B-12:** Interface compliance MUST be verified before source creation.

---

## Data Contract Rules (D-#)

- **D-1:** Source creation MUST occur within a single transaction boundary.
- **D-2:** External ID generation MUST be atomic and collision-free.
- **D-3:** Collection discovery (when `--discover` is provided) MUST occur within the same transaction as source creation, following Unit of Work principles.
- **D-4:** Newly discovered collections MUST be persisted with `sync_enabled=False`.
- **D-5:** PathMapping records MUST be created with empty `local_path` for discovered collections.
- **D-6:** On transaction failure, ALL changes MUST be rolled back with no partial creation.
- **D-7:** Source configuration MUST be validated before database persistence.
- **D-8:** Enricher validation MUST occur before source creation.
- **D-9:** Collection discovery MUST NOT occur unless `--discover` is explicitly provided.
- **D-10:** Importer interface compliance MUST be verified before source creation.
- **D-11:** Configuration schema validation MUST be performed using importer's `get_config_schema()` method.
- **D-12:** When `--test-db` is provided, ALL database operations MUST be isolated to a test environment and MUST NOT affect production data.
- **D-13:** Test database isolation MUST be enforced at the transaction level, ensuring no cross-contamination with production systems.

---

## Test Coverage Mapping

- `B-1..B-12` → `test_source_add_contract.py`
- `D-1..D-13` → `test_source_add_data_contract.py`

---

## Error Conditions

### Validation Errors

- Invalid source type: "Unknown source type 'invalid'. Available types: plex, filesystem"
- Missing required parameters: "Error: --base-url is required for Plex sources"
- Invalid configuration: "Error: Path does not exist: /invalid/path"
- Interface violation: "Error: Importer 'plex' does not implement ImporterInterface"
- Configuration schema error: "Error: Invalid configuration schema for importer 'plex'"

### Database Errors

- Duplicate external ID: Transaction rollback, clear error message
- Foreign key violations: Transaction rollback, diagnostic information

---

## Examples

### Plex Source Creation

```bash
# Dry run to validate configuration
retrovue source add --type plex --name "My Plex Server" \
  --base-url "https://plex.example.com" --token "your-token" --dry-run

# Create with enrichers
retrovue source add --type plex --name "My Plex Server" \
  --base-url "https://plex.example.com" --token "your-token" \
  --enrichers "ffprobe,metadata" --json

# Create with collection discovery
retrovue source add --type plex --name "My Plex Server" \
  --base-url "https://plex.example.com" --token "your-token" \
  --discover --json

# Create with both enrichers and discovery
retrovue source add --type plex --name "My Plex Server" \
  --base-url "https://plex.example.com" --token "your-token" \
  --enrichers "ffprobe,metadata" --discover
```

### Filesystem Source Creation

```bash
# Create filesystem source
retrovue source add --type filesystem --name "Media Library" \
  --base-path "/media/movies" --test-db
```

### Test Environment Usage

```bash
# Test source creation in isolated environment
retrovue source add --type plex --name "Test Plex" \
  --base-url "http://test-plex:32400" --token "test-token" \
  --test-db --dry-run

# Test source creation with discovery
retrovue source add --type plex --name "Test Plex" \
  --base-url "http://test-plex:32400" --token "test-token" \
  --test-db --discover --json

# Test filesystem source (discover flag ignored)
retrovue source add --type filesystem --name "Test Media" \
  --base-path "/test/media" --test-db --discover
```

---

## See Also

- [Unit of Work](../_ops/UnitOfWorkContract.md) - Transaction management requirements for atomic operations
- [Source Discover](SourceDiscoverContract.md) - Standalone collection discovery operations
- [Collection Ingest](CollectionIngestContract.md) - Collection-level ingest operations
