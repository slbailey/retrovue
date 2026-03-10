# Interstitial Enrichment — Canonical Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`, `LAW-DERIVATION`

---

## Overview

Interstitial enrichment governs how interstitial media assets (commercials, promos, bumpers, station IDs, trailers, teasers, shortform, PSAs, filler) are discovered from the filesystem, classified with canonical metadata, and made eligible for traffic selection and playout.

This contract is the sole authority for the pipeline from filesystem discovery through editorial metadata stamping to traffic eligibility. It defines required outcomes at each stage. It does not govern break placement, break structure expansion, or traffic policy evaluation — those concerns are owned by `break_detection.md`, `break_structure.md`, and `traffic_policy.md` respectively.

### Scope

This contract governs:
- Filesystem discovery of interstitial media files
- Collection enumeration from directory structure
- Metadata inference from directory hierarchy
- Canonical interstitial type determination
- Editorial metadata requirements for traffic eligibility
- State transitions from discovery to playout readiness

This contract does NOT govern:
- Break opportunity identification or placement
- Break slot ordering or budget allocation
- Traffic policy evaluation (cooldown, caps, rotation)
- Bumper or station ID selection mechanics
- Channel YAML traffic profile declarations

### Related Contracts

- `INV-INTERSTITIAL-TYPE-STAMP-001` — Canonical type stamping invariant (this contract subsumes and extends)
- `traffic_policy.md` — Runtime candidate evaluation
- `break_structure.md` — Break slot expansion
- `traffic_manager.md` — Break filling orchestration
- `traffic_dsl.md` — Channel YAML traffic configuration

---

## Terminology

### Interstitial Asset

A media file intended for placement within commercial breaks. Interstitial assets are classified by canonical type and are distinct from program content (episodes, movies).

### Canonical Interstitial Type

One of exactly nine recognized type values. Every interstitial asset MUST carry one of these as `editorial.interstitial_type`:

| Type | Description |
|------|-------------|
| `commercial` | Paid advertising spot |
| `promo` | Network/channel promotional content |
| `psa` | Public service announcement |
| `bumper` | Short transition element |
| `station_id` | Station identification |
| `trailer` | Movie or show trailer |
| `teaser` | Short teaser/preview |
| `shortform` | Short-form interstitial content |
| `filler` | Generic fill material |

### Collection

A first-level subdirectory under a configured root path. Collections are the organizational unit for interstitial media on disk.

### Collection Type Map

The authoritative mapping from collection directory name to canonical interstitial type:

| Collection Name | Canonical Type |
|-----------------|---------------|
| `bumpers` | `bumper` |
| `commercials` | `commercial` |
| `promos` | `promo` |
| `psas` | `psa` |
| `station_ids` | `station_id` |
| `trailers` | `trailer` |
| `teasers` | `teaser` |
| `shortform` | `shortform` |
| `oddities` | `filler` |

### Inference Rules

Directory-name-to-tag mappings applied during file discovery. Two rule sets exist: type rules (directory name → interstitial type) and category rules (directory name → business category). Inference rules provide initial metadata; the collection type map is authoritative and overrides file-level inference.

---

## Inputs

### Filesystem Media Roots

One or more local directory paths configured as root paths for discovery. Each root path MUST exist and MUST be a directory.

### Collection Structure

Immediate subdirectories of each root path. Discovery MUST enumerate only the first level of subdirectories. Files at the top level of a root path are not collections.

### Directory Hierarchy

The directory ancestry between a root path and each discovered media file. Directory names within this hierarchy are the source material for metadata inference.

### Sidecar Files

Optional JSON or YAML files adjacent to media files, with extensions `.retrovue.json`, `.json`, `.yaml`, or `.yml` appended after the media file extension. Sidecar content is attached to the discovered item when present.

### Glob Patterns

File matching patterns that determine which files are discovered. Default patterns match ten video extensions: `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.3gp`, `.ogv`.

---

## Required Outcomes

### Discovery

**D-1.** Discovery MUST scan all configured root paths recursively using configured glob patterns.

**D-2.** Discovery MUST exclude files that are directories, do not exist, are not regular files, or have any path component starting with `.` (unless `include_hidden` is true).

