# Source Ingest

## Purpose

Defines the exact behavior, safety, idempotence, and data effects of the ingest operation for an entire source. This is an iterative operation that processes all enabled **containers** within a source (contract entity: Container), following the same pattern as Source Discover but for asset ingestion rather than container discovery. Each container ingest operates in its own transaction boundary, allowing for partial success when some containers fail.

NOTE: This command operates at the source level and iterates across all enabled containers, processing each container's ingest operation. Each container ingest follows the exact same process defined in the Container Ingest contract, with each container operating in its own transaction boundary to allow for partial success when some containers fail.

---

## Command Shape

**CLI Syntax:**

```
retrovue source ingest <source_id>|"<source name>" [--dry-run] [--test-db] [--json] [--verify]
```

- `<source_id>`: The UUID or database identifier for the source to ingest
- `"source name"`: Human-friendly, quoted name for the source (alternative to ID)
- `--dry-run`: Show intended ingest actions without modifying the database
- `--test-db`: Direct all actions at the isolated test database environment
- `--json`: Output information in a structured JSON format for automation
- `--verify`: Diagnostic-only. After ingest, verify created assets exist in the same session and
  include verification counts in JSON output (see Verification section). No effect on exit codes.

**Scope Restrictions:**

- **BULK OPERATION ONLY**: This command operates at the source level and processes ALL enabled collections
- **NO COLLECTION-LEVEL NARROWING**: The command MUST NOT accept or forward any collection-level narrowing flags:
  - `--title`
  - `--season`
  - `--episode`
- **SURGICAL CONTROL**: For targeted ingest of specific titles/seasons/episodes, use `retrovue container ingest <container_id> [--title ... --season ... --episode ...]` (during rollout, `retrovue collection ingest <collection_id>` may be accepted as deprecated).
- **SINGLE TRANSACTION**: The entire source ingest operation MUST be wrapped in a single Unit of Work, ensuring atomicity across all containers

**Requirements:**

- The command MUST require either a source ID or exact source name
- Named lookup MUST support both human and machine workflows
- The command MUST iterate over all containers where `sync_enabled=true` AND `ingestible=true` for the specified source

---

## Safety Expectations

- The command MUST refuse to run against a source that has no containers where `sync_enabled=true` AND `ingestible=true`
- The command MUST verify that the source exists and is accessible before attempting container iteration
- **CONTAINER-LEVEL NARROWING FORBIDDEN**: If any container-level narrowing flags (`--title`, `--season`, `--episode`) are provided, the CLI MUST refuse to run, exit with code 1, and emit a human-readable error directing the operator to use `retrovue container ingest` (or deprecated `retrovue collection ingest` during rollout)
- If `--dry-run` is provided, the command MUST NOT make any database or persistent state changes, but MUST show what _would_ be ingested across all containers
- If `--test-db` is provided, the command MUST operate solely on an isolated, non-production database
- Partial or failed ingest operations across containers MUST NOT result in orphaned or incomplete database records
- **SINGLE TRANSACTION BOUNDARY**: The entire source ingest operation MUST be wrapped in a single Unit of Work. If any container ingest fails fatally, the entire source ingest operation MUST be rolled back. Non-fatal container ingest failures (e.g., individual asset processing errors) MUST be logged but MUST NOT abort the entire operation.
- Source type MUST be valid and support the ingest operation. Unsupported source types MUST cause the command to fail with exit code 1.
- Source MUST support asset enumeration for content discovery

---

## Output Format

### Human-Readable Output

- Source identification and summary
- Total number of eligible containers found (`sync_enabled=true` AND `ingestible=true`)
- Per-container ingest results:
  - Container name and status
  - Assets discovered, ingested, skipped, updated per container
  - Last ingest time per container
- Overall summary with total counts across all containers:
  - Total assets discovered, ingested, skipped, updated
  - Total duplicates prevented
  - Overall last ingest time
- Summary line with clear status: `Success`, `Partial Success`, `Error: No eligible containers`, etc.
- EXAMPLE: Source ingest complete: 4 containers processed, 1,250 assets discovered (800 ingested, 400 skipped, 50 updated)

### JSON Output (if `--json` is provided)

