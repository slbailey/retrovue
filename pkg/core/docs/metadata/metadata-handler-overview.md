### Metadata Handler – Technical Design Overview (v0.1)

Last updated: 2025-11-02

This document outlines the upcoming Metadata Handler service that standardizes ingestion,
normalization, enrichment, and persistence of RetroVue metadata.

Related docs:
- Taxonomy: `docs/metadata/metadata-taxonomy.md`
- Sources & resolution: `docs/metadata/metadata-sources.md`
- Enrichment: `docs/metadata/metadata-enrichment.md`
- URI schema: `docs/metadata/asset-uri-schema.md`

---

### Responsibilities

- Normalization & Validation
  - Apply per-field normalization rules (types, trimming, enums, dates) and validate against the
    taxonomy. Reject or drop invalid values; never coerce lossy types without rules.
  - Sidecar validation:
    - If a sidecar is present, validate it against `docs/metadata/sidecar-schema.json`.
    - On validation failure, reject ingest with HTTP 400 or route to quarantine (configurable).
    - On success, normalize and pass the sidecar payload into source resolution.
- Source Resolution & Priority
  - Resolve conflicting values across sources using the global strategy (Manual/Sidecar > Platform
    > Embedded > Filename > AI; `Probe` for technical fields). Merge arrays with de-duplication.
- Canonicalization & Dedupe
  - Build `canonical_key` using shared canonical logic; detect and reconcile duplicates across
    importers without destructive updates. Maintain provenance.
- Enrichment Orchestration
  - Trigger configured enrichers (`ai_summary`, `genre_classifier`, etc.), record events, and
    populate `ai_*` fields according to priority rules.
- URI Handling
  - Persist `source_uri` from importer.
  - Resolve and persist `canonical_uri` as a native filesystem path (not `file://`).
  - Use runtime mappers (`PathMapping`, Importer adapters) only for resolution during ingest.
- Persistence
  - Upsert entity rows (`Series`, `Episode`, `Movie`, etc.) and `Asset` with resolved + enriched
    fields. Append `enrichment_event` records. Avoid committing outside the UnitOfWork boundary.
- Idempotency & Observability
  - Ensure deterministic outcomes per input hash; emit structured logs/metrics; capture provenance
    and versions for auditability.

Out of scope (initial)
- Media transcoding, artwork generation, or direct file moves. The handler only orchestrates
  metadata; media operations are separate services.

---

### What Is a Sidecar?

A sidecar is a structured JSON document that follows the RetroVue Sidecar Schema and is understood end‑to‑end by the Metadata Handler. It is identified by:
- `asset_type`: one of `episode`, `movie`, `promo`, `bumper`, `ad`, `block`
- `_meta`: includes `schema = retrovue.sidecar`, semantic `version`, and `scope` (`file` | `series` | `collection`)
- Optional `relationships` (e.g., `series_id`, `promoted_asset_id`) and `station_ops` (operational tags)

Sidecars are one of several metadata sources the handler accepts and merges. They differ from:
- Editorial: loosely structured fields from importers or filename parsing (e.g., `title`, `season_number`)
- Probed: technical measurements (ffprobe) that always win for technical fields
- AI/Enrichment: derived fields like `ai_summary`, `ai_genres` that can backfill missing editorial

Any chunk of metadata that conforms to the Sidecar Schema—no matter whether it came from a file on disk, an importer API, or an enrichment process—can be treated as a sidecar by the handler.

Inputs the handler merges (illustrative):
- Sidecars (one or more, merged by scope: collection → series → file)
- Editorial (importer/platform/tags/filename)
- Probed (ffprobe; authoritative for technical)
- AI/Enrichment (optional backfill where allowed)

Example (filesystem importer):
- Filesystem provides: `editorial` + `probed` + file‑scoped sidecar
- Handler validates sidecar against `docs/metadata/sidecar-schema.json`, merges with series/collection sidecars when present, resolves sources, applies enrichment, and persists the final Asset and entity rows.

