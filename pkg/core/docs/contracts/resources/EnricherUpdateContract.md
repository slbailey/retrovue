# Enricher Update

## Purpose

Define the behavioral contract for updating enricher enrichment parameters. This contract ensures safe, consistent enricher updates with proper validation and parameter handling. Enrichment parameters are the specific values an enricher needs to perform its enrichment tasks (e.g., API keys, file paths, timing values).

---

## Command Shape

```
retrovue enricher update <enricher_id> [options] [--test-db] [--dry-run] [--json]
```

### Required Parameters

- `enricher_id`: Enricher instance identifier (UUID or enricher ID)

### Type-Specific Enrichment Parameters

**FFmpeg/FFprobe Enrichers:**

- Typically require no parameters (use system defaults)
- If parameters are provided, the command should inform the user that updates are not necessary

**TheTVDB Enrichers:**

- `--api-key`: New API key for TheTVDB authentication
- `--language`: Language preference for metadata retrieval

**TMDB Enrichers:**

- `--api-key`: New API key for TMDB authentication
- `--language`: Language preference for metadata retrieval

**File Parser Enrichers:**

- `--pattern`: Updated filename parsing pattern
- `--field-mapping`: Updated field mapping rules

**LLM Enrichers:**

- `--api-key`: New API key for LLM service
- `--model`: Updated model identifier
- `--prompt-template`: Updated prompt template

**Watermark Enrichers:**

- `--overlay-path`: Updated path to watermark image
- `--position`: Updated watermark position
- `--opacity`: Updated watermark opacity

**Crossfade Enrichers:**

- `--duration`: Updated transition duration
- `--curve`: Updated transition curve type

**Lower-Third Enrichers:**

- `--template-path`: Updated template file path
- `--data-source`: Updated data source configuration

### Optional Parameters

- `--test-db`: Direct command to test database environment
- `--dry-run`: Show what would be updated without executing
- `--json`: Output result in JSON format

---

## Safety Expectations

### Confirmation Model

- No confirmation prompts required for enricher updates
- `--dry-run` shows configuration validation and update preview
- `--force` flag not applicable (non-destructive operation)

### Validation Requirements

- Enricher instance must exist and be available
- Configuration must be valid for the enricher type
- Configuration validation before database operations
- Scope validation must be maintained

---

## Output Format

### Human-Readable Output

**Success Output:**

```
Successfully updated enricher: Video Analysis
  ID: enricher-ffprobe-a1b2c3d4
  Type: ffprobe
  Name: Video Analysis
  Configuration: {"ffprobe_path": "/usr/bin/ffprobe", "timeout": 60}
  Updated: 2024-01-15 10:30:00
```

**Dry-run Output:**

```
Would update enricher: Video Analysis
  ID: enricher-ffprobe-a1b2c3d4
  Type: ffprobe
  Name: Video Analysis
  Current Configuration: {"ffprobe_path": "ffprobe", "timeout": 30}
  New Configuration: {"ffprobe_path": "/usr/bin/ffprobe", "timeout": 60}
```

### JSON Output