- Top-level deterministic keys:
  - `"status"`: `"success"` | `"partial"` | `"error"`
  - `"source"`: Source identification object
  - `"collections_processed"` (or `containers_processed` when canonical): Number of containers processed. *Compatibility:* key name may remain during rollout.
  - `"stats"`: Aggregated statistics object:
    - `"assets_discovered"`: Total assets discovered across all containers
    - `"assets_ingested"`: Total assets ingested across all containers
    - `"assets_skipped"`: Total assets skipped across all containers
    - `"assets_updated"`: Total assets updated across all containers
    - `"duplicates_prevented"`: Total duplicates prevented across all containers
  - `"last_ingest_time"`: Overall last ingest time (ISO format)
  - `"collection_results"` (or `container_results` when canonical): [array of per-container result objects matching Container Ingest format]. *Compatibility:* key name may remain during rollout.
  - `"errors"`: [array of error objects/messages]
- Must include all the information from the human-readable output in a machine-consumable way.

#### Verification (only when `--verify` is provided)

When `--verify` is passed, additional verification fields are included to aid troubleshooting:

- Top-level:
  - `"verification"`: `{ "requested": <int>, "found": <int>, "ok": <bool> }`
    - `requested`: number of created Asset UUIDs reported by per-collection results
    - `found`: count of those UUIDs present in the database using the same session
    - `ok`: `true` when `found == requested`

- Per-collection (each entry in `collection_results[]`):
  - `"verification"`: `{ "collection_count": <int>, "created_found": <int> }`
    - `collection_count`: total `assets` rows for that collection UUID at verification time
    - `created_found`: how many of that entry's `created_assets[].uuid` exist in the database

Notes:
- Verification fields appear only with `--verify` and only in JSON output. They do not alter
  normal output shape or exit codes.
- Verification queries run in the same transaction/session as ingest to avoid read-your-writes
  visibility issues.

---

## Exit Codes

- `0` — Success; all containers ingested successfully or (if `--dry-run`) actions listed with no errors.
- `1` — Validation failure (e.g., source not found, no enabled containers, mapping invalid).
- `2` — Partial success; some containers succeeded, some failed.
- `3` — External system unreachable (source location cannot be accessed).
- All non-zero exit codes MUST be accompanied by a clear error message in both human and JSON output.

---

## Data Effects

- **SINGLE TRANSACTION BOUNDARY**: The entire source ingest operation MUST be wrapped in a single Unit of Work, ensuring atomicity across all containers. If any container ingest fails fatally, the entire source ingest operation MUST be rolled back.
- For each eligible container (`sync_enabled=true` AND `ingestible=true`), the ingest process follows the exact same rules as defined in the [Container Ingest](ContainerIngestContract.md).
- New Assets follow the canonical lifecycle: all assets are created with `state='new'` and `approved_for_broadcast=False`. Confidence scoring is informational only and MUST NOT drive lifecycle or approval decisions. Promotion to `ready` occurs only through `enrich_asset()` after enrichment completes. Approval requires explicit operator action (INV-ASSET-APPROVAL-OPERATOR-ONLY-001).
- Duplicate detection logic MUST prevent the creation of duplicate Asset records within each collection, following the Collection Ingest contract rules.
- Any enrichment hooks MAY run during ingest per collection, following the same per-asset failure handling.
- Assets created by this operation MUST NOT be marked as approved for broadcast automatically.
- Individual collection ingest failures (non-fatal, e.g., individual asset processing errors) MUST be logged but MUST NOT abort the entire source ingest operation.
- The source ingest operation MUST aggregate and report statistics from all container ingests, including total assets discovered, ingested, skipped, updated, and duplicates prevented.
- The source ingest operation MUST report the overall last ingest time (the latest `last_ingest_time` across all successfully processed containers).

---

## Behavior Contract

#### Behavior Contract Rules (B-#)

