# Enricher Add

## Purpose

Define the behavioral contract for creating new enricher instances. This contract ensures safe, consistent enricher creation with proper validation and configuration handling.

---

## Command Shape

```
retrovue enricher add --type <type> --name <name> [options] [--test-db] [--dry-run] [--json]
```

### Required Parameters

- `--type`: Enricher type identifier ("ingest" or "playout")
- `--name`: Human-readable name for the enricher instance

### Type-Specific Parameters

**Ingest Enrichers:**

- `--config`: JSON configuration for the enricher (optional, default: "{}")

**Playout Enrichers:**

- `--config`: JSON configuration for the enricher (optional, default: "{}")

### Optional Parameters

- `--test-db`: Direct command to test database environment
- `--dry-run`: Show what would be created without executing
- `--json`: Output result in JSON format
- `--help`: Show help for the specified enricher type

---

## Safety Expectations

### Confirmation Model

- No confirmation prompts required for enricher creation
- `--dry-run` shows configuration validation and enricher ID generation
- `--force` flag not applicable (non-destructive operation)

### Validation Requirements

- Enricher type must be valid and available
- Required parameters must be provided for each enricher type
- Enricher ID must be unique (format: "enricher-{type}-{hash}")
- Configuration must be valid before database operations
- Type validation must be performed

---

## Output Format

### Human-Readable Output

**Success Output:**

```
Successfully created ingest enricher: Video Analysis
  ID: enricher-ingest-a1b2c3d4
  Type: ingest
  Name: Video Analysis
  Configuration: {"ffprobe_path": "ffprobe", "timeout": 30}
```

**Help Output:**

```
Help for ingest enricher type:
Description: Enrichers that run during content ingestion to add value to assets

Required parameters:
  --name: Human-readable label for this enricher

Optional parameters:
  --config: JSON configuration for the enricher
    Default: {}

Examples:
  retrovue enricher add --type ingest --name 'Video Analysis'
  retrovue enricher add --type ingest --name 'Metadata Enrichment' --config '{"sources": ["imdb", "tmdb"]}'
```

### JSON Output

```json
{
  "enricher_id": "enricher-ingest-a1b2c3d4",
  "type": "ingest",
  "name": "Video Analysis",
  "config": {
    "ffprobe_path": "ffprobe",
    "timeout": 30
  },
  "status": "created"
}
```

---

## Exit Codes

- `0`: Enricher created successfully
- `1`: Validation error, missing parameters, or creation failure

---

## Data Effects

### Database Changes

1. **Enricher Table**: New record inserted with:

   - Generated UUID primary key
   - Enricher ID in format "enricher-{type}-{hash}"
   - Enricher type
   - Configuration JSON
   - Created/updated timestamps

2. **Registry Updates**:
   - Enricher instance registered in registry
   - Configuration validated against type schema
   - Type validation performed

### Side Effects

- Enricher ID generation (must be unique)
- Configuration validation
- Registry state updates

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST validate enricher type against available types before proceeding.
- **B-2:** Required parameters MUST be validated before any database operations.
- **B-3:** Enricher ID MUST be generated in format "enricher-{type}-{hash}" and MUST be unique.
- **B-4:** When `--json` is supplied, output MUST include fields `"enricher_id"`, `"type"`, `"name"`, `"config"`, and `"status"`.
- **B-5:** On validation failure, the command MUST exit with code `1` and print a human-readable error message.
- **B-6:** The `--dry-run` flag MUST show configuration validation and enricher ID generation without executing.
- **B-7:** The `--help` flag MUST display detailed help for the specified enricher type and MUST exit with code `0` without creating any enricher instances.
- **B-8:** Configuration validation MUST be performed against the enricher type's schema.

---

## Data Contract Rules (D-#)

- **D-1:** Enricher creation MUST occur within a single transaction boundary.
- **D-2:** Enricher ID generation MUST be atomic and collision-free.
- **D-3:** Configuration validation MUST occur before database persistence.
- **D-4:** On transaction failure, ALL changes MUST be rolled back with no partial creation.
- **D-5:** Enricher type validation MUST occur before database operations.
- **D-6:** Type validation MUST be performed for the enricher type.
- **D-7:** Registry updates MUST occur within the same transaction as enricher creation.
- **D-8:** Configuration schema validation MUST be performed against the enricher type.

---

## Test Coverage Mapping

- `B-1..B-8` → `test_enricher_add_contract.py`
- `D-1..D-8` → `test_enricher_add_data_contract.py`

---

## Error Conditions

### Validation Errors

- Invalid enricher type: "Unknown enricher type 'invalid'. Available types: ingest, playout"
- Missing required parameters: "Error: --name is required for ingest enrichers"
- Invalid configuration: "Error: Invalid configuration for enricher type 'ingest'"

### Database Errors

- Duplicate enricher ID: Transaction rollback, clear error message
- Foreign key violations: Transaction rollback, diagnostic information

---

## Examples

### Ingest Enricher Creation

```bash
# Create ingest enricher with default config
retrovue enricher add --type ingest --name "Video Analysis"

# Create ingest enricher with custom config
retrovue enricher add --type ingest --name "Metadata Enrichment" \
  --config '{"sources": ["imdb", "tmdb"], "api_key": "your-key"}'

# Get help for ingest enricher
retrovue enricher add --type ingest --help
```

### Playout Enricher Creation

```bash
# Create playout enricher with default config
retrovue enricher add --type playout --name "Channel Branding"

# Create playout enricher with custom config
retrovue enricher add --type playout --name "Custom Overlay" \
  --config '{"overlay_path": "/path/to/overlay.png", "position": "top-right"}'

# Get help for playout enricher
retrovue enricher add --type playout --help
```

### Test Environment Usage

```bash
# Test enricher creation in isolated environment
retrovue enricher add --type ingest --name "Test Enricher" \
  --test-db --dry-run

# Test with JSON output
retrovue enricher add --type playout --name "Test Playout" \
  --test-db --json
```

---

## Supported Enricher Types

- **ingest**: Enrichers that run during content ingestion to add value to assets
- **playout**: Enrichers that run during playout to add value to content being broadcast

---

## Safety Guidelines

- Always use `--test-db` for testing enricher creation logic
- Use `--dry-run` to preview enricher creation
- Verify enricher type availability before creation
- Check configuration validation after creation

---

## See Also

- [Enricher List Types](EnricherListTypesContract.md) - List available enricher types
- [Enricher List](EnricherListContract.md) - List configured enricher instances
- [Enricher Update](EnricherUpdateContract.md) - Update enricher configurations
- [Enricher Remove](EnricherRemoveContract.md) - Remove enricher instances
