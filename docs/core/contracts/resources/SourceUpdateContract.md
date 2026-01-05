# Source Update

## Purpose

Define the behavioral contract for updating existing content sources in RetroVue. This contract ensures safe, consistent source configuration updates with proper validation, importer interface compliance verification, and atomic transaction handling.

---

## Command Shape

```
retrovue source update <source_selector> [--name <name>] [importer-specific flags] [--test-db] [--dry-run] [--json]
```

### Required Parameters

- `source_selector`: Source identifier (UUID, external ID, or exact name)

### Optional Parameters

- `--name <name>`: Update the human-readable name for the source
- Importer-specific configuration flags (e.g., `--base-url`, `--token`, `--base-path`, `--enrichers`, etc.) may be supplied. Only provided flags will be applied. Unspecified fields remain unchanged.
- `--test-db`: Direct command to test database environment
- `--dry-run`: Show what would be updated without executing
- `--json`: Output result in JSON format

### Type-Specific Configuration Parameters

**Dynamic Flag Discovery:**

The CLI is dynamic and asks the importer: "what fields can I update, and how should they surface as flags?"

Importer-specific configuration flags are dynamically generated based on the importer's `get_update_fields()` method, which returns `UpdateFieldSpec` objects describing:

- The CLI flag name (e.g., `--base-url`, `--token`)
- The underlying configuration key (e.g., `base_url`, `token`)
- Whether the field is sensitive (for redaction)
- Whether the field is immutable (cannot be updated)
- A human-readable description for help text

**Examples:**

**Plex Sources:**

- `--base-url <url>`: Update Plex server base URL
- `--token <token>`: Update Plex authentication token (sensitive)
- `--servers <json>`: Update servers configuration (JSON array format)

**Filesystem Sources:**

- `--base-path <path>`: Update base filesystem path to scan

**Common Parameters:**

- `--enrichers <list>`: Update comma-separated list of enrichers

Running `retrovue source update --type plex --help` MUST dynamically list the supported update flags for the Plex importer as declared by the importer's `get_update_fields()` method.

You MAY update any subset of supported fields (e.g., update only base_url, or only token, or both).

Updating one field MUST NOT require resending sibling fields.

Unspecified fields MUST keep their previous values.

---

## Safety Expectations

### Update Model

- **Non-destructive operation**: Only updates configuration parameters
- **Idempotent**: Safe to run multiple times with same parameters
- **Dry-run support**: Preview updates without database changes
- **Test isolation**: `--test-db` prevents external system calls

### Validation Requirements

- Source must exist and be accessible
- Importer must be interface compliant (ImporterInterface) and implement `get_update_fields()` and `validate_partial_update()`
- Configuration parameters must be valid according to importer's `validate_partial_update()` method
- Schema validation MUST occur only for keys present in the update payload. Full re-validation of unchanged fields is NOT required.
- The importer's `validate_partial_update()` method MUST be called with only the fields being updated
- Configuration validation must occur before database updates
- External ID and type cannot be changed (immutable fields)
- Attempts to update immutable fields MUST be detected during validation, before any transaction is opened
- Immutable fields MUST NOT be exposed as update flags by the importer's `get_update_fields()` method

### Dry-run Behavior

- In `--dry-run` mode, no database writes MAY occur
- On valid input, exit code MUST be 0 and output MUST match the normal `--json` shape
- On invalid input, exit code MUST be 1 and MUST emit the same human-readable error used in non-dry-run mode
- Dry-run human-readable output includes current and proposed configuration for validation purposes

### Test Database Behavior

- In `--test-db` mode, ALL database writes MUST be isolated to a non-production test environment
- `--test-db` MUST NOT leak any writes to production databases or persistent storage
- When `--test-db` is combined with `--dry-run`, dry-run behavior takes precedence (no writes occur)
- Behavior, output format, and exit codes MUST remain identical to production mode

---

## Output Format

### Human-Readable Output

**Successful Update:**

```
Successfully updated source: My Plex Server
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Name: My Updated Plex Server
  Type: plex
  Updated Parameters:
    - base_url: https://new-plex.example.com
    - token: ***REDACTED***
```

**Dry-run Output:**

```
Would update source: My Plex Server
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Current Name: My Plex Server
  Proposed Name: My Updated Plex Server
  Current Configuration:
    - base_url: https://old-plex.example.com
    - token: ***REDACTED***
  Proposed Configuration:
    - base_url: https://new-plex.example.com
    - token: ***REDACTED***

(No database changes made — dry-run mode)
```

### JSON Output