- **B-1:** The command MUST accept `<source_id>` as any of: full UUID, external ID (e.g. Plex server key), or case-insensitive display name. Source name matching MUST be case-insensitive. If multiple sources match the provided name (case-insensitive), the command MUST exit with code 1 and emit: "Multiple sources named '<name>' exist. Please specify the UUID." Resolution MUST NOT prefer one source over another, even if one has exact casing match.
- **B-2:** The command MUST iterate ingest across all containers belonging to `<source_id>` that are both `sync_enabled=true` AND `ingestible=true`.
- **B-3:** The command MUST NOT accept or forward any of the container-level narrowing flags: `--title`, `--season`, `--episode`.
- **B-4:** If any container-level narrowing flags (`--title`, `--season`, `--episode`) are provided, the CLI MUST refuse to run, exit with code 1, and emit the error message: "Per-title/season/episode ingest is only supported at the container level. Use: retrovue container ingest <container_id> [--title ... --season ... --episode ...]" (during rollout, `retrovue collection ingest <collection_id>` may be mentioned as deprecated).
- **B-5:** Source ingest MUST clearly summarize, in human-readable output and in `--json` mode, which containers were targeted and which were skipped (and why). Partial failures are allowed and MUST produce exit code 2.
- **B-6:** When run with `--dry-run`, the command MUST enumerate what would be ingested for each eligible container but MUST NOT call actual ingest routines that mutate data.
- **B-7:** Output with `--json` MUST include `"status": "success" | "partial" | "error"` and explicit per-container results matching Container Ingest format.
- **B-8:** When run with `--test-db`, no changes may affect production or staging databases.
- **B-9:** When both `--dry-run` and `--test-db` are provided, `--dry-run` takes precedence. The command MUST NOT write to any database (neither production nor test), but MUST still use the test DB context for resolution and validation.
- **B-10:** **SINGLE TRANSACTION BOUNDARY**: The entire source ingest operation MUST be wrapped in a single Unit of Work. If any container ingest fails fatally, the entire source ingest operation MUST be rolled back. Non-fatal container ingest failures (e.g., individual asset processing errors) MUST be logged but MUST NOT abort the entire operation.
- **B-11:** For each eligible container, the system MUST verify the container is ingestible BEFORE processing. If the container is not ingestible, it MUST be skipped and logged.
- **B-12:** Source type MUST be valid and support ingest operations. Unsupported source types MUST cause the command to fail with exit code 1.
- **B-13:** Source and container validity MUST be verified before ingest attempt.
- **B-14:** The command MUST aggregate statistics from all container ingests and report totals for assets discovered, ingested, skipped, updated, and duplicates prevented.
- **B-15:** The command MUST report the overall last ingest time (the latest `last_ingest_time` across all successfully processed containers).

---

### Data Contract

#### Data Contract Rules (D-#)

- **D-1:** **SINGLE TRANSACTION BOUNDARY**: The entire source ingest operation MUST be wrapped in a single Unit of Work, following Unit of Work principles. If a fatal error occurs before successful completion, no assets, relationships, or side effects from any container ingest may persist.
- **D-2:** Source ingest MUST only process containers where `sync_enabled=true` AND `ingestible=true`. Containers that do not meet both criteria MUST be skipped and logged.
- **D-3:** For each eligible container, the system MUST verify the container is ingestible BEFORE processing. If the container is not ingestible, it MUST be skipped and logged.
- **D-4:** Source ingest MUST invoke the same underlying ingestion pipeline that container ingest uses for full container scope (no `--title`/`--season`/`--episode`), but MUST call it in full container scope only.
- **D-5:** All ingest operations triggered under source ingest MUST be tracked individually per container in ingest logs/audit trails, distinguishing between bulk source ingest and manual surgical ingest.
- **D-6:** Duplicate detection logic MUST prevent the creation of duplicate Asset records within each container, following the Container Ingest contract rules.
- **D-7:** Every new Asset MUST begin in lifecycle state `new` and MUST NOT be in `ready` state at creation time. If enrichers are attached to the container, assets MAY transition through `enriching` state during active enrichment processing, but MUST NOT remain in `enriching` state after enrichment completes.
- **D-8:** Source type validity MUST be verified before ingest attempt.
- **D-9:** Asset discovery MUST retrieve all assets belonging to the container. Discovery MUST return normalized asset data and MUST NOT perform any database writes.
- **D-10:** Asset discovery and database persistence are separate operations. All database persistence (Asset creation, updates, container state updates) MUST occur within Unit of Work transaction boundaries.
- **D-11:** The `ingestible` field MUST be verified for each container before ingesting.
- **D-12:** If `ingestible=false`, the container MUST NOT be included in bulk ingest operations, even if `sync_enabled=true`.
- **D-13:** All operations run with `--test-db` MUST be isolated from production database storage, tables, and triggers.
- **D-14:** When both `--dry-run` and `--test-db` are provided, `--dry-run` takes precedence. The command MUST NOT write to any database (neither production nor test), but MUST still use the test DB context for resolution and validation.
- **D-15:** Source-level ingest MUST NOT create any source-level database records; all persistence occurs at the container level.
- **D-16:** The source ingest operation MUST aggregate and report statistics from all container ingests, including total assets discovered, ingested, skipped, updated, and duplicates prevented.
- **D-17:** The source ingest operation MUST report the overall last ingest time (the latest `last_ingest_time` across all successfully processed containers).

