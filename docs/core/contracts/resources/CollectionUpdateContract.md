# Collection Update

## Purpose

Define the behavioral contract for updating collection configuration and state. This contract ensures safe, consistent collection updates with proper validation, prerequisite checking, and atomic transaction handling.

---

## Command Shape

```
retrovue collection update <collection_id> [--sync-enable] [--sync-disable] [--add-enricher <enricher_id>] [--delete-enricher <enricher_id>] [--list-enrichers] [--path-mapping <local_path|DELETE>] [--priority <n>] [--test-db] [--dry-run] [--json]
```

### Required Parameters

- `<collection_id>`: Collection identifier (UUID, external ID, or display name)

### Optional Parameters

**Sync Management:**

- `--sync-enable`: Enable sync for the collection (requires `ingestible=true`)
- `--sync-disable`: Disable sync for the collection (requires `sync_enabled=true`)

**Enricher Management:**

- `--add-enricher <enricher_id>`: Attach an enricher to the collection (requires `--priority` when adding)
- `--delete-enricher <enricher_id>`: Remove an enricher from the collection
- `--list-enrichers`: Display all enrichers attached to the collection (read-only operation)
- `--priority <n>`: Priority for enricher execution order (required when using `--add-enricher`, ignored otherwise)

**Path Mapping:**

- `--path-mapping <local_path|DELETE>`: Set the local path for the collection's path mapping, or clear it with `DELETE`. Updating sets `local_path` only (does not change the external path). `DELETE` sets the mapping's `local_path` to null (keeps the external path) and sets `ingestible=false`.
  

**Common Flags:**

- `--test-db`: Direct command to test database environment
- `--dry-run`: Show what would be updated without executing
- `--json`: Output result in JSON format

**Mutual Exclusivity:**

- `--sync-enable` and `--sync-disable` MUST NOT be provided together. If both are provided, the command MUST exit with code 1 and emit: "Error: Cannot specify both --sync-enable and --sync-disable. Use one flag only."
- `--add-enricher` and `--delete-enricher` MAY be provided together in a single command to perform multiple enricher operations atomically.
- `--list-enrichers` MAY be combined with other flags, but when `--list-enrichers` is provided, the command MUST display enricher information even if no other operations are performed.
- At least one operation flag (`--sync-enable`, `--sync-disable`, `--add-enricher`, `--delete-enricher`, `--list-enrichers`, or `--path-mapping`) MUST be provided. If none are provided, the command MUST exit with code 1 and emit: "Error: Must specify at least one operation: --sync-enable, --sync-disable, --add-enricher, --delete-enricher, --list-enrichers, or --path-mapping."

---

## Safety Expectations

### Prerequisite Validation

- **Enable Sync Prerequisite**: `--sync-enable` MAY only be executed if the collection's `ingestible` field is `true`. If `ingestible=false`, the command MUST exit with code 1 and emit: "Error: Cannot enable sync for collection 'X'. Collection is not ingestible. Check path mappings and prerequisites with 'retrovue collection show <id>'."
- **Disable Sync Prerequisite**: `--sync-disable` MAY only be executed if the collection's `sync_enabled` field is `true`. If `sync_enabled=false`, the command MUST exit with code 1 and emit: "Error: Cannot disable sync for collection 'X'. Collection is not currently sync-enabled."
- **Idempotent Operations**: Enabling an already-enabled collection or disabling an already-disabled collection MUST succeed with exit code 0 and MUST be treated as a no-op (no database changes, but operation is considered successful).
- **Enricher Validation**: `--add-enricher` requires that the enricher exists and is available. If the enricher does not exist, the command MUST exit with code 1 and emit: "Error: Enricher '<enricher_id>' not found."
- **Enricher Priority**: When using `--add-enricher`, the `--priority` flag MUST be provided. If `--add-enricher` is specified without `--priority`, the command MUST exit with code 1 and emit: "Error: --priority is required when using --add-enricher."
- **Enricher Duplication**: Adding an enricher that is already attached to the collection MUST be treated as idempotent (no error, but may update priority if different priority is provided).
- **Enricher Removal**: Removing an enricher that is not attached to the collection MUST be treated as idempotent (no error, operation succeeds with no changes).
- **Path Mapping Validation**: `--path-mapping` MUST validate that the provided local path exists and is accessible before updating the PathMapping record. If the path does not exist or is not accessible, the command MUST exit with code 1 and emit: "Error: Local path '<local_path>' does not exist or is not accessible."
- **Ingestible Revalidation**: After updating a path mapping, the collection's `ingestible` status MUST be revalidated by calling the importer's `validate_ingestible()` method. This revalidation determines whether the collection meets all prerequisites for ingestion.
- **Path Mapping Requirement**: A collection MUST have a PathMapping record before `--path-mapping` or `--path-mapping-plex` can be used. If no PathMapping exists for the collection, the command MUST exit with code 1 and emit: "Error: Collection 'X' does not have a path mapping. Path mappings are created during source discovery."

