# Enricher List

## Purpose

Define the behavioral contract for listing all configured enricher instances. This contract ensures consistent display of enricher instances with their configuration and attachment status.

---

## Command Shape

```
retrovue enricher list [--json] [--test-db] [--dry-run]
```

### Optional Parameters

- `--json`: Output result in JSON format
- `--test-db`: Direct command to test database environment
- `--dry-run`: Show what would be listed without executing

---

## Safety Expectations

### Listing Model

- **Non-destructive operation**: Only displays enricher instances
- **Idempotent**: Safe to run multiple times
- **Dry-run support**: Preview listing without external effects
- **Test isolation**: `--test-db` prevents external system calls

### Display Behavior

- Shows all configured enricher instances
- Displays enricher type and configuration
- Reports attachment status to collections/channels
- Shows availability status

---

## Output Format

### Human-Readable Output

**Listing Results:**

```
Configured enricher instances:
  enricher-ffprobe-a1b2c3d4    - Video Analysis (ffprobe)
    Configuration: {"ffprobe_path": "ffprobe", "timeout": 30}
    Attached to: 2 collections, 0 channels
    Status: Available

  enricher-metadata-b2c3d4e5  - Movie Metadata (metadata)
    Configuration: {"sources": "imdb,tmdb", "api_key": "***REDACTED***"}
    Attached to: 1 collection, 0 channels
    Status: Available

  enricher-playout-c3d4e5f6   - Channel Branding (playout)
    Configuration: {"overlay_path": "/path/to/overlay.png"}
    Attached to: 0 collections, 1 channel
    Status: Available

Total: 3 enricher instances configured
```

**Dry-run Output:**

```
Would list 3 enricher instances from database:
  • enricher-ffprobe-a1b2c3d4 - Video Analysis (ffprobe)
  • enricher-metadata-b2c3d4e5 - Movie Metadata (metadata)
  • enricher-playout-c3d4e5f6 - Channel Branding (playout)
```

### JSON Output

```json
{
  "status": "ok",
  "enrichers": [
    {
      "enricher_id": "enricher-ffprobe-a1b2c3d4",
      "type": "ffprobe",
      "name": "Video Analysis",
      "config": {
        "ffprobe_path": "ffprobe",
        "timeout": 30
      },
      "attachments": {
        "collections": 2,
        "channels": 0
      },
      "status": "available"
    },
    {
      "enricher_id": "enricher-metadata-b2c3d4e5",
      "type": "metadata",
      "name": "Movie Metadata",
      "config": {
        "sources": "imdb,tmdb",
        "api_key": "***REDACTED***"
      },
      "attachments": {
        "collections": 1,
        "channels": 0
      },
      "status": "available"
    },
    {
      "enricher_id": "enricher-playout-c3d4e5f6",
      "type": "playout",
      "name": "Channel Branding",
      "config": {
        "overlay_path": "/path/to/overlay.png"
      },
      "attachments": {
        "collections": 0,
        "channels": 1
      },
      "status": "available"
    }
  ],
  "total": 3
}
```

---

## Exit Codes

- `0`: Listing completed successfully
- `1`: Database access error, listing failure, or validation error

---

## Data Effects

### Database Queries

1. **Enricher Instance Lookup**:

   - Queries enricher instances from database
   - Validates enricher type availability
   - Checks attachment status

2. **Attachment Status**:
   - Counts collections attached to each enricher
   - Counts channels attached to each enricher
   - Reports attachment statistics

### Side Effects

- Database queries (read-only)
- No external system calls or database modifications
- No filesystem changes

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST list all configured enricher instances from the database.
- **B-2:** The command MUST display enricher type, name, and configuration for each instance.
- **B-3:** When `--json` is supplied, output MUST include fields `"status"`, `"enrichers"`, and `"total"` with appropriate data structures.
- **B-4:** On listing failure (database access error), the command MUST exit with code `1` and print a human-readable error message.
- **B-5:** The `--dry-run` flag MUST show what would be listed without executing database queries.
- **B-6:** Enricher listing MUST be deterministic - the same database state MUST produce the same listing results.
- **B-7:** The command MUST report attachment status for each enricher instance.
- **B-8:** Empty listing results (no enricher instances) MUST return exit code `0` with message "No enricher instances configured".

---

## Data Contract Rules (D-#)

- **D-1:** Database queries MUST be read-only during listing operations.
- **D-2:** Enricher instance lookup MUST validate enricher type availability.
- **D-3:** Attachment status MUST be calculated accurately for each enricher.
- **D-4:** Enricher listing MUST NOT modify external systems or database tables.
- **D-5:** Database queries MUST be atomic and consistent.
- **D-6:** Enricher availability status MUST be validated against registry state.
- **D-7:** Configuration display MUST respect privacy settings (redact sensitive data).
- **D-8:** Listing operations MUST be performant and not block other operations.

---

## Test Coverage Mapping

- `B-1..B-8` → `test_enricher_list_contract.py`
- `D-1..D-8` → `test_enricher_list_data_contract.py`

---

## Error Conditions

### Database Errors

- Database connection error: "Error: Cannot connect to database"
- Query failure: "Error: Failed to query enricher instances"
- Access error: "Error: Database access denied"

### Validation Errors

- Invalid enricher type: "Error: Enricher type 'invalid' not found in registry"
- Corrupted configuration: "Error: Invalid configuration for enricher 'enricher-ffprobe-a1b2c3d4'"
- Missing enricher: "Error: Enricher instance not found"

---

## Examples

### Basic Listing

```bash
# List all configured enricher instances
retrovue enricher list

# List with JSON output
retrovue enricher list --json

# Preview listing without database queries
retrovue enricher list --dry-run
```

### Test Environment Usage

```bash
# Test enricher listing in isolated environment
retrovue enricher list --test-db

# Test with mock enricher instances
retrovue enricher list --test-db --json
```

### Error Scenarios

```bash
# Database connection error
retrovue enricher list
# Error: Cannot connect to database

# No enricher instances configured
retrovue enricher list
# No enricher instances configured
```

---

## Supported Enricher Types

- **ffprobe**: Video/audio analysis using FFprobe (ingest type)
- **metadata**: Metadata extraction and enrichment (ingest type)
- **playout**: Playout enricher for channel processing (playout type)
- **Custom**: Third-party enricher implementations

---

## Safety Guidelines

- Always use `--test-db` for testing listing logic
- Use `--dry-run` to preview listing results
- Verify database connectivity before listing
- Check enricher availability after listing

---

## See Also

- [Enricher List Types](EnricherListTypesContract.md) - List available enricher types
- [Enricher Add](EnricherAddContract.md) - Create enricher instances
- [Enricher Update](EnricherUpdateContract.md) - Update enricher configurations
- [Enricher Remove](EnricherRemoveContract.md) - Remove enricher instances
