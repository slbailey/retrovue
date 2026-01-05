# Contract — Collection Ingest

## Purpose

Defines the behavioral rules for `retrovue collection ingest` including discovery, validation, enrichment, and persistence effects.

This contract explicitly specifies how URIs are persisted during ingest:
- `source_uri`: Source-native locator provided by the importer (e.g., `plex://12345`).
- `canonical_uri`: Locally-resolvable native filesystem path derived during ingest via importer path
  resolution and `PathMapping` (e.g., `R:\media\tv\...` on Windows, `/mnt/media/...` on Linux).

## Commands

- `retrovue collection ingest <selector> [--title <t>] [--season <n>] [--episode <n>] [--dry-run] [--json] [--verbose-assets]`

## Preconditions

- Collection exists and is ingestible.
- For full ingest (no title/season/episode filters), `sync_enabled=true`.

## Behavior

1) Discovery
- Importer is invoked to discover items (supports scoped discovery when filters provided).
- Importer returns items with a stable `source_uri` (native to the source) and provider metadata.

2) URI Resolution
- Ingest calls `importer.resolve_local_uri(item, *, collection, path_mappings)` to obtain a local `file://` URI for enrichment.
- The resolved local URI is used transiently for enrichment only.

3) Persistence
- Collection ingest MAY ONLY create new `Asset` rows. It MUST NOT mutate existing assets.
- New `Asset` rows include:
  - `source_uri`: persisted verbatim from the importer (unique per `(collection_uuid, source_uri)`).
  - `canonical_uri`: persisted from the resolved local path (native OS path; not `file://`).
  - Canonical identity: `canonical_key` and `canonical_key_hash` are derived from canonical path + collection.
  - `hash_sha256`: computed natively by ingest at create-time when the local file is reachable; otherwise left null.
  - Initial lifecycle state and approval decided by confidence scoring (see 5) Confidence & Auto-State).

4) Enrichment
- Attached ingest-scope enrichers run in priority order.
- Enricher outputs update technical fields (e.g., `duration_ms`, `video_codec`, `audio_codec`, `container`).
  Hash computation is not an enricher responsibility.
- A stable `last_enricher_checksum` is stored for change detection.
- Enricher dependency errors (e.g., FFprobe not installed) MUST be surfaced as readable messages in `stats.errors`. Ingest continues for other items without crashing.

5) Updates vs Creates
- If `(collection_uuid, canonical_key_hash)` matches an existing asset: collection ingest MUST SKIP without updating.
- Asset modifications (content/enricher/approval) are handled by a separate `asset update` command (pending).

6) Failure Modes
- If importer cannot resolve a local URI for an ingestible collection, ingest fails with a validation error referencing `PathMapping`.
- Importer/network errors are returned with appropriate exit code and surfaced in `--json` mode.

7) Confidence Scoring & Auto-State
- The ingest service MUST compute a confidence score in [0.0, 1.0] using deterministic signals from normalized metadata and basic media probes.
- Default thresholds:
  - `auto_ready_threshold = 0.80`
  - `review_threshold = 0.50`
- New asset creation rules:
  - If score ≥ `auto_ready_threshold`: create with `state=ready` and `approved_for_broadcast=true`.
  - If `review_threshold` ≤ score < `auto_ready_threshold`: create with `state=new` and `approved_for_broadcast=false`.
  - If score < `review_threshold`: create with `state=new`, `approved_for_broadcast=false`, and mark for operator attention.
- Thresholds MAY be overridden per-run via CLI flags and/or configuration, but MUST be reported in output.
- For existing assets matched as unchanged, no state/approval changes are made. For changed assets, see Asset ingest update rules in the Asset Confidence contract.

### Metadata handling (NEW)

B-20. For each discovered item, the ingest orchestration MUST construct an ingest payload containing:

- importer_name
- asset_type (best-effort, may fall back to ingest scope)
- source_uri (as discovered, before local resolution)
- editorial (if present on the item)
- probed (if present on the item)
- sidecar(s) (if present on the item or produced by an enricher)

B-21. The ingest orchestration MUST pass the payload to the unified metadata handler
`retrovue.usecases.metadata_handler.handle_ingest(...)` **before** creating the `Asset` record.

B-22. The handler’s output is authoritative for per-domain metadata. The orchestration MUST persist any
returned domains to their dedicated tables:

- `asset_editorial(payload jsonb)`
- `asset_probed(payload jsonb)`
- `asset_station_ops(payload jsonb)`
- `asset_relationships(payload jsonb)`
- `asset_sidecar(payload jsonb)`

B-23. Each metadata table MUST have an `asset_uuid` FK → `asset.uuid` with `ON DELETE CASCADE`. Deleting
the asset MUST delete the attached metadata rows.

B-24. Dry-run (`--dry-run`) MUST execute the full metadata handler and produce fully resolved metadata
in the CLI output, but MUST NOT commit the `asset` row nor any of the metadata tables (entire transaction
is rolled back).

## Output

### Human
- Prints scope and summary stats (discovered/ingested/skipped/updated), with confidence outcome
  summaries: auto-ready, needs-enrichment, needs-review.

### JSON (`--json`)
- Returns an object with `status`, `scope`, `collection_id`, `collection_name`, `stats`, `thresholds`, and optional `last_ingest_time`.
- `stats` MUST include deterministic keys:
  - `assets_discovered`, `assets_ingested`, `assets_skipped`, `assets_updated`, `duplicates_prevented`
  - `assets_auto_ready`, `assets_needs_enrichment`, `assets_needs_review`
- `thresholds` MUST include: `{ "auto_ready": float, "review": float }`
- When `--verbose-assets` is provided:
  - `created_assets[]` SHOULD include `uuid`, `source_uri`, `canonical_uri`, `state`, `approved_for_broadcast`, and `confidence`.
  - `updated_assets[]` SHOULD include `uuid` and reason for update when applicable.

## Safety
- `--dry-run` must execute discovery and enrichment preparation without any DB writes.
- Transactions are atomic; partial writes are rolled back on error.
- `state=enriching` is reserved for periods when enrichment is actively running; ingest must not
  set `enriching` at creation time.
 - Full-file content hashing (e.g., SHA-256 over entire media files) MUST NOT be performed
   during ingest. Change detection MUST rely on lightweight signals (e.g., size, mtime,
   probe signatures) or importer-provided versioning. Heavy hashing MAY be done offline in
   maintenance workflows, but it is out of scope for ingest.

## Lifecycle Notes
- This file updates prior guidance that "new assets MUST NOT be in ready state at creation".
  With confidence scoring active, creation in `ready` with `approved_for_broadcast=true` is allowed
  when score ≥ `auto_ready_threshold`.

## Notes
- This contract supersedes prior ambiguity about `uri` by explicitly separating `source_uri` and `canonical_uri` and assigning importer vs ingest responsibilities.
- Asset mutation is deferred to an upcoming `asset update` command (pending); ingest is create-only.