### Update Model

- **Non-destructive operation**: Only updates collection state flags
- **Idempotent**: Safe to run multiple times with same parameters
- **Dry-run support**: Preview updates without database changes
- **Test isolation**: `--test-db` prevents production database modifications

### Validation Requirements

- Collection must exist and be accessible
- Collection identification MUST follow the same resolution rules as `collection show` (UUID, external ID, or case-insensitive name, with ambiguity handling)
- Prerequisite validation MUST occur before any database operations
- State transitions MUST be validated before database updates

### Dry-run Behavior

- In `--dry-run` mode, no database writes MAY occur
- On valid input, exit code MUST be 0 and output MUST match the normal `--json` shape
- On invalid input, exit code MUST be 1 and MUST emit the same human-readable error used in non-dry-run mode
- Dry-run human-readable output includes current and proposed state for validation purposes

### Test Database Behavior

- In `--test-db` mode, ALL database writes MUST be isolated to a non-production test environment
- `--test-db` MUST NOT leak any writes to production databases or persistent storage
- When `--test-db` is combined with `--dry-run`, dry-run behavior takes precedence (no writes occur)
- Behavior, output format, and exit codes MUST remain identical to production mode

---

## Output Format

### Human-Readable Output

**Enable Sync Success:**

```
Successfully enabled sync for collection "TV Shows"
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Sync Enabled: true
  Ingestible: true
  Updated: 2024-01-15 10:30:00
```

**Disable Sync Success:**

```
Successfully disabled sync for collection "TV Shows"
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Sync Enabled: false
  Ingestible: true
  Updated: 2024-01-15 10:30:00
```

**Idempotent Operation (Already Enabled):**

```
Collection "TV Shows" is already sync-enabled
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Sync Enabled: true
  No changes were made.
```

**Add Enricher Success:**

```
Successfully added enricher to collection "TV Shows"
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Enricher: enricher-ffprobe-a1b2c3d4 (ffprobe)
  Priority: 1
  Updated: 2024-01-15 10:30:00
```

**Delete Enricher Success:**

```
Successfully removed enricher from collection "TV Shows"
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Enricher: enricher-ffprobe-a1b2c3d4
  Updated: 2024-01-15 10:30:00
```

**List Enrichers Output:**

```
Collection "TV Shows" Enrichers:
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Enrichers:
    1. enricher-ffprobe-a1b2c3d4 (ffprobe) - Priority: 1
    2. enricher-metadata-b2c3d4e5 (metadata) - Priority: 2
```

**Set Path Mapping Success:**

```
Successfully updated path mapping for collection "TV Shows"
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  External Path: /library/sections/1
  Local Path: /media/tv-shows
  Ingestible: true
  Updated: 2024-01-15 10:30:00
```

**Dry-run Output:**

```
[DRY RUN] Would enable sync for collection "TV Shows"
  Current State: sync_enabled=false, ingestible=true
  Proposed State: sync_enabled=true, ingestible=true
  No changes were applied.
```

