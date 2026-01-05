# Source Delete

## Purpose

Define the behavioral contract for deleting content sources from RetroVue. This contract ensures safe, cascade-aware source deletion with proper confirmation and cleanup.

---

## Command Shape

```
retrovue source delete <source_selector> [--force] [--test-db] [--confirm] [--json]
```

### Required Parameters

- `source_selector`: One of:
  - a single source identifier (UUID, external ID, or exact name)
  - a wildcard pattern (e.g. "test-_" or "plex-temp-_"), which may match multiple sources by name or external_id
  - the special token "\*" meaning "all sources"

The command MUST evaluate source_selector to a concrete list of candidate sources before performing any deletion. Each candidate source is then validated and (if eligible) deleted under the normal safety rules.

### Optional Parameters

- `--force`: Skip confirmation prompts
- `--test-db`: Direct command to test database environment
- `--confirm`: Required flag to proceed with deletion
- `--json`: Output result in JSON format

---

## Safety Expectations

### Confirmation Model

**Without `--force`:**

- Interactive confirmation prompt required
- Shows source details and cascade impact
- User must type "yes" to confirm
- Cancellation returns exit code 0

**With `--force`:**

- No confirmation prompts
- Immediate deletion execution
- Use with extreme caution

**Wildcard / multi-delete confirmation behavior:**

When `<source_selector>` resolves to more than one source and `--force` is NOT provided, the confirmation prompt MUST summarize:

- how many sources are targeted,
- how many collections and path mappings would be deleted in total,
- and MUST require typing "yes" to continue.

When `<source_selector>` resolves to more than one source and `--force` IS provided, the command MUST proceed with deletion of all eligible sources without interactive prompts.

In production, any source that fails safety validation (see D-5) MUST be skipped and reported, even under `--force`. The presence of a protected source MUST NOT abort deletion of other safe sources unless the operator cancels.

### Cascade Deletion

Deleting a source removes:

- Source record
- All associated SourceCollection records
- All associated PathMapping records
- Any other related data through foreign key constraints

---

## Output Format

### Human-Readable Output

**Confirmation Prompt:**

```
Are you sure you want to delete source 'My Plex Server' (ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44)?
This will also delete:
  - 3 collections
  - 12 path mappings
This action cannot be undone.
Type 'yes' to confirm:
```

**Success Output:**

```
Successfully deleted source: My Plex Server
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Type: plex
```

### JSON Output

```json
{
  "deleted": true,
  "source_id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "name": "My Plex Server",
  "type": "plex",
  "collections_deleted": 3,
  "path_mappings_deleted": 12
}
```

---

## Exit Codes

- `0`: Source deleted successfully or deletion cancelled
- `1`: Source not found, deletion failed, or validation error

---

## Data Effects

### Database Changes

1. **Cascade Deletion**:

   - Source record deleted
   - All SourceCollection records deleted (foreign key cascade)
   - All PathMapping records deleted (foreign key cascade)

2. **Audit Logging**:
   - Deletion logged with source details
   - Count of related records deleted
   - Timestamp of deletion

### Side Effects

- No external system cleanup required
- No filesystem changes
- Database transaction boundary maintained

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST require interactive confirmation unless `--force` is provided. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-2:** Interactive confirmation MUST require the user to type "yes" exactly to proceed. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-3:** The confirmation prompt MUST show source details and cascade impact count. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-4:** When `--json` is supplied, output MUST include fields `"deleted"`, `"source_id"`, `"name"`, and `"type"`.
- **B-5:** On validation failure (source not found), the command MUST exit with code `1` and print "Error: Source 'X' not found".
- **B-6:** Cancellation of confirmation MUST return exit code `0` with message "Deletion cancelled". Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-7:** The `--force` flag MUST skip all confirmation prompts and proceed immediately. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-8:** The source_selector argument MAY be a wildcard. Wildcard selection MUST resolve to a deterministic list of matching sources before any deletion occurs. If multiple sources are selected and `--force` is not provided, the command MUST present a single aggregated confirmation prompt summarizing impact across all matched sources and require the operator to type "yes". If `--force` is provided, the command MUST skip confirmation and attempt deletion of each matched source. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).

