### RetroVue Asset URI Schema (v0.1)

Last updated: 2025-11-02

This document defines RetroVue URI conventions for asset location and playout.
It clarifies the difference between `source_uri` (importer-native locator) and
`canonical_uri` (RetroVue playout locator), enumerates allowed importer URI
formats, explains mapping/resolution, re-resolution behavior, and outlines the
related database structures.

---

### Concepts: source_uri vs canonical_uri

- `source_uri` (importer-native)
  - Purpose: points back to the original item/location in the importer’s domain.
  - Stability: stable as long as the importer preserves its own identifiers.
  - Example: `plex://library/metadata/12345`, `file://X:/TV/Show/S01E02.mkv`, `s3://bucket/key`.
  - Ownership: written/managed by the importer; used for provenance and re-resolution.

- `canonical_uri` (RetroVue playout)
  - Purpose: stable, internal playout locator that RetroVue resolves to a concrete
    playback URL or stream at runtime.
  - Stability: stable across storage moves and path renames; tied to the `asset_id`.
  - Format: native filesystem path persisted at ingest time (not `file://`).
  - Resolution: used directly for local access; remote playback URLs are resolved by adapters
    when needed (e.g., Plex transcode URL, signed S3 URL) and are not stored as canonical URIs.

Key differences
- `source_uri` is for origin/provenance; `canonical_uri` is for playout.
- `source_uri` scheme varies by importer; `canonical_uri` uses a single RetroVue scheme.
- `source_uri` must never embed credentials; `canonical_uri` is not a direct signed URL.

---

### URI formats and normalization by importer

All URIs use lowercase scheme. Paths must be percent-encoded where required.

| Importer | Required `source_uri` format | Notes and normalization rules | Example |
| --- | --- | --- | --- |
| Plex | `plex://library/metadata/{rating_key}` | rating_key is Plex integer/id; optional server scoping may be handled in Importer config; no credentials in URI | `plex://library/metadata/12345` |
| Filesystem | Windows: `file://X:/path/to/file.ext`  POSIX: `file:///path/to/file.ext` | Convert backslashes to forward slashes; uppercase drive letter; collapse duplicate separators; percent-encode spaces | `file://X:/TV/Show/S01E02.mkv` |
| S3 | `s3://{bucket}/{key}` | Do not embed credentials; optional `?versionId=...` if versioning required; collapse `//` | `s3://archive-bucket/tv/Show/S01E02.mkv` |
| HTTP(S) | `https://...` or `http://...` | Only if importer supports web source; must be absolute; prefer https | `https://media.example.com/asset.mkv` |

RetroVue canonical

| Field | Format | Examples |
| --- | --- | --- |
| `canonical_uri` | native filesystem path | `R:\media\tv\Show\S01E02.mkv`, `/mnt/media/Show/S01E02.mkv` |
| Scheme | none (not `file://`) | — |

Normalization checklist
- Lowercase scheme (e.g., `plex://`, `file://`, `s3://`, `retrovue://`).
- Remove trailing slashes unless they are meaningful to the scheme.
- Percent-encode spaces and reserved characters in path segments.
- Windows file paths: use `file://X:/...` with forward slashes; uppercase the drive letter.
- S3: ensure exactly one `/` between bucket and key; strip leading `/` from key.

---

### Example mapping and resolution

RetroVue resolves a `canonical_uri` to a concrete playback URL using the asset’s
`source_uri`, the `Importer` adapter, and optional `PathMapping` rows.

| Importer | source_uri | Mapping rule / adapter | canonical_uri | Resolved playback URL (example) |
| --- | --- | --- | --- | --- |
| Filesystem | `file://X:/TV/Show/S01E02.mkv` | Map to local native path via `PathMapping` | `X:\TV\Show\S01E02.mkv` | `smb://nas/TV/Show/S01E02.mkv` |
| Filesystem | `file:///mnt/media/Show/S01E02.mkv` | Map to local native path via `PathMapping` | `/mnt/media/Show/S01E02.mkv` | signed `https://s3.amazonaws.com/archive-bucket/tv/Show/S01E02.mkv?...` |
| Plex | `plex://library/metadata/12345` | Resolve to local native path when mirrored; else leave canonical unset until resolved | `/mnt/media/Show/S01E02.mkv` | `https://plex.server:32400/video/:/transcode/universal/start?...` |
| S3 | `s3://archive-bucket/tv/Show/S01E02.mkv` | Resolve to local cache path if materialized; else managed by runtime adapters | `/var/cache/rv/Show/S01E02.mkv` | signed `https://archive-bucket.s3.amazonaws.com/tv/Show/S01E02.mkv?...` |