### JSON Output

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926-1",
  "name": "TV Shows",
  "sync_enabled": true,
  "ingestible": true,
  "updated": true,
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Apply Enrichers JSON Output:**

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926-1",
  "name": "TV Shows",
  "operation": "apply-enrichers",
  "enrichment": {
    "pipeline_checksum": "<hex>",
    "stats": {
      "assets_considered": 120,
      "assets_enriched": 118,
      "assets_auto_ready": 110,
      "errors": []
    }
  },
  "updated": true,
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Idempotent Operation (Already in Target State):**

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926-1",
  "name": "TV Shows",
  "sync_enabled": true,
  "ingestible": true,
  "updated": false,
  "message": "Collection is already sync-enabled. No changes were made."
}
```

**Add Enricher JSON Output:**

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926-1",
  "name": "TV Shows",
  "operation": "add-enricher",
  "enricher_id": "enricher-ffprobe-a1b2c3d4",
  "enricher_type": "ffprobe",
  "priority": 1,
  "updated": true,
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**List Enrichers JSON Output:**
**Auto-Enrichment on Update (implicit):**

When enrichers are attached to the collection, `collection update` automatically applies the
ingest-scope pipeline to existing assets that need enrichment (state='new' or outdated/missing
`last_enricher_checksum`). The JSON output includes an `enrichment` object summarizing the run:

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926-1",
  "name": "TV Shows",
  "operation": "update",
  "enrichment": {
    "pipeline_checksum": "<hex>",
    "stats": {
      "assets_considered": 120,
      "assets_enriched": 118,
      "assets_auto_ready": 110,
      "errors": []
    }
  },
  "updated": true,
  "updated_at": "2024-01-15T10:30:00Z"
}
```

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926-1",
  "name": "TV Shows",
  "operation": "list-enrichers",
  "enrichers": [
    {
      "enricher_id": "enricher-ffprobe-a1b2c3d4",
      "enricher_type": "ffprobe",
      "name": "Video Analysis",
      "priority": 1
    },
    {
      "enricher_id": "enricher-metadata-b2c3d4e5",
      "enricher_type": "metadata",
      "name": "Metadata Enrichment",
      "priority": 2
    }
  ]
}
```

**Set Path Mapping JSON Output:**

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926-1",
  "name": "TV Shows",
  "operation": "path-mapping",
  "path_mapping": {
    "external_path": "/library/sections/1",
    "local_path": "/media/tv-shows"
  },
  "ingestible": true,
  "updated": true,
  "updated_at": "2024-01-15T10:30:00Z"
}
```

---

## Exit Codes

- `0`: Collection updated successfully, enrichers listed successfully, path mapping updated successfully, or operation was idempotent (no changes needed)
- `1`: Validation error, collection not found, enricher not found, path mapping validation failed, prerequisite not met, or invalid flag combination

---

## Data Effects

### Database Changes

1. **Enable Sync** (`--sync-enable`):

   - Collection's `sync_enabled` field set to `true`
   - Updated timestamp refreshed
   - No other fields modified

2. **Disable Sync** (`--disable-sync`):

   - Collection's `sync_enabled` field set to `false`
   - Updated timestamp refreshed
   - No other fields modified

3. **Add Enricher** (`--add-enricher`):

   - CollectionEnricher relationship record created or updated
   - Enricher priority set according to `--priority` flag
   - Updated timestamp refreshed
   - Enricher must exist and be available

4. **Delete Enricher** (`--delete-enricher`):

   - CollectionEnricher relationship record removed
   - Updated timestamp refreshed
   - Idempotent if enricher was not attached

5. **List Enrichers** (`--list-enrichers`):

   - No database modifications (read-only operation)
   - Displays all enrichers attached to the collection
   - Ordered by priority

6. **Set Path Mapping** (`--path-mapping`):
   - PathMapping record's `local_path` field updated
   - Path validation performed (path must exist and be accessible)
   - Collection's `ingestible` status revalidated via importer's `validate_ingestible()` method
   - Updated timestamp refreshed