**D-3.** Each discovered file MUST produce a `DiscoveredItem` with a `file://` URI, a provider key equal to the file path, and editorial metadata containing at minimum `title`, `size`, and `modified`.

**D-4.** If a sidecar file exists adjacent to a media file, its contents MUST be attached to the discovered item. If loading fails, the sidecar MUST be silently ignored and discovery MUST continue.

### Collection Enumeration

**C-1.** Collection discovery MUST enumerate only immediate subdirectories of each root path. It MUST NOT recurse beyond the first level.

**C-2.** Hidden directories (names starting with `.`) MUST be excluded unless `include_hidden` is true.

**C-3.** Each collection MUST receive a stable `external_id` derived from the SHA-256 hash of the subdirectory's resolved absolute path (first 16 hex characters).

### Metadata Inference

**M-1.** When `tag_from_path_segments` is false (default), the importer MUST walk directory ancestors from the file's parent upward to the configured root (exclusive) and apply inference rules. Matching is case-insensitive. The deepest (most specific) directory MUST take priority.

**M-2.** Type rules MUST be evaluated first-match-wins. Category rules MUST be evaluated independently, also first-match-wins.

**M-3.** When no type rule matches any ancestor directory, `interstitial_type` MUST default to `"filler"`.

**M-4.** When no category rule matches, `interstitial_category` MUST be absent from the editorial dict.

**M-5.** Inferred labels MUST be appended to `raw_labels` as structured strings: `interstitial_type:{value}` and `interstitial_category:{value}`.

**M-6.** When `tag_from_path_segments` is true, every directory component between the configured root (exclusive) and the file's parent (inclusive) MUST be emitted as a normalized `tag:{lowercase_name}` label. Deepest directory MUST appear first. Type and category inference MUST be skipped entirely.

### Canonical Type Stamping

**T-1.** The `InterstitialTypeEnricher` MUST determine canonical `interstitial_type` from the collection name using the Collection Type Map. Collection name is authoritative.

**T-2.** The enricher MUST overwrite any file-level `interstitial_type` already present in the editorial dict. Collection-level type takes precedence over inference.

**T-3.** The enricher MUST preserve all other existing editorial fields. It MUST merge, not replace.

**T-4.** `apply_enrichers_to_collection()` MUST auto-inject `InterstitialTypeEnricher` at priority -1 (before all configured enrichers) for any collection whose name is a key in the Collection Type Map.

### Unknown Collection Handling

**U-1.** If a collection name is not a key in the Collection Type Map, the `InterstitialTypeEnricher` MUST raise an error at construction time. There MUST be no silent fallback, no default type, no best-guess behavior.

**U-2.** If `enrich()` is called and the collection name cannot be resolved to a canonical type, the enricher MUST raise an error at enrichment time.

### Eligibility for Traffic Selection

**E-1.** An asset MUST have `AssetEditorial.payload` containing the key `"interstitial_type"` to be visible to the traffic system. Assets without this key MUST be invisible to `get_filler_assets()`.

**E-2.** An asset MUST have `state='ready'` to be eligible for traffic selection.

**E-3.** An asset MUST have a non-null, positive `duration_ms` that does not exceed the requested `max_duration_ms` to be eligible for traffic selection.

**E-4.** Traffic selection MUST query by `interstitial_type` field in `AssetEditorial.payload`. It MUST NOT query by collection name, collection UUID, or any storage-layer concept.

### Auto-Promotion to Ready State

**P-1.** Auto-promotion to `"ready"` state requires a confidence score at or above the `auto_ready_threshold` (default 0.80).

**P-2.** Confidence MUST be scored as: +0.2 for `size > 0`, +0.3 for valid `duration_ms` (0 < dur ≤ 10,800,000ms), +0.2 for `video_codec` present, +0.1 for `audio_codec` present, +0.1 for `container` present. Maximum score is 1.0.

**P-3.** If `duration_ms` is missing, zero, negative, or exceeds 10,800,000ms, confidence MUST be forced to 0.0. The asset MUST NOT be auto-promoted.