**Successful Update:**

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926",
  "name": "My Updated Plex Server",
  "type": "plex",
  "config": {
    "servers": [
      { "base_url": "https://new-plex.example.com", "token": "***REDACTED***" }
    ]
  },
  "updated_at": "2024-01-20T14:45:00Z",
  "updated_parameters": ["name", "base_url", "token"]
}
```

**Dry-run Output:**

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926",
  "current_name": "My Plex Server",
  "proposed_name": "My Updated Plex Server",
  "type": "plex",
  "current_config": {
    "servers": [
      { "base_url": "https://old-plex.example.com", "token": "***REDACTED***" }
    ]
  },
  "proposed_config": {
    "servers": [
      { "base_url": "https://new-plex.example.com", "token": "***REDACTED***" }
    ]
  },
  "updated_parameters": ["name", "base_url", "token"]
}
```

---

## Exit Codes

- `0`: Source updated successfully
- `1`: Validation error, source not found, or update failure

---

## Data Effects

### Database Changes

1. **Source Table**: Updated record with:

   - Modified `name` field (if `--name` provided)
   - Updated `config` JSON field with new parameters
   - Updated `updated_at` timestamp (automatic)

2. **No Cascade Effects**: Source updates do not affect related collections or path mappings

### Side Effects

- Configuration validation against importer schema (structural/schema-based only)
- External ID and type remain unchanged (immutable)
- **No external system calls**: The source update command MUST NOT perform any live external calls (e.g., Plex API probes, filesystem scans) in any mode, including `--test-db`. Validation is purely structural/schema-based. This keeps update operations light, fast, deterministic, and aligned with the principle that "config administration ≠ connectivity testing".

---

## Behavior Contract Rules (B-#)

### Existence and Validation (B-1–B-6)

- **B-1:** The command MUST validate source existence before attempting updates. If the `source_selector` matches multiple sources (e.g., ambiguous name), the command MUST exit with code `1` and print "Error: Multiple sources match 'X'. Please use ID."
- **B-2:** The command MUST validate all configuration parameters using the importer's `validate_partial_update()` method before database updates. The validation MUST be called with only the fields present in the update payload.
- **B-3:** The command MUST NOT allow updates to immutable fields (`id`, `external_id`, `type`, `created_at`).
- **B-4:** When `--json` is supplied, output MUST include fields `"id"`, `"external_id"`, `"name"`, `"type"`, `"config"`, and `"updated_parameters"`.
- **B-5:** On validation failure (source not found), the command MUST exit with code `1` and print "Error: Source 'X' not found".
- **B-6:** On configuration validation failure, the command MUST exit with code `1` and print a human-readable error message describing the validation failure.

### Mode Handling (B-7–B-11)

- **B-7:** The `--dry-run` flag MUST show current and proposed configuration without executing database updates. In dry-run mode, no database writes MAY occur.
- **B-8:** The `--test-db` flag MUST isolate ALL database writes to a non-production test environment. `--test-db` MUST NOT leak any writes to production databases or persistent storage.
- **B-9:** When `--test-db` is combined with `--dry-run`, dry-run behavior takes precedence (no writes occur).
- **B-10:** Behavior, output format, and exit codes MUST remain identical to production mode when using `--test-db`.
- **B-11:** In `--test-db` mode, the command MUST use the test/unit-of-work context instead of the production unit-of-work context. This ensures that all database operations are routed to the test database session and no production data is accessed or modified.

### Update Logic (B-12–B-14)

- **B-12:** The command MUST support updating multiple importer-defined configuration parameters in a single operation.
- **B-13:** The command MUST perform a non-destructive, field-level update. Only the configuration keys named via importer-specific flags (and/or `--name`) may change. All other configuration keys and values MUST be preserved exactly as they existed before the update.
- **B-14:** Configuration parameter validation MUST occur before any database operations.

### Output and Redaction (B-15–B-16)

- **B-15:** Sensitive values (e.g., API tokens, credentials) MUST be redacted (`"***REDACTED***"`) in all output modes, including `--json` and `--dry-run`.
- **B-16:** When `--dry-run` and `--json` are both provided, exit code MUST be `0` on valid input and the output MUST use the dry-run JSON shape (`current_*` / `proposed_*`) instead of the post-update shape.

### Importer and External Safety (B-17–B-18)