### Side Effects

- Collection state change affects eligibility for `source ingest` operations
- Updated timestamp reflects state change time
- Enricher attachments affect enrichment pipeline execution during ingest
- Path mapping updates trigger `ingestible` revalidation, which may change the collection's eligibility for ingest operations
- Applying enrichers (`--apply-enrichers`) updates existing assets in-place and may auto-promote
  eligible assets to `state=ready` with `approved_for_broadcast=true` when confidence ≥ threshold.
- Path mapping changes may affect the importer's ability to resolve content locations

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST accept `<collection_id>` as any of: full UUID, external ID (e.g. Plex library key), or case-insensitive display name. Collection name matching MUST be case-insensitive. If multiple collections match the provided name (case-insensitive), the command MUST exit with code 1 and emit: "Multiple collections named '<name>' exist. Please specify the UUID." Resolution MUST NOT prefer one collection over another, even if one has exact casing match.
- **B-2:** If no collection matches the provided identifier, the command MUST exit with code 1 and emit: "Error: Collection 'X' not found."
- **B-3:** If no operation flags are provided, the command MUST still apply attached ingest-scope enrichers to existing assets needing enrichment and report enrichment stats. If no enrichers are attached, the command MAY be a no-op.
 - **B-20:** When `--apply-enrichers` is provided, the command MUST apply the attached ingest-scope enrichers to assets needing enrichment (state='new' or outdated checksum) and include enrichment stats in JSON output.
- **B-4:** If both `--sync-enable` and `--sync-disable` are provided, the command MUST exit with code 1 and emit: "Error: Cannot specify both --sync-enable and --sync-disable. Use one flag only."
- **B-5:** For `--sync-enable`, if `ingestible=false`, the command MUST exit with code 1 and emit: "Error: Cannot enable sync for collection 'X'. Collection is not ingestible. Check path mappings and prerequisites with 'retrovue collection show <id>'."
- **B-6:** For `--sync-disable`, if `sync_enabled=false`, the command MUST exit with code 1 and emit: "Error: Cannot disable sync for collection 'X'. Collection is not currently sync-enabled."
- **B-7:** If `--enable-sync` is provided for a collection that is already `sync_enabled=true`, the command MUST succeed with exit code 0, MUST NOT modify the database, and MUST indicate that the collection is already enabled.
- **B-8:** If `--disable-sync` is provided for a collection that is already `sync_enabled=false`, the command MUST succeed with exit code 0, MUST NOT modify the database, and MUST indicate that the collection is already disabled.
- **B-9:** When `--add-enricher` is provided, the `--priority` flag MUST also be provided. If `--add-enricher` is specified without `--priority`, the command MUST exit with code 1 and emit: "Error: --priority is required when using --add-enricher."
- **B-10:** When `--add-enricher` is provided, the enricher MUST exist and be available. If the enricher does not exist, the command MUST exit with code 1 and emit: "Error: Enricher '<enricher_id>' not found."
- **B-11:** If `--add-enricher` is provided for an enricher already attached to the collection, the operation MUST succeed (idempotent) and MAY update the priority if a different priority is provided.
- **B-12:** If `--delete-enricher` is provided for an enricher not attached to the collection, the operation MUST succeed (idempotent) with no database changes.
- **B-13:** When `--list-enrichers` is provided, the output MUST display all enrichers attached to the collection, ordered by priority, even if no other operations are performed.
- **B-14:** When `--path-mapping` is provided, the collection MUST have an existing PathMapping record. If no PathMapping exists, the command MUST exit with code 1 and emit: "Error: Collection 'X' does not have a path mapping. Path mappings are created during source discovery."
- **B-15:** When `--path-mapping` is provided, the local path MUST exist and be accessible before updating the PathMapping record. If the path does not exist or is not accessible, the command MUST exit with code 1 and emit: "Error: Local path '<local_path>' does not exist or is not accessible."
- **B-16:** After successfully updating a path mapping, the collection's `ingestible` status MUST be revalidated by calling the importer's `validate_ingestible()` method. The output MUST reflect the updated `ingestible` status.
- **B-17:** When `--json` is supplied, output MUST include fields: `"id"`, `"external_id"`, `"name"`, `"operation"` (indicating which operation was performed), `"sync_enabled"`, `"ingestible"`, `"updated"` (boolean indicating if database was modified), `"updated_at"`, and optionally `"message"` for idempotent operations. For enricher operations, include `"enricher_id"`, `"enricher_type"`, and `"priority"`. For `--list-enrichers`, include `"enrichers"` array. For `--path-mapping`, include `"path_mapping"` object with `"external_path"` and `"local_path"`.
- **B-18:** The `--dry-run` flag MUST show current and proposed state without executing. In dry-run mode, no database writes MAY occur. On valid input, exit code MUST be 0 and output MUST match the normal `--json` shape.
- **B-19:** When run with `--test-db`, no changes may affect production or staging databases.