**P-4.** Enrichment MUST be idempotent. The pipeline checksum (SHA-256 of the enricher signature list) MUST be compared against the asset's `last_enricher_checksum`. Assets whose checksum matches MUST be skipped.

---

## Required Metadata Outcomes

### After Discovery

Every `DiscoveredItem` MUST contain:

| Field | Source | Required |
|-------|--------|----------|
| `editorial.title` | File stem | Yes |
| `editorial.size` | File stat | Yes |
| `editorial.modified` | File stat (ISO timestamp) | Yes |
| `editorial.interstitial_type` | Inference rules (default: `"filler"`) | Yes (when inference mode active) |
| `editorial.interstitial_category` | Inference rules | No (absent when no rule matches) |

### After Enrichment

Every interstitial asset MUST contain:

| Field | Source | Authority |
|-------|--------|-----------|
| `editorial.interstitial_type` | Collection Type Map via `InterstitialTypeEnricher` | Authoritative — overrides file-level inference |

### Traffic Selection Dependencies

Traffic selection depends on exactly these fields:

| Field | Requirement |
|-------|-------------|
| `AssetEditorial.payload["interstitial_type"]` | MUST exist (JSONB key presence) |
| `Asset.state` | MUST equal `"ready"` |
| `Asset.duration_ms` | MUST be non-null, positive, and ≤ `max_duration_ms` |
| `interstitial_type` value | MUST be in the channel policy's `allowed_types` set |

---

## Invariants

### INV-INTERSTITIAL-TYPE-STAMP-001 — Collection name is authoritative for canonical type

Every interstitial asset ingested from a filesystem source MUST have `editorial.interstitial_type` set to a canonical type during ingest. The type is determined by the Collection Type Map from the collection name. File-level inference MUST NOT override the collection-level type.

### INV-INTERSTITIAL-TRAFFIC-VISIBILITY-001 — Assets without interstitial_type are invisible to traffic

`get_filler_assets()` MUST query for assets where `AssetEditorial.payload` contains the key `"interstitial_type"`. Assets lacking this key MUST NOT appear in traffic candidate lists regardless of state, collection membership, or duration.

### INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001 — Traffic layer MUST NOT reference storage topology

TrafficManager, TrafficPolicy, and DatabaseAssetLibrary MUST NOT reference collection names, collection UUIDs, source names, or filesystem paths. The `interstitial_type` field in `AssetEditorial.payload` is the sole bridge between storage topology and traffic semantics.

### INV-INTERSTITIAL-ENRICHER-INJECT-001 — Auto-injection of type enricher

`apply_enrichers_to_collection()` MUST auto-inject `InterstitialTypeEnricher` at priority -1 for collections whose name appears in the Collection Type Map. No manual enricher attachment is required for interstitial collections.

### INV-INTERSTITIAL-UNKNOWN-REJECT-001 — Unknown collections MUST be rejected

If a collection name is not in the Collection Type Map, the `InterstitialTypeEnricher` MUST raise an error. Silent fallback to any default type MUST NOT occur.

### INV-INTERSTITIAL-CONFIDENCE-DURATION-001 — Invalid duration forces zero confidence

If `duration_ms` is missing, zero, negative, or exceeds 10,800,000ms (3 hours), confidence MUST be 0.0. The asset MUST NOT be auto-promoted to ready state.

### INV-INTERSTITIAL-ENRICHMENT-IDEMPOTENT-001 — Enrichment is idempotent

Assets whose `last_enricher_checksum` matches the current pipeline checksum MUST be skipped during re-enrichment. The pipeline checksum MUST be the SHA-256 hex digest of the JSON-serialized enricher signature list.

---

## Error Handling Outcomes

### Unknown or Unmapped Collections

The enricher MUST raise `EnricherConfigurationError` at construction time for collection names not in the Collection Type Map. The enricher MUST raise `EnricherError` at enrichment time if the collection name cannot be resolved. No asset MUST be created with an incorrect or missing canonical type due to silent fallback.

### Missing Sidecars

If a sidecar file does not exist, the `sidecar` field on the discovered item MUST be `None`. If a sidecar file exists but cannot be parsed, the `sidecar` field MUST be `None`. Discovery MUST NOT fail due to missing or malformed sidecar files.

