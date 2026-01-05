# Source Discover

## Purpose

Define the behavioral contract for discovering collections from content sources. This contract ensures safe collection discovery with proper validation, persistence handling, and importer interface compliance verification.

---

## Command Shape

```
retrovue source discover <source_id> [--json] [--test-db] [--dry-run]
```

### Required Parameters

- `source_id`: Source identifier (UUID, external ID, or name)

### Optional Parameters

- `--json`: Output result in JSON format
- `--test-db`: Direct command to test database environment
- `--dry-run`: Show what would be discovered without persisting

---

## Safety Expectations

### Discovery Model

- **Non-destructive operation**: Only discovers and persists collections
- **Idempotent**: Safe to run multiple times
- **Dry-run support**: Preview discovery without database changes
- **Test isolation**: `--test-db` prevents external API calls

### Collection Handling

- Newly discovered collections start with `enabled=False`
- Existing collections are updated with current metadata
- Duplicate collections are skipped with notification
- No PathMapping records are created during discovery. The external path (e.g., plex path) is persisted in the collection's config for display purposes. PathMapping rows are only created via `retrovue collection update --path-mapping` and removed via `--path-mapping DELETE`.
- Importer must be interface compliant (ImporterInterface). Implementations that subclass BaseImporter are considered compliant by construction. Non-compliant importers MUST cause the command to fail with exit code 1.
- Collection discovery uses importer's discovery capability to enumerate collections

---

## Output Format

### Human-Readable Output

**Discovery Results:**

```
Successfully added 3 collections from 'My Plex Server':
  • Movies (ID: 1) - Disabled by default
  • TV Shows (ID: 2) - Disabled by default
  • Music (ID: 3) - Disabled by default

Use 'retrovue collection update <name> --sync-enable' to enable collections for sync
```

**Dry-run Output:**

```
Would discover 3 collections from 'My Plex Server':
  • Movies (ID: 1) - Would be created
  • TV Shows (ID: 2) - Would be created
  • Music (ID: 3) - Would be created
```

**Dry-run Output with Existing Collections:**

```
Discovered collections from 'My Plex Server' (dry-run):
  • Movies (ID: 1) - Would skip (already exists)
  • TV Shows (ID: 2) - Would skip (already exists)
  • New Collection (ID: 10) - Would be created
```

### JSON Output

```json
{
  "source": {
    "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
    "name": "My Plex Server",
    "type": "plex"
  },
  "collections_added": 3,
  "collections": [
    {
      "external_id": "1",
      "name": "Movies",
      "sync_enabled": false,
      "ingestible": false,
      "source_type": "plex"
    },
    {
      "external_id": "2",
      "name": "TV Shows",
      "sync_enabled": false,
      "ingestible": false,
      "source_type": "plex"
    },
    {
      "external_id": "3",
      "name": "Music",
      "sync_enabled": false,
      "ingestible": false,
      "source_type": "plex"
    }
  ]
}
```

---

## Exit Codes

- `0`: Discovery completed successfully
- `1`: Source not found, discovery failed, or validation error

---

## Data Effects

### Database Changes

1. **Collection Persistence**:

   - New SourceCollection records created
   - Existing collections updated with current metadata
   - All collections start with `enabled=False`

2. **Path Mapping Creation**:
   - PathMapping records created for each collection
   - `plex_path` populated from external system
   - `local_path` left empty for operator configuration

### Side Effects

- External API calls to source system (unless `--test-db`)
- Database transaction for collection persistence
- Logging of discovery results and errors

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST validate source existence before attempting discovery.
- **B-2:** The `--dry-run` flag MUST show what would be discovered without persisting to database.
- **B-3:** When `--json` is supplied, output MUST include fields `"source"`, `"collections_added"`, and `"collections"`.
- **B-4:** On validation failure (source not found), the command MUST exit with code `1` and print "Error: Source 'X' not found".
- **B-5:** Empty discovery results MUST return exit code `0` with message "No collections found for source 'X'".
- **B-6:** Duplicate collections MUST be skipped with notification message.
- **B-7:** For any source type whose importer does not expose a discovery capability, the command MUST succeed with exit code 0, MUST NOT modify the database, and MUST clearly report that no collections are discoverable for that source type.
- **B-8:** The command MUST obtain the importer for the Source's type.
- **B-9:** The importer MUST expose a discovery capability that returns all collections (libraries, sections, folders, etc.) visible to that Source.
- **B-10:** If the importer claims to support discovery but fails interface compliance (missing required discovery capability, raises interface violation), the command MUST exit with code 1 and emit a human-readable error.

---

## Data Contract Rules (D-#)

- **D-1:** Collection discovery MUST occur within a single transaction boundary.
- **D-2:** Newly discovered collections MUST be persisted with `sync_enabled=False`.
- **D-3:** Discovery MUST NOT flip existing collections from `sync_enabled=False` to `sync_enabled=True`.
- **D-4:** Discovery MUST NOT create PathMapping records. External paths are stored in collection configuration metadata to enable human display. PathMapping records are created only via `collection update --path-mapping` and removed via `--path-mapping DELETE`.
- **D-5:** On transaction failure, ALL changes MUST be rolled back with no partial persistence.
- **D-6:** Duplicate external ID checking MUST prevent duplicate collection creation.
- **D-7:** Collection metadata MUST be updated for existing collections.
- **D-8:** Collection discovery MUST use the importer-provided discovery capability to enumerate collections.
- **D-9:** Interface compliance MUST be verified before discovery begins.

---

## Test Coverage Mapping

- `B-1..B-10` → `test_source_discover_contract.py`
- `D-1..D-9` → `test_source_discover_data_contract.py`

---

## Error Conditions

### Validation Errors

- Source not found: "Error: Source 'invalid-source' not found"
- Unsupported source type: "Error: Source type 'filesystem' not supported for discovery"
- Missing configuration: "Error: Plex source 'My Plex' missing base_url or token"
- Interface violation: "Error: Source's importer does not implement ImporterInterface"
- Discovery capability failure: "Error: Importer claims to support discovery but failed interface compliance"

### Discovery Errors

- Connection failure: Graceful error handling, no collections discovered
- API errors: Clear error messages with diagnostic information
- Empty results: "No collections found for source 'My Plex Server'"

### Database Errors

- Transaction rollback on any persistence failure
- Foreign key constraint violations handled gracefully
- Duplicate external ID prevention

---

## Examples

### Basic Discovery

```bash
# Discover collections from Plex source
retrovue source discover "My Plex Server"

# Discover by external ID
retrovue source discover plex-5063d926

# Discover with JSON output
retrovue source discover "My Plex Server" --json
```

### Dry-run Testing

```bash
# Preview discovery without changes
retrovue source discover "My Plex Server" --dry-run

# Test discovery logic
retrovue source discover "Test Plex" --test-db --dry-run
```

### Test Environment Usage

```bash
# Test discovery in isolated environment
retrovue source discover "Test Plex Server" --test-db

# Test with mock data
retrovue source discover "Test Source" --test-db --json
```

---

## Supported Source Types

- **Plex**: Full collection discovery from Plex Media Server
- **Filesystem**: Not supported (collections are directory-based)

---

## Safety Guidelines

- Always use `--test-db` for testing discovery logic
- Use `--dry-run` to preview discovery results
- Verify source configuration before discovery
- Check collection counts after discovery