---

## Data Contract Rules (D-#)

- **D-1:** Collection update operations MUST occur within a single transaction boundary, following Unit of Work principles.
- **D-2:** Prerequisite validation (`ingestible=true` for enable, `sync_enabled=true` for disable) MUST occur before any database operations begin.
- **D-3:** If prerequisite validation fails, the transaction MUST NOT be opened and no database modifications MAY occur.
- **D-4:** For `--enable-sync`, the collection's `sync_enabled` field MUST be set to `true` only if `ingestible=true`. If `ingestible=false`, the operation MUST NOT proceed.
- **D-5:** For `--disable-sync`, the collection's `sync_enabled` field MUST be set to `false` only if `sync_enabled=true` currently. If `sync_enabled=false` already, the operation MUST be treated as idempotent (no database changes).
- **D-6:** Updated timestamp (`updated_at`) MUST be refreshed whenever a state change is successfully persisted to the database.
- **D-7:** Idempotent operations (enabling already-enabled, disabling already-disabled) MUST NOT modify the database but MUST still be considered successful operations.
- **D-8:** Collection identification MUST use the same resolution logic as `collection show` (UUID, external ID, or case-insensitive name lookup).
- **D-9:** If multiple collections match the provided name (case-insensitive), the query MUST return all matching collections for ambiguity detection before any updates occur. Resolution MUST NOT prefer one collection over another based on casing match.
- **D-10:** All operations run with `--test-db` MUST be isolated from production database storage, tables, and triggers.
- **D-11:** For `--add-enricher`, the enricher MUST exist and be available before creating the relationship. If the enricher does not exist, the operation MUST NOT proceed.
- **D-12:** CollectionEnricher relationship records MUST include priority ordering for execution sequence.
- **D-13:** When `--add-enricher` and `--delete-enricher` are provided together, all enricher operations MUST occur atomically within the same transaction.
- **D-14:** `--list-enrichers` is a read-only operation and MUST NOT modify any database state.
- **D-15:** For `--path-mapping`, the PathMapping record MUST exist before the local_path can be updated. If no PathMapping exists, the operation MUST NOT proceed.
- **D-16:** Path validation MUST occur before updating the PathMapping record. The local path MUST exist and be accessible at the time of update.
- **D-17:** After updating a path mapping, the collection's `ingestible` status MUST be revalidated by calling the importer's `validate_ingestible()` method, and the collection's `ingestible` field MUST be updated to reflect the validation result.
- **D-18:** Path mapping updates and `ingestible` revalidation MUST occur within the same transaction boundary, ensuring atomicity.
- **D-19:** On transaction failure, ALL changes MUST be rolled back with no partial state updates.
 - **D-20:** The enrichment helper MUST NOT commit; the CLI command commits after successful application.

---

## Test Coverage Mapping

- `B-1..B-19` → `test_collection_update_contract.py`
- `D-1..D-19` → `test_collection_update_data_contract.py`

Each rule above MUST have explicit test coverage in its respective test file, following the contract test responsibilities in [README.md](./README.md).  
Each test file MUST reference these rule IDs in docstrings or comments to provide bidirectional traceability.