### Missing Metadata for Confidence

If any of `duration_ms`, `video_codec`, `audio_codec`, or `container` labels are absent from `raw_labels`, the confidence score MUST be reduced accordingly. Missing `duration_ms` specifically MUST force confidence to 0.0.

### Invalid Duration

Assets with `duration_ms` equal to zero, negative, or exceeding 10,800,000ms MUST receive confidence 0.0. Assets with null `duration_ms` in the database MUST be excluded from traffic candidate queries.

---

## Required Tests

### Discovery

- A file matching a configured glob pattern in a root path MUST be discovered and produce a `DiscoveredItem`.
- A file with a hidden path component MUST be excluded when `include_hidden` is false.
- A file with a hidden path component MUST be included when `include_hidden` is true.
- A non-existent root path MUST raise `ImporterError`.
- A root path that is not a directory MUST raise `ImporterError`.
- Discovery of a broken symlink MUST skip the file without error.

### Collection Enumeration

- Immediate subdirectories of a root path MUST each produce one collection entry.
- Files at the root level MUST NOT produce collection entries.
- Two different root paths containing the same subdirectory name at different absolute paths MUST produce distinct `external_id` values.
- Hidden subdirectories MUST be excluded when `include_hidden` is false.

### Metadata Inference

- A file under `root/commercials/restaurants/mcdonalds.mp4` MUST infer `interstitial_type: commercial` and `interstitial_category: restaurant`.
- A file under `root/psas/health/drink_water.mp4` MUST infer `interstitial_type: psa`.
- A file under a directory matching no inference rule MUST default `interstitial_type` to `"filler"`.
- A deeper directory matching a type rule MUST take priority over a shallower directory matching a different type rule.
- When `tag_from_path_segments` is true, each directory component between root and file parent MUST appear as `tag:{name}` in raw_labels, and no `interstitial_type` or `interstitial_category` MUST appear in editorial.

### Canonical Type Stamping

- Each collection name in the Collection Type Map MUST produce the correct canonical type after enrichment.
- The enricher MUST overwrite a pre-existing file-level `interstitial_type` in editorial.
- The enricher MUST preserve other editorial fields (e.g. `title`, `interstitial_category`).
- All nine canonical types MUST be reachable via at least one collection name in the map.

### Unknown Collection Handling

- An unmapped collection name MUST raise `EnricherConfigurationError` at enricher construction.
- An unmapped collection name MUST raise `EnricherError` at enrichment time if construction was bypassed.

### Auto-Promotion and Confidence

- An asset with `size > 0`, valid `duration_ms`, `video_codec`, `audio_codec`, and `container` MUST receive confidence 1.0.
- An asset missing `duration_ms` MUST receive confidence 0.0.
- An asset with `duration_ms = 0` MUST receive confidence 0.0.
- An asset with `duration_ms` exceeding 10,800,000ms MUST receive confidence 0.0.
- An asset with confidence below `auto_ready_threshold` MUST NOT be auto-promoted to ready.
- An asset with confidence at or above `auto_ready_threshold` MUST be auto-promoted to ready.

### Enrichment Idempotency

- Re-enrichment with the same pipeline checksum MUST skip already-enriched assets.
- Re-enrichment with a changed pipeline checksum MUST re-process previously enriched assets.
- Auto-injection of `InterstitialTypeEnricher` MUST occur for collections named in the Collection Type Map without manual enricher attachment.

### Traffic Eligibility

- An asset with `state='ready'`, valid `duration_ms`, and `interstitial_type` present in editorial payload MUST appear in `get_filler_assets()` results (when type is in `allowed_types`).
- An asset without `interstitial_type` in editorial payload MUST NOT appear in `get_filler_assets()` results regardless of state.
- An asset with `state='new'` MUST NOT appear in `get_filler_assets()` results.
- An asset with null `duration_ms` MUST NOT appear in `get_filler_assets()` results.
- An asset with `duration_ms` exceeding `max_duration_ms` MUST NOT appear in `get_filler_assets()` results.
- `get_filler_assets()` MUST NOT reference collection name or collection UUID in its query.

---

## Enforcement Evidence

TODO
