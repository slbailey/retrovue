# Enricher Remove

## Purpose

Define the behavioral contract for removing enricher instances from RetroVue. This contract ensures safe, cascade-aware enricher removal with proper confirmation and cleanup.

---

## Command Shape

```
retrovue enricher remove <enricher_id> [--force] [--test-db] [--confirm] [--json]
```

### Required Parameters

- `enricher_id`: Enricher instance identifier (UUID or enricher ID)

### Optional Parameters

- `--force`: Skip confirmation prompts
- `--test-db`: Direct command to test database environment
- `--confirm`: Required flag to proceed with removal
- `--json`: Output result in JSON format

---

## Safety Expectations

### Confirmation Model

**Without `--force`:**

- Interactive confirmation prompt required
- Shows enricher details and cascade impact
- User must type "yes" to confirm
- Cancellation returns exit code 0

**With `--force`:**

- No confirmation prompts
- Immediate removal execution
- Use with extreme caution

### Cascade Removal

Removing an enricher instance removes:

- Enricher instance record
- All associated attachment records (collections/channels)
- Any other related data through foreign key constraints

---

## Output Format

### Human-Readable Output

**Confirmation Prompt:**

```
Are you sure you want to remove enricher 'Video Analysis' (ID: enricher-ffprobe-a1b2c3d4)?
This will also remove:
  - 2 collection attachments
  - 0 channel attachments
This action cannot be undone.
Type 'yes' to confirm:
```

**Success Output:**

```
Successfully removed enricher: Video Analysis
  ID: enricher-ffprobe-a1b2c3d4
  Type: ffprobe
```

### JSON Output

```json
{
  "removed": true,
  "enricher_id": "enricher-ffprobe-a1b2c3d4",
  "name": "Video Analysis",
  "type": "ffprobe",
  "collection_attachments_removed": 2,
  "channel_attachments_removed": 0
}
```

---

## Exit Codes

- `0`: Enricher removed successfully or removal cancelled
- `1`: Enricher not found, removal failed, or validation error

---

## Data Effects

### Database Changes

1. **Cascade Removal**:

   - Enricher instance record deleted
   - All collection attachment records deleted (foreign key cascade)
   - All channel attachment records deleted (foreign key cascade)

2. **Audit Logging**:
   - Removal logged with enricher details
   - Count of related records deleted
   - Timestamp of removal

### Side Effects

- No external system cleanup required
- No filesystem changes
- Database transaction boundary maintained

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST require interactive confirmation unless `--force` is provided. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-2:** Interactive confirmation MUST require the user to type "yes" exactly to proceed. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-3:** The confirmation prompt MUST show enricher details and cascade impact count. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-4:** When `--json` is supplied, output MUST include fields `"removed"`, `"enricher_id"`, `"name"`, and `"type"`.
- **B-5:** On validation failure (enricher not found), the command MUST exit with code `1` and print "Error: Enricher 'X' not found".
- **B-6:** Cancellation of confirmation MUST return exit code `0` with message "Removal cancelled". Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).
- **B-7:** The `--force` flag MUST skip all confirmation prompts and proceed immediately. Interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).

---

## Data Contract Rules (D-#)

- **D-1:** Enricher removal MUST cascade delete all associated collection attachment records.
- **D-2:** Enricher removal MUST cascade delete all associated channel attachment records.
- **D-3:** All removal operations MUST occur within a single transaction boundary.
- **D-4:** On transaction failure, ALL changes MUST be rolled back with no partial deletions.
- **D-5:** **PRODUCTION SAFETY**: This command MUST comply with [\_ops/ProductionSafety.md](../_ops/ProductionSafety.md) (PS-1 through PS-4). An enricher MUST be considered unsafe to remove in production if removal would cause harm to running or future operations. Harm is defined as: (1) it is actively in use by a running ingest or playout process, OR (2) it is marked `protected_from_removal = true`. `--force` MUST NOT override this safeguard. **Production is determined by environment configuration (e.g. `env.is_production() == true`). This check MUST be enforced by the removal command before performing any destructive action.**
- **D-6:** Removal MUST be logged with enricher details, collection count, and channel count.
- **D-7:** The command MUST verify enricher existence before attempting removal.

---

## Test Coverage Mapping

- `B-1..B-7` → `test_enricher_remove_contract.py`
- `D-1..D-7` → `test_enricher_remove_data_contract.py`

---

## Error Conditions

### Validation Errors

- Enricher not found: "Error: Enricher 'enricher-ffprobe-a1b2c3d4' not found"
- Invalid enricher ID format: Handled gracefully with clear error message

### Database Errors

- Foreign key constraint violations: Transaction rollback
- Concurrent modification: Transaction rollback with retry suggestion

---

## Examples

### Interactive Removal

```bash
# Remove with confirmation prompt
retrovue enricher remove enricher-ffprobe-a1b2c3d4

# Remove by enricher ID
retrovue enricher remove enricher-metadata-b2c3d4e5

# Remove by UUID
retrovue enricher remove 550e8400-e29b-41d4-a716-446655440000
```

### Force Removal

```bash
# Skip confirmation prompts
retrovue enricher remove enricher-ffprobe-a1b2c3d4 --force

# Force removal with JSON output
retrovue enricher remove enricher-metadata-b2c3d4e5 --force --json
```

### Test Environment Usage

```bash
# Test removal in isolated environment
retrovue enricher remove enricher-ffprobe-a1b2c3d4 --test-db --force

# Test confirmation flow
retrovue enricher remove enricher-metadata-b2c3d4e5 --test-db
```

---

## Global Contract Compliance

### Confirmation Flow

If the enricher is eligible for removal, interactive confirmation MUST follow [\_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) (C-1 through C-14).

### Production Safety

This command MUST comply with [\_ops/ProductionSafety.md](../_ops/ProductionSafety.md) (PS-1 through PS-4). An enricher MUST be considered unsafe to remove in production if removal would cause harm to running or future operations. Harm is defined as:

- it is actively in use by a running ingest or playout process, OR
- it is marked `protected_from_removal = true`

`--force` MUST NOT override this safeguard.

---

## Safety Guidelines

- Always use `--test-db` for testing removal logic in non-production environments
- Verify cascade impact before using `--force` in non-production environments
- Use `--dry-run` equivalent by checking enricher details first
- Confirm enricher identification before removal
- **Production Safety**: Enrichers marked as `protected_from_removal = true` cannot be removed in production environments, even with `--force`
- **Harm Prevention**: The system prevents removal of enrichers that would break active operations or violate operational expectations
- **Environment Detection**: Production vs non-production is determined by environment configuration, not by analyzing enricher usage patterns or channel configurations

---

## See Also

- [Enricher List Types](EnricherListTypesContract.md) - List available enricher types
- [Enricher Add](EnricherAddContract.md) - Create enricher instances
- [Enricher List](EnricherListContract.md) - List configured enricher instances
- [Enricher Update](EnricherUpdateContract.md) - Update enricher configurations