Future related tests (integration or scenario-level) MAY reference these same rule IDs for coverage mapping but must not redefine behavior.

---

## Error Conditions

### Validation Errors

- Collection not found: "Error: Collection 'invalid-name' not found."
- Ambiguous name: "Multiple collections named 'Movies' exist. Please specify the UUID."
- No operation specified: "Error: Must specify at least one operation: --enable-sync, --disable-sync, --add-enricher, --delete-enricher, --list-enrichers, or --path-mapping."
- Conflicting flags: "Error: Cannot specify both --enable-sync and --disable-sync. Use one flag only."
- Enable prerequisite not met: "Error: Cannot enable sync for collection 'TV Shows'. Collection is not ingestible. Check path mappings and prerequisites with 'retrovue collection show <id>'."
- Disable prerequisite not met: "Error: Cannot disable sync for collection 'TV Shows'. Collection is not currently sync-enabled."
- Enricher not found: "Error: Enricher 'enricher-ffprobe-999' not found."
- Priority required: "Error: --priority is required when using --add-enricher."
- Path mapping missing: "Error: Collection 'TV Shows' does not have a path mapping. Path mappings are created during source discovery."
- Path invalid: "Error: Local path '/invalid/path' does not exist or is not accessible."

---

## Examples

### Enable Sync

```bash
# Enable sync for a collection
retrovue collection update "TV Shows" --sync-enable

# Enable sync with JSON output
retrovue collection update "TV Shows" --sync-enable --json

# Enable sync by UUID
retrovue collection update 4b2b05e7-d7d2-414a-a587-3f5df9b53f44 --sync-enable

# Dry-run enable sync
retrovue collection update "TV Shows" --sync-enable --dry-run
```

### Disable Sync

```bash
# Disable sync for a collection
retrovue collection update "TV Shows" --sync-disable

# Disable sync with JSON output
retrovue collection update "TV Shows" --sync-disable --json

# Disable sync by external ID
retrovue collection update plex-5063d926-1 --sync-disable
```

### Error Cases

```bash
# Invalid: Collection not found
retrovue collection update "Non-existent" --sync-enable
# Error: Collection 'Non-existent' not found.

# Invalid: Ambiguous name
retrovue collection update "Movies" --sync-enable
# Error: Multiple collections named 'Movies' exist. Please specify the UUID.

# Invalid: No operation specified
retrovue collection update "TV Shows"
# Error: Must specify at least one operation: --sync-enable, --sync-disable, --add-enricher, --delete-enricher, --list-enrichers, or --path-mapping.

# Invalid: Conflicting flags
retrovue collection update "TV Shows" --sync-enable --sync-disable
# Error: Cannot specify both --sync-enable and --sync-disable. Use one flag only.

# Invalid: Enable sync when not ingestible
retrovue collection update "TV Shows" --sync-enable
# Error: Cannot enable sync for collection 'TV Shows'. Collection is not ingestible. Check path mappings and prerequisites with 'retrovue collection show <id>'.

# Invalid: Disable sync when not enabled
retrovue collection update "TV Shows" --sync-disable
# Error: Cannot disable sync for collection 'TV Shows'. Collection is not currently sync-enabled.

# Valid: Idempotent operation (already enabled)
retrovue collection update "TV Shows" --sync-enable
# Success: Collection "TV Shows" is already sync-enabled. No changes were made.
```

### Enricher Management

```bash
# Add enricher to collection
retrovue collection update "TV Shows" --add-enricher enricher-ffprobe-a1b2c3d4 --priority 1

# Add enricher with JSON output
retrovue collection update "TV Shows" --add-enricher enricher-metadata-b2c3d4e5 --priority 2 --json

# Delete enricher from collection
retrovue collection update "TV Shows" --delete-enricher enricher-ffprobe-a1b2c3d4

# List enrichers attached to collection
retrovue collection update "TV Shows" --list-enrichers

# List enrichers with JSON output
retrovue collection update "TV Shows" --list-enrichers --json

# Multiple operations in one command
retrovue collection update "TV Shows" --add-enricher enricher-ffprobe-a1b2c3d4 --priority 1 --delete-enricher enricher-metadata-b2c3d4e5
```