- **B-17:** The command MUST verify that the importer for the source's type is available and interface-compliant before configuration validation. The importer MUST implement `get_update_fields()` and `validate_partial_update()` methods. If the importer cannot be loaded, does not implement ImporterInterface, or is missing required update methods, the command MUST exit with code `1` and print "Error: Importer for source type 'X' is not available or not interface-compliant".
- **B-18:** The command MUST NOT perform any live external system calls (e.g., Plex API probes, filesystem scans, connectivity tests) in any mode (production, `--test-db`, `--dry-run`). Validation is purely structural/schema-based using the importer's `get_config_schema()` method. This ensures update operations are light, fast, deterministic, and aligned with config administration (not connectivity testing).

### Concurrency (B-19)

- **B-19:** If the update transaction fails due to concurrent modification, the command MUST exit with code `1` and print "Error: Source was modified concurrently. Please retry."

### Help and Discoverability (B-20)

- **B-20:** The command MUST expose importer-specific configuration fields in its help output. Running `retrovue source update --type <source_type> --help` MUST list all updatable parameters for that source type, their expected value format, and a short description.

---

## Data Contract Rules (D-#)

- **D-1:** Source updates MUST occur within a single transaction boundary. All update operations MUST execute inside a UnitOfWork per UnitOfWorkContract.md to guarantee atomicity and rollback.
- **D-2:** Configuration and importer validation MUST complete successfully before opening the transactional Unit of Work. This ensures that validation failures never trigger rollback logs or DB session writes.
- **D-3:** On transaction failure, ALL changes MUST be rolled back with no partial updates.
- **D-4:** Immutable fields (`id`, `external_id`, `type`, `created_at`) MUST NOT be modified.
- **D-5:** The `updated_at` timestamp MUST be automatically updated on successful changes.
- **D-6:** Configuration parameters MUST be validated against importer's `validate_partial_update()` method. This method MUST be called with only the keys present in the update payload.
- **D-7:** Importer interface compliance MUST be verified before configuration validation. The system MUST be able to load the importer for the source's type from the registry, and the importer MUST implement ImporterInterface (or subclass BaseImporter) including `get_update_fields()` and `validate_partial_update()` methods. If any condition fails, the operation MUST abort with exit code 1 and the error message specified in B-17.
- **D-8:** When `--test-db` is provided, ALL database operations MUST be isolated to a test environment and MUST NOT affect production data.
- **D-9:** Test database isolation MUST be enforced at the transaction level, ensuring no cross-contamination with production systems. This MUST be implemented by using the test/unit-of-work context instead of the production unit-of-work context, as specified in B-11.
- **D-10:** Configuration updates MUST be applied as a partial merge on the source's existing config. Keys present in the update MUST overwrite the existing values for those keys. Keys not present in the update MUST remain unchanged. The command MUST NOT drop, null-out, or replace unrelated keys/objects/arrays in config. Partial merges apply only to top-level keys of the config object. Nested objects or arrays (e.g., `servers`) are treated as atomic values—updated wholesale if referenced.

---

## Test Coverage Mapping

- `B-1..B-20` → `test_source_update_contract.py`
- `D-1..D-10` → `test_source_update_data_contract.py`

---

## Error Conditions

### Validation Errors

- Source not found: "Error: Source 'invalid-source' not found"
- Multiple sources match selector: "Error: Multiple sources match 'X'. Please use ID."
- Importer not available or not compliant: "Error: Importer for source type 'plex' is not available or not interface-compliant"
- Invalid configuration parameter: "Error: Invalid configuration parameter 'invalid_param' for source type 'plex'"
- Missing required parameter: "Error: Configuration parameter 'base_url' is required for Plex sources"
- Invalid parameter value: "Error: Invalid URL format for base_url parameter"
- Immutable field update: "Error: Cannot update immutable field 'external_id'"

### Database Errors

- Transaction rollback on any persistence failure
- Foreign key constraint violations handled gracefully
- Concurrent modification: "Error: Source was modified concurrently. Please retry."

---

## Examples

### Basic Source Updates

```bash
# Update source name
retrovue source update "My Plex Server" --name "Updated Plex Server"

# Update only the Plex token (preserves existing base_url, servers, enrichers, etc.)
retrovue source update "My Plex Server" --token "new-token-here"

# Update only the Plex base_url (preserves token)
retrovue source update "My Plex Server" --base-url "https://new-plex.example.com"

# Update multiple parameters in a single call (patch semantics)
retrovue source update "My Plex Server" \
  --base-url "https://new-plex.example.com" \
  --token "new-token-here"

# Update filesystem source path
retrovue source update "Media Library" --base-path "/new/media/path"
```

### Dry-run Testing