---

## Test Coverage Mapping

- **B-1..B-15** → `test_source_ingest_contract.py`
- **D-1..D-17** → `test_source_ingest_data_contract.py`
- **D-9, D-10** → `test_source_ingest_data_contract.py` (importer/service separation)

Each rule above MUST have explicit test coverage in its respective test file, following the contract test responsibilities in [README.md](./README.md).  
Each test file MUST reference these rule IDs in docstrings or comments to provide bidirectional traceability.

Future related tests (integration or scenario-level) MAY reference these same rule IDs for coverage mapping but must not redefine behavior.

---

## Examples

### Valid Source Ingest Operations

```bash
# Ingest all enabled collections from a source
retrovue source ingest "My Plex Server"

# Ingest with JSON output
retrovue source ingest "My Plex Server" --json

# Dry-run source ingest
retrovue source ingest "My Plex Server" --dry-run

# Test source ingest
retrovue source ingest "My Plex Server" --test-db --dry-run
```

### Forbidden Operations (Will Fail)

```bash
# FORBIDDEN: Container-level narrowing flags
retrovue source ingest "My Plex Server" --title "The Big Bang Theory"
# Error: Per-title/season/episode ingest is only supported at the container level.
# Use: retrovue container ingest <container_id> [--title ... --season ... --episode ...]

# FORBIDDEN: Season flag
retrovue source ingest "My Plex Server" --season 1
# Error: Per-title/season/episode ingest is only supported at the container level.

# FORBIDDEN: Episode flag
retrovue source ingest "My Plex Server" --episode 6
# Error: Per-title/season/episode ingest is only supported at the container level.
```

### Correct Surgical Operations

```bash
# For targeted ingest, use collection ingest instead
retrovue container ingest "TV Shows" --title "The Big Bang Theory"
retrovue container ingest "TV Shows" --title "The Big Bang Theory" --season 1
retrovue container ingest "TV Shows" --title "The Big Bang Theory" --season 1 --episode 6
```

---

## Relationship to Collection Ingest

This Source Ingest builds upon and orchestrates the Collection Ingest:

- **Iteration**: Source ingest iterates across all eligible collections (`sync_enabled=true` AND `ingestible=true`), similar to Source Discover
- **Unit of Work**: The entire source ingest operation is wrapped in a single Unit of Work, ensuring atomicity across all collections
- **Atomicity**: All collection ingests occur within the same transaction boundary. If any collection ingest fails fatally, the entire source ingest operation is rolled back
- **Error Handling**: Fatal collection ingest failures abort the entire operation; non-fatal failures (e.g., individual asset processing errors) are logged but don't abort
- **Aggregation**: Source ingest aggregates results from multiple collection ingests into a unified output with total statistics
- **Safety**: Source ingest maintains the same safety guarantees as collection ingest, applied across all collections atomically
- **Validation**: Source ingest enforces the same validation order as collection ingest: collection resolution → prerequisite validation → scope resolution

All collection-level behavior, safety expectations, and data effects are inherited from the Collection Ingest and MUST be enforced for each collection processed by the source ingest operation.

---

## Examples

### Basic Source Ingest

```bash
# Ingest all enabled collections from a source
retrovue source ingest "My Plex Server"

# Ingest by source ID
retrovue source ingest plex-5063d926

# Ingest with JSON output
retrovue source ingest "My Plex Server" --json
```

### Dry-run Testing

```bash
# Preview ingest across all collections
retrovue source ingest "My Plex Server" --dry-run

# Test ingest logic
retrovue source ingest "Test Source" --test-db --dry-run
```

### Test Environment Usage

```bash
# Test source ingest in isolated environment
retrovue source ingest "Test Plex Server" --test-db
```

---

## Safety Guidelines

- Always use `--test-db` for testing source ingest logic
- Use `--dry-run` to preview ingest actions across all collections
- Verify source configuration and enabled collections before ingest
- Monitor per-collection results for partial failures
- Confirm source identification before ingest

---

## See Also

- [Unit of Work](../_ops/UnitOfWorkContract.md) - Transaction management requirements for atomic operations
- [Source Discover](SourceDiscoverContract.md) - Iterative collection discovery operations
- [Container Ingest](ContainerIngestContract.md) - Individual collection ingest operations