Transformation examples

| Input | Step | Output |
| --- | --- | --- |
| `file://x:/tv/Show/Clip.MKV` | Normalize scheme/case/path | `file://X:/tv/Show/Clip.MKV` |
| `file://X:/tv/Show/Clip.MKV` | Apply mapping `file://X:/tv` → `smb://nas/TV` | `smb://nas/TV/Show/Clip.MKV` |
| `s3://archive/TV/Show/Clip.mkv` | Sign for playback | `https://archive.s3.amazonaws.com/TV/Show/Clip.mkv?X-Amz-Expires=...` |
| `plex://library/metadata/12345` | Resolve via Importer | Plex transcode URL | 

---

### Re-resolution lifecycle

When a `canonical_uri` fails to resolve or becomes stale, RetroVue re-resolves using
the authoritative `source_uri` and current configuration.

Triggers
- Playback returns 404/410 or storage error.
- `PathMapping` changed (e.g., mount moved from SMB to S3).
- Importer-specific invalidation (e.g., Plex item migrated servers but rating_key retained).
- Integrity mismatch (e.g., `file_sha256` updated after re-ingest).

Process
1) Attempt resolution from cache; if expired or failed, continue.
2) Use Importer adapter to translate `source_uri` → current fetchable URL.
3) Apply `PathMapping` transformations if the adapter yields a path-based locator.
4) Validate reachability (lightweight stat where applicable).
5) Update `Asset.canonical_uri` when the native path changes due to mapping/config updates.
6) Record `last_resolved_at` and provenance; on failure, mark `state = needs_attention`.

Notes
- `canonical_uri` typically remains a stable native path across runs.
- Do not mutate `source_uri` except during re-ingest by the importer.

---

### Database structures and relationships

This section lists expected columns to support URI handling. Types are indicative.

Importer

| Column | Type | Notes |
| --- | --- | --- |
| importer_id | uuid | PK |
| name | text | e.g., `plex`, `filesystem`, `s3` |
| scheme | text | lowercase scheme this importer owns (e.g., `plex`, `file`, `s3`) |
| config_json | jsonb | server/endpoints/credentials (secure store) |
| enabled | boolean | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

PathMapping

| Column | Type | Notes |
| --- | --- | --- |
| mapping_id | uuid | PK |
| importer_id | uuid | FK → Importer (nullable; global mapping if null) |
| scheme | text | e.g., `file`, `smb`, `s3` |
| source_prefix | text | e.g., `file://X:/TV` |
| target_prefix | text | e.g., `smb://nas/TV` or `s3://archive-bucket/tv` |
| priority | int | Higher wins when multiple prefixes match |
| active | boolean | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

Asset

| Column | Type | Notes |
| --- | --- | --- |
| asset_id | uuid | PK |
| importer_id | uuid | FK → Importer |
| source_uri | text | importer-native locator |
| canonical_uri | text | native filesystem path |
| canonical_key | text | for dedupe; see taxonomy |
| file_sha256 | text | content integrity |
| variant | text | `source` | `mezzanine` | `transcoded-...` |
| state | text | `ready` | `missing` | `needs_attention` | ... |
| approved_for_broadcast | boolean | |
| last_resolved_at | timestamptz | last successful resolution |
| created_at | timestamptz | |
| updated_at | timestamptz | |

Relationships
- `Asset.importer_id` → `Importer.importer_id`
- `PathMapping.importer_id` → `Importer.importer_id` (optional scoping)
- Resolvers consult all active `PathMapping` rows applicable to the scheme.

---

### Validation and examples

Valid canonical URI examples
```
R:\\media\\anime-movies\\akira (1988)\\akira (1988) webdl-480p.mkv
/mnt/media/anime-movies/akira (1988)/akira (1988) webdl-480p.mkv
```

Valid filesystem source URIs
```
file://X:/TV/Show/S01E02.mkv
file:///mnt/media/Show/S01E02.mkv
```

Valid S3 source URI
```
s3://archive-bucket/tv/Show/S01E02.mkv
```

Valid Plex source URI
```
plex://library/metadata/12345
```



