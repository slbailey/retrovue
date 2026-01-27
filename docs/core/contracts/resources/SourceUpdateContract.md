# Source Update Contract

## Purpose

Define the observable guarantees for updating existing content sources in RetroVue. This contract specifies **what** the update operation guarantees, not how it is implemented.

---

## Command Shape

```
retrovue source update <source_selector> [--name <name>] [type-specific flags] [--test-db] [--dry-run] [--json]
```

### Required Parameters

- `source_selector`: Source identifier (UUID, external ID, or exact name)

### Optional Parameters

- `--name <name>`: Update the human-readable name
- Type-specific configuration flags (e.g., `--base-url`, `--token`, `--base-path`)
- `--test-db`: Direct command to test database environment
- `--dry-run`: Show what would be updated without executing
- `--json`: Output result in JSON format

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Source updated successfully |
| `1` | Validation error, source not found, or update failure |

---

## Core Guarantees

### SU-010: Source Existence

**Guarantee:** Source must exist before update.

**Observable behavior:**
- Non-existent source → exit code 1
- Error message: "Source 'X' not found"

---

### SU-011: Ambiguous Selector Handling

**Guarantee:** Ambiguous selectors are rejected.

**Observable behavior:**
- Multiple matches → exit code 1
- Error message: "Multiple sources match 'X'. Please use ID."

---

### SU-020: Partial Update Semantics

**Guarantee:** Only specified fields are updated; others preserved.

**Observable behavior:**
- Unspecified fields retain previous values
- Single field can be updated independently
- Multiple fields can be updated together

---

### SU-021: Immutable Fields

**Guarantee:** Certain fields cannot be updated.

**Immutable fields:** `id`, `external_id`, `type`, `created_at`

**Observable behavior:**
- Attempt to update immutable field → exit code 1
- Error message: "Cannot update immutable field 'X'"

---

### SU-030: Configuration Validation

**Guarantee:** Configuration validated before database changes.

**Observable behavior:**
- Invalid configuration → exit code 1 with descriptive error
- Database unchanged on validation failure
- Validation is schema-based only (no external calls)

---

### SU-031: No External Calls

**Guarantee:** Update operation makes no external system calls.

**Observable behavior:**
- No Plex API probes, filesystem scans, or connectivity tests
- Update is fast, deterministic, and offline-safe
- Same behavior in all modes (production, test-db, dry-run)

---

### SU-040: Dry-Run Mode

**Guarantee:** Dry-run shows changes without executing them.

**Observable behavior:**
- No database writes in dry-run mode
- Output shows current and proposed configuration
- Valid input → exit code 0
- Invalid input → exit code 1 with same error as normal mode

---

### SU-041: Test Database Mode

**Guarantee:** Test-db isolates all writes to test environment.

**Observable behavior:**
- No production data affected
- Same output format and exit codes as production
- When combined with dry-run, dry-run takes precedence

---

### SU-050: Atomic Transaction

**Guarantee:** Update is atomic (all-or-nothing).

**Observable behavior:**
- Transaction failure → all changes rolled back
- No partial updates
- Concurrent modification → exit code 1 with retry message

---

### SU-051: Timestamp Update

**Guarantee:** `updated_at` timestamp automatically set on success.

---

## Output Format

### Human-Readable (Success)

```
Successfully updated source: My Plex Server
  ID: 4b2b05e7-d7d2-414a-a587-3f5df9b53f44
  Name: My Updated Plex Server
  Type: plex
  Updated Parameters:
    - base_url: https://new-plex.example.com
    - token: ***REDACTED***
```

### Human-Readable (Dry-Run)

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

### JSON (Success)

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

### JSON (Dry-Run)

```json
{
  "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
  "external_id": "plex-5063d926",
  "current_name": "My Plex Server",
  "proposed_name": "My Updated Plex Server",
  "type": "plex",
  "current_config": { ... },
  "proposed_config": { ... },
  "updated_parameters": ["name", "base_url", "token"]
}
```

---

## Sensitive Value Handling

**Guarantee:** Sensitive values redacted in all output.

**Observable behavior:**
- Tokens, credentials show as `***REDACTED***`
- Applies to JSON, human-readable, and dry-run output

---

## Help and Discoverability

**Guarantee:** Type-specific flags are discoverable.

**Observable behavior:**
- `retrovue source update --type plex --help` lists all updatable parameters
- Each parameter includes description and expected format

---

## Error Messages

| Condition | Message |
|-----------|---------|
| Source not found | "Error: Source 'X' not found" |
| Multiple matches | "Error: Multiple sources match 'X'. Please use ID." |
| Source type unsupported | "Error: Source type 'X' does not support updates" |
| Invalid parameter | "Error: Invalid configuration parameter 'X' for source type 'Y'" |
| Invalid value | "Error: Invalid URL format for base_url parameter" |
| Immutable field | "Error: Cannot update immutable field 'X'" |
| Concurrent modification | "Error: Source was modified concurrently. Please retry." |

---

## Behavioral Rules Summary

| Rule | Guarantee |
|------|-----------|
| SU-010 | Source must exist |
| SU-011 | Ambiguous selectors rejected |
| SU-020 | Partial update semantics |
| SU-021 | Immutable fields protected |
| SU-030 | Configuration validated before changes |
| SU-031 | No external system calls |
| SU-040 | Dry-run shows without executing |
| SU-041 | Test-db isolates writes |
| SU-050 | Atomic transaction |
| SU-051 | Timestamp auto-updated |

---

## Test Coverage

| Rule | Test |
|------|------|
| SU-010, SU-011 | `test_source_update_existence` |
| SU-020, SU-021 | `test_source_update_semantics` |
| SU-030, SU-031 | `test_source_update_validation` |
| SU-040, SU-041 | `test_source_update_modes` |
| SU-050, SU-051 | `test_source_update_transaction` |

---

## See Also

- [Source Add Contract](SourceAddContract.md) — creating sources
- [Source List Contract](SourceListContract.md) — viewing sources
- [Unit of Work Contract](../_ops/UnitOfWorkContract.md) — transaction guarantees
- [Contract Hygiene Checklist](../../../standards/contract-hygiene.md) — authoring guidelines