Summary: Not every metadata blob is a sidecar, but every sidecar is a metadata blob the handler understands.

---

### Interfaces

Input contract (from Importers)
- Transport: internal call (Python API) or HTTP POST to the handler (FastAPI) depending on runtime.
- Schema (simplified):
```json
{
  "importer_name": "plex",
  "importer": "filesystem",            // alias accepted; prefer importer_name
  "asset_type": "episode",
  "source_uri": "file:///mnt/media/Show/S01E02.mkv",
  "source_payload": { /* raw platform JSON when available */ },

  // Editorial fields gleaned from platform/tags/filename
  "editorial": {
    "title": "Retro Hour",
    "season_number": 1,
    "episode_number": 2,
    "description": "Part two of the pilot.",
    "genres": ["comedy"]
  },

  // Media probe (ffprobe) results – probe wins for technical fields
  "probed": {
    "runtime_seconds": 1487,
    "resolution": "480p",
    "aspect_ratio": "4:3",
    "audio_channels": 2,
    "audio_format": "stereo",
    "video_codec": "h264",
    "container": "matroska"
  },

  // Sidecar per docs/metadata/sidecar-spec.md (first-class citizen)
  "sidecar": {
    "asset_type": "episode",
    "title": "Pilot (Part 2)",
    "season_number": 1,
    "episode_number": 2,
    "relationships": { "series_id": "b1c2c1b2-aaaa-bbbb-cccc-ddee88990011" },
    "_meta": {
      "schema": "retrovue.sidecar",
      "version": "0.1.0",
      "scope": "file",
      "authoritative_fields": ["title", "genres"]
    }
  },

  // Optional operations extension (see scheduling-tags.md)
  "station_ops": {
    "content_class": "cartoon",
    "daypart_profile": "after_school",
    "ad_avail_model": "kids_30"
  }
}
```

Notes
- `probed` supersedes the earlier `technical` example; handlers may continue to accept `technical`
  as a backward-compatible alias that is normalized to `probed` internally.
- `source_uri` MUST be importer-native (e.g., `plex://...`). Filesystem-style URIs are handled by
  the runtime resolver and should not appear in the ingest payload.
 - Sidecar validation uses a centralized loader/validator (`retrovue.infra.metadata.schema_loader`)
   against `docs/metadata/sidecar-schema.json` to keep code and docs in sync.

### Sidecar discovery

- Importers MAY submit multiple sidecars via a `sidecars: []` array in the ingest payload.
- If multiple sidecars are present, the handler merges them in the order: `file` → `series` →
  `collection`, per `docs/metadata/sidecar-spec.md`. Authoritative fields apply within their
  declared scope.
- If only a single sidecar is present, the handler trusts its declared `_meta.scope`.

Output contract (summary)
- See the authoritative service contract in `docs/contracts/resources/MetadataHandlerContract.md` for input/output shapes.
  The handler returns a `canonical_uri` using a native filesystem path, and merged domains under
  `editorial`, `probed`, optional `station_ops` and `relationships`, plus the final validated `sidecar`.

Integration points
- Importers: call `POST /metadata/ingest` or Python API `handle_ingest(payload)`.
- Database: SQLAlchemy 2.x UnitOfWork; write to `Asset`, entity tables, `enrichment_event`, use
  `Importer` and `PathMapping` for resolution services.
- Enrichment engines: internal strategy interface for model-backed and rule-based enrichers.
- Runtime resolver: separate playout resolver consumes `canonical_uri` at playback time.

---

### Component structure

Logical modules
- `normalization`
  - Field mappers and validators implementing `metadata-sources.md` rules.
- `resolution`
  - Source priority resolver, array merge, external ID sanitization.
- `canonicalization`
  - Canonical key builder and dedupe matcher (imports `infra/canonical.py`).
- `uri`
  - `source_uri` validators per scheme; `canonical_uri` constructor; adapters for test resolution.