```json
{
  "enricher_id": "enricher-ffprobe-a1b2c3d4",
  "type": "ffprobe",
  "name": "Video Analysis",
  "config": {
    "ffprobe_path": "/usr/bin/ffprobe",
    "timeout": 60
  },
  "status": "updated",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

---

## Exit Codes

- `0`: Enricher updated successfully
- `1`: Validation error, enricher not found, or update failure

---

## Data Effects

### Database Changes

1. **Enricher Table**: Record updated with:

   - New configuration JSON
   - Updated timestamp
   - Validation status

2. **Registry Updates**:
   - Enricher instance configuration updated in registry
   - Configuration validated against type schema
   - Scope validation maintained

### Side Effects

- Configuration validation
- Registry state updates
- No external system calls

---

## Behavior Contract Rules (B-#)

- **B-1:** The command MUST validate enricher instance existence before attempting updates.
- **B-2:** Enrichment parameter validation MUST be performed against the enricher type's parameter schema.
- **B-3:** When `--json` is supplied, output MUST include fields `"enricher_id"`, `"type"`, `"name"`, `"config"`, `"status"`, and `"updated_at"`.
- **B-4:** On validation failure (enricher not found), the command MUST exit with code `1` and print "Error: Enricher 'X' not found".
- **B-5:** The `--dry-run` flag MUST show enrichment parameter validation and update preview without executing.
- **B-6:** Enrichment parameter updates MUST preserve enricher type and core functionality.
- **B-7:** The command MUST support partial enrichment parameter updates (only specified parameters).
- **B-8:** Update operations MUST be atomic and consistent.
- **B-9:** For enrichers that require no parameters (e.g., FFmpeg), the command MUST inform the user that updates are not necessary.
- **B-10:** The command MUST validate enrichment parameters against the enricher's specific requirements (e.g., API key format, file path existence).

---

## Data Contract Rules (D-#)

- **D-1:** Enricher updates MUST occur within a single transaction boundary.
- **D-2:** Enrichment parameter validation MUST occur before database persistence.
- **D-3:** On transaction failure, ALL changes MUST be rolled back with no partial updates.
- **D-4:** Enricher type and core functionality MUST NOT be changed during updates.
- **D-5:** Registry updates MUST occur within the same transaction as enricher updates.
- **D-6:** Enrichment parameter schema validation MUST be performed against the enricher type.
- **D-7:** Update operations MUST preserve enricher instance identity.
- **D-8:** Enrichment parameter updates MUST maintain backward compatibility where possible.
- **D-9:** Enrichment parameters MUST be validated for correctness (e.g., API key format, file existence).
- **D-10:** Parameter updates MUST preserve the enricher's ability to perform its enrichment tasks.

---

## Test Coverage Mapping

- `B-1..B-10` → `test_enricher_update_contract.py`
- `D-1..D-10` → `test_enricher_update_data_contract.py`

---

## Error Conditions

### Validation Errors

- Enricher not found: "Error: Enricher 'enricher-ffprobe-a1b2c3d4' not found"
- Invalid enrichment parameters: "Error: Invalid enrichment parameters for enricher type 'tvdb'"
- Missing required parameters: "Error: Required enrichment parameter '--api-key' not provided"
- No parameters needed: "Info: FFmpeg enricher requires no parameter updates"
- Invalid parameter format: "Error: API key format is invalid"
- File not found: "Error: Watermark file '/path/to/watermark.png' not found"

### Database Errors

- Transaction rollback on any persistence failure
- Foreign key constraint violations handled gracefully
- Concurrent modification: Transaction rollback with retry suggestion

---

## Examples

### FFmpeg Enricher Update (No Parameters Needed)

```bash
# FFmpeg enrichers typically don't need parameter updates
retrovue enricher update enricher-ffmpeg-a1b2c3d4
# Output: "FFmpeg enricher requires no parameter updates"

# Dry run shows no changes needed
retrovue enricher update enricher-ffmpeg-a1b2c3d4 --dry-run
# Output: "No enrichment parameters to update for FFmpeg enricher"
```

### TheTVDB Enricher Update

```bash
# Update API key for TheTVDB authentication
retrovue enricher update enricher-tvdb-b2c3d4e5 \
  --api-key "new-tvdb-api-key"

# Update language preference
retrovue enricher update enricher-tvdb-b2c3d4e5 \
  --language "en-US"

# Update multiple parameters
retrovue enricher update enricher-tvdb-b2c3d4e5 \
  --api-key "new-tvdb-api-key" --language "en-US"
```

### Watermark Enricher Update

```bash
# Update watermark image path
retrovue enricher update enricher-watermark-c3d4e5f6 \
  --overlay-path "/new/path/to/watermark.png"

# Update watermark position and opacity
retrovue enricher update enricher-watermark-c3d4e5f6 \
  --position "top-right" --opacity 0.7
```

### LLM Enricher Update

```bash
# Update API key for LLM service
retrovue enricher update enricher-llm-d4e5f6g7 \
  --api-key "new-openai-api-key"

# Update model and prompt template
retrovue enricher update enricher-llm-d4e5f6g7 \
  --model "gpt-4" --prompt-template "/path/to/new/template.txt"
```

### Test Environment Usage

```bash
# Test enricher update in isolated environment
retrovue enricher update enricher-ffprobe-a1b2c3d4 \
  --timeout 60 --test-db --dry-run

# Test with JSON output
retrovue enricher update enricher-metadata-b2c3d4e5 \
  --sources "tvdb,imdb" --test-db --json
```

---

## Supported Enricher Types

- **ffmpeg**: Video/audio analysis using FFmpeg (typically no parameters needed)
- **ffprobe**: Video/audio metadata extraction using FFprobe (typically no parameters needed)
- **tvdb**: Metadata extraction from TheTVDB (requires `--api-key`)
- **tmdb**: Metadata extraction from TMDB (requires `--api-key`)
- **file-parser**: Filename parsing for metadata extraction (may require `--pattern`)
- **llm**: LLM-based metadata generation (requires `--api-key`, `--model`)
- **watermark**: Video watermark overlay (requires `--overlay-path`)
- **crossfade**: Video transition effects (requires `--duration`)
- **lower-third**: Lower-third graphics overlay (requires `--template-path`)
- **emergency-crawl**: Emergency text crawl overlay (requires `--message`)

---

## Safety Guidelines

- Always use `--test-db` for testing enricher update logic
- Use `--dry-run` to preview enricher updates
- Verify enricher instance existence before updates
- Check configuration validation after updates

---

## See Also

- [Enricher List Types](EnricherListTypesContract.md) - List available enricher types
- [Enricher Add](EnricherAddContract.md) - Create enricher instances
- [Enricher List](EnricherListContract.md) - List configured enricher instances
- [Enricher Remove](EnricherRemoveContract.md) - Remove enricher instances