---

## Data Contract Rules (D-#)

- **D-1:** Source deletion MUST cascade delete all associated SourceCollection records.
- **D-2:** Source deletion MUST cascade delete all associated PathMapping records.
- **D-3:** All deletion operations MUST occur within a single transaction boundary.
- **D-4:** On transaction failure, ALL changes MUST be rolled back with no partial deletions.
- **D-5:** **PRODUCTION SAFETY**: A Source MUST NOT be deleted in production if any Asset from that Source has appeared in a PlaylogEvent or AsRunLog. `--force` MUST NOT override this rule. In a wildcard or multi-source delete, this safety rule MUST be applied independently per source. Protected sources MUST be skipped and reported, and unprotected sources MAY still be deleted in the same run. Production is determined by environment configuration (e.g. `env.is_production() == true`). The command MUST evaluate this before performing any destructive action. This command MUST comply with [\_ops/ProductionSafety.md](../_ops/ProductionSafety.md) (PS-1 through PS-4).
- **D-6:** Deletion MUST be logged with source details, collection count, and path mapping count.
- **D-7:** The command MUST verify source existence before attempting deletion.
- **D-8:** For wildcard or multi-source deletion, each source MUST be deleted using the same transactional guarantees defined in D-1..D-4. Partial success is allowed across the set (one source can delete successfully while another is blocked by production safety), but each individual source delete MUST remain atomic.
- **D-9:** Deleting a Source MUST also delete all Collections that belong to that Source. This cascade MUST occur in the same transaction boundary as the Source deletion. If the transaction fails, no partial state is allowed (the Source MUST still exist and all of its Collections MUST still exist).
- **D-10:** Collections are the boundary that will eventually own Assets. Once Asset persistence and Asset metadata tables (technical metadata, enrichments, segment markers, etc.) are finalized, Collection deletion will be responsible for removing: all Assets in that Collection, and all per-Asset metadata rows, in a single transaction. This deeper cascade is not yet enforced and MUST NOT block Source deletion at this stage, but it is considered part of the intended lifecycle model.

---

## Test Coverage Mapping

- `B-1..B-8` → `test_source_delete_contract.py`
- `D-1..D-10` → `test_source_delete_data_contract.py`

---

## Error Conditions

### Validation Errors

- Source not found: "Error: Source 'invalid-source' not found"
- Invalid source ID format: Handled gracefully with clear error message

### Database Errors

- Foreign key constraint violations: Transaction rollback
- Concurrent modification: Transaction rollback with retry suggestion

---

## Examples

### Interactive Deletion

```bash
# Delete with confirmation prompt
retrovue source delete "My Plex Server"

# Delete by external ID
retrovue source delete plex-5063d926

# Delete by UUID
retrovue source delete 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
```

### Force Deletion

```bash
# Skip confirmation prompts
retrovue source delete "My Plex Server" --force

# Force deletion with JSON output
retrovue source delete plex-5063d926 --force --json
```

### Test Environment Usage

```bash
# Test deletion in isolated environment
retrovue source delete "Test Plex Server" --test-db --force

# Test confirmation flow
retrovue source delete "Test Source" --test-db
```

### Wildcard Operations

```bash
# Delete all sources whose name or external_id starts with "test-"
retrovue source delete "test-*" --force --test-db

# Delete all disposable sources in a staging DB (will prompt once to confirm)
retrovue source delete "*" --test-db

# Attempt wildcard delete in production:
# - Safe sources are removed
# - Any source tied to on-air / logged assets is skipped and reported
retrovue source delete "*" --force
```

---

## Safety Guidelines

- Always use `--test-db` for testing deletion logic
- Verify cascade impact before using `--force`
- Use `--dry-run` equivalent by checking source details first
- Confirm source identification before deletion