```bash
# Preview updates without changes
retrovue source update "My Plex Server" --name "New Name" --dry-run

# Test update logic
retrovue source update "Test Source" --base-url "http://test:32400" --test-db --dry-run
```

### Test Environment Usage

```bash
# Test source updates in isolated environment
retrovue source update "Test Plex Server" --name "Updated Test Server" --test-db

# Test with JSON output
retrovue source update "Test Source" --base-url "http://test:32400" --test-db --json
```

### Error Scenarios

```bash
# Source not found
retrovue source update "Non-existent Source" --name "New Name"
# Error: Source 'Non-existent Source' not found

# Importer not available or not compliant
retrovue source update "My Plex Server" --base-url "https://plex.example.com"
# Error: Importer for source type 'plex' is not available or not interface-compliant

# Invalid configuration parameter
retrovue source update "My Plex Server" --invalid-param "value"
# Error: Invalid configuration parameter 'invalid_param' for source type 'plex'

# Attempt to update immutable field (if flag exists)
retrovue source update "My Plex Server" --external-id "new-id"
# Error: Cannot update immutable field 'external_id'
```

---

## Configuration Parameter Examples

### Plex Source Updates

```bash
# Update server URL only
retrovue source update "My Plex" --base-url "https://plex.example.com"

# Update authentication token only
retrovue source update "My Plex" --token "new-token-here"

# Update servers configuration (JSON format)
retrovue source update "My Plex" --servers '[{"base_url":"https://plex1.example.com","token":"token1"},{"base_url":"https://plex2.example.com","token":"token2"}]'

# Update enrichers
retrovue source update "My Plex" --enrichers "ffprobe,metadata,thumbnails"
```

### Filesystem Source Updates

```bash
# Update base path
retrovue source update "Media Library" --base-path "/new/media/path"

# Update enrichers
retrovue source update "Media Library" --enrichers "ffprobe,metadata"
```

### Help and Discoverability

```bash
# View available update flags for Plex sources
retrovue source update --type plex --help

# View available update flags for filesystem sources
retrovue source update --type filesystem --help
```

---

## Safety Guidelines

- Always use `--test-db` for testing update logic
- Use `--dry-run` to preview configuration changes
- Verify source identification before updates
- Test configuration changes in isolated environment first
- Monitor for validation errors and parameter conflicts

---

## See Also

- [Source Add](SourceAddContract.md) - Creating sources with configuration validation
- [Source List](SourceListContract.md) - Viewing current source configurations
- [Source List Types](SourceListTypesContract.md) - Available source types and their parameters
- [Unit of Work](../_ops/UnitOfWorkContract.md) - Transaction management requirements for atomic operations
- [Importer Interface](../../../src/retrovue/adapters/importers/base.py) - Importer interface including `get_update_fields()` and `validate_partial_update()` requirements

---

## Importer Interface Requirements for Source Update

### Required Methods

All importers MUST implement the following methods to support source updates:

#### `get_update_fields() -> list[UpdateFieldSpec]`

This method MUST return all user-settable configuration fields for this importer, including:

- The CLI flag name (e.g., `"--base-url"`, `"--token"`)
- The underlying config key (e.g., `"base_url"`, `"token"`)
- Whether the field is sensitive (for redaction in output)
- Whether the field is immutable (cannot be updated)
- A human-readable description for help text

This method enables the CLI to dynamically generate help text and command-line flags.

#### `validate_partial_update(partial_config: dict) -> None`

This method MUST:

- Ensure each provided key is valid for this importer
- Enforce type/format rules (e.g., URL must look like a URL, path must exist)
- Enforce required relationships (if any)
- Raise `ImporterConfigurationError` with a human-readable message on failure

This method is called with only the fields present in the update payload (not the entire configuration).

### Example Implementation

```python
@classmethod
def get_update_fields(cls) -> list[UpdateFieldSpec]:
    return [
        UpdateFieldSpec(
            config_key="base_url",
            cli_flag="--base-url",
            help="Plex server base URL",
            field_type="string",
            is_sensitive=False,
            is_immutable=False
        ),
        UpdateFieldSpec(
            config_key="token",
            cli_flag="--token",
            help="Plex authentication token",
            field_type="string",
            is_sensitive=True,
            is_immutable=False
        ),
    ]

@classmethod
def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
    if "base_url" in partial_config:
        url = partial_config["base_url"]
        if not url.startswith(("http://", "https://")):
            raise ImporterConfigurationError(
                "base_url must start with http:// or https://"
            )
    if "token" in partial_config:
        if not partial_config["token"]:
            raise ImporterConfigurationError("token cannot be empty")
```