### Error Cases for Enrichers

```bash
# Invalid: Priority missing
retrovue collection update "TV Shows" --add-enricher enricher-ffprobe-a1b2c3d4
# Error: --priority is required when using --add-enricher.

# Invalid: Enricher not found
retrovue collection update "TV Shows" --add-enricher enricher-invalid-999 --priority 1
# Error: Enricher 'enricher-invalid-999' not found.

# Valid: Idempotent add (already attached)
retrovue collection update "TV Shows" --add-enricher enricher-ffprobe-a1b2c3d4 --priority 1
# Success: Enricher already attached. Priority updated if different.

# Valid: Idempotent delete (not attached)
retrovue collection update "TV Shows" --delete-enricher enricher-ffprobe-a1b2c3d4
# Success: Enricher was not attached. No changes were made.
```

### Path Mapping Management

```bash
# Set local path mapping for a collection (does not modify external path)
retrovue collection update "TV Shows" --path-mapping /media/tv-shows

# Set path mapping with JSON output
retrovue collection update "TV Shows" --path-mapping /media/tv-shows --json

# Set path mapping by UUID
retrovue collection update 4b2b05e7-d7d2-414a-a587-3f5df9b53f44 --path-mapping /media/tv-shows

# Delete the mapping (collection becomes non-ingestible)
retrovue collection update "TV Shows" --path-mapping DELETE
```

### Error Cases for Path Mapping

```bash
# Invalid: Path mapping does not exist
retrovue collection update "TV Shows" --path-mapping /media/tv-shows
# Error: Collection 'TV Shows' does not have a path mapping. Path mappings are created during source discovery.

# Invalid: Local path does not exist
retrovue collection update "TV Shows" --path-mapping /invalid/path
# Error: Local path '/invalid/path' does not exist or is not accessible.

# Valid: Path mapping update triggers ingestible revalidation
retrovue collection update "TV Shows" --path-mapping /media/tv-shows
# Success: Path mapping updated. Collection is now ingestible.
```

### Test Environment Usage

```bash
# Test enable sync in isolated environment
retrovue collection update "Test Collection" --enable-sync --test-db

# Test disable sync with dry-run
retrovue collection update "Test Collection" --disable-sync --test-db --dry-run

# Test add enricher in isolated environment
retrovue collection update "Test Collection" --add-enricher enricher-ffprobe-test --priority 1 --test-db

# Test list enrichers with dry-run
retrovue collection update "Test Collection" --list-enrichers --test-db --dry-run

# Test path mapping update in isolated environment
retrovue collection update "Test Collection" --path-mapping /test/media --test-db

# Test path mapping update with dry-run
retrovue collection update "Test Collection" --path-mapping /test/media --test-db --dry-run
```

---

## Relationship to Collection Ingest

The `collection update` command controls collection eligibility for `collection ingest` and `source ingest`:

- **Prerequisite Management**: Operators use `collection update --enable-sync` to make collections eligible for bulk ingest operations
- **Ingest Prerequisites**: `collection ingest` requires both `sync_enabled=true` AND `ingestible=true` for full collection ingest
- **Source Ingest Filtering**: `source ingest` automatically filters to collections meeting both prerequisites
- **Surgical Operations**: Even when `sync_enabled=false`, operators can still perform targeted ingest operations (`--title`/`--season`/`--episode`)

---

## See Also

- [Collection Ingest](CollectionIngestContract.md) - Ingest operations that depend on sync_enabled and ingestible status
- [Collection Show](CollectionShowContract.md) - Displaying collection information including sync_enabled and ingestible status
- [Collection Contract](CollectionContract.md) - Overview of all collection operations
- [Source Ingest](SourceIngestContract.md) - Source-level orchestration that filters by sync_enabled and ingestible