- `enrichment`
  - Orchestrator, enricher registry, result normalization, event logging.
- `persistence`
  - UnitOfWork-aware upsert of entity + `Asset`; append-only `enrichment_event` writer.
- `api`
  - FastAPI endpoints (if deployed as a service); Pydantic request/response schemas.

Suggested FastAPI endpoints
- `POST /metadata/ingest` – Accept importer payload, run normalize + enrich, persist, return summary
- `POST /metadata/enrich/{asset_id}` – Re-run enrichment for an asset
- `POST /metadata/resolve/{asset_id}` – Attempt re-resolution of playout targets (uri adapters)
- `GET /metadata/{asset_id}` – Retrieve resolved + enriched view and provenance pointers

Key classes (illustrative)
- `MetadataHandler` – Facade coordinating normalization, canonicalization, enrichment, persistence
- `FieldNormalizer` – Stateless utilities per field/type
- `SourceResolver` – Applies priority rules and merges arrays
- `CanonicalIdService` – Computes `canonical_key` and finds existing matches
- `UriService` – Validates `source_uri`, composes `canonical_uri`
- `EnrichmentOrchestrator` – Runs enrichers, emits `enrichment_event`, updates `ai_*`
- `Repository` (scoped) – UoW-backed writers for `Asset`, entities, `enrichment_event`

---

### URI persistence rules

- On ingest: always persist `source_uri` exactly as sent.
- On ingest: resolve and persist `canonical_uri` as a native path (not `file://`).
- On ingest: record `path_mapping_version` (even if null).
- On re-resolve: update routing, not the canonical string.

This prevents regressions where a `file://` locator is written back to the DB. The canonical URI is
the native filesystem path derived at ingest time.

---

### Example flow – Plex episode to stored records

Scenario
- Importer: Plex; asset type: `episode` for Series "Retro Hour", S01E02.

Steps
1) Receive input
   - `source_uri = plex://library/metadata/12345`
   - Editorial: title/description/genres; Technical: duration/resolution/aspect

2) Normalize & validate
   - Trim/canonicalize fields, ensure `season_number` and `episode_number` integers, `aspect_ratio`
     simplified to `4:3`, `runtime_seconds` rounded to nearest second.

3) Resolve sources (priority rules)
   - Prefer sidecar/manual (if present), then Plex, then tags/filename; keep Probe values for
     technical fields.

4) Canonicalization & dedupe
   - Build `canonical_key = series:retro-hour|s01e02`; search for an existing `Asset`.
   - If found, update in-place and downgrade state as per ingest rules; else create new.

5) Persist Series/Episode + Asset
   - Upsert `Series` (by normalized title or external IDs) and link via `series_id`.
   - Insert/Update `Episode` with resolved fields.
   - Insert/Update `Asset` with `source_uri`, `canonical_uri` as a native filesystem path,
     `file_sha256` (if available), and resolved/editorial fields.

6) Enrichment orchestration
   - Run `ai_summary`, `keyword_extractor`, `genre_classifier`.
   - Normalize outputs into `ai_*` columns; write `enrichment_event` rows with versions/provenance.
   - Apply backfill policy if `genres` empty → set from `ai_genres`.

7) Return response
   - Includes `asset_id`, `canonical_uri`, resolved fields delta, and `enriched_fields` snapshot.

Sequence (condensed)
```
Importer → [POST /metadata/ingest]
  → Normalization → Source Resolution → Canonicalization/Dedupe
  → Persist Series/Episode/Asset → Enrichment → Enrichment events
  → Response { asset_id, canonical_uri, resolved + enriched }
```

Observability
- Log per step with correlation id; metrics for durations, enrichment success rate, and dedupe hits.
- Store `input_hash` to ensure idempotency for replays.

Failure handling
- Validation errors: return 400 with field errors (API) or raise typed exceptions (internal API);
  do not persist partial rows unless configured for quarantine.
- Enrichment failures: do not block persistence; record failed event with error details.


