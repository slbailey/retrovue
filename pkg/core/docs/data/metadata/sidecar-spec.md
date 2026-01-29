### RetroVue Sidecar JSON Specification (v0.1)

Last updated: 2025-11-02

This document defines the RetroVue sidecar JSON format that accompanies media files or importer
items. Sidecars provide editorial metadata that maps 1:1 to the fields defined in
`docs/metadata/metadata-taxonomy.md` and can optionally mark specific fields as authoritative for
source resolution.

---

### Design goals

- 1:1 field mapping to the taxonomy. Keys and types should match exactly (snake_case, ISO dates,
  integer seconds, etc.).
- Minimal control surface: a single `_meta` object provides sidecar-level controls (e.g.,
  authoritative fields) without wrapping or altering field values.
- Deterministic resolution: marked authoritative fields win over platform/embedded sources per the
  global strategy (see `metadata-sources.md`).

---

### File structure

Top-level JSON object with three parts:
- Metadata fields as defined in the taxonomy. Include only what you intend to set.
- `_meta` object for controls and versioning.
- Optional `relationships` object for explicit cross-links.
 - Optional `station_ops` object for operational scheduling tags.

`_meta` object fields
- `schema` (string, required) – identifier of the schema owner; must be `retrovue.sidecar`.
- `version` (string, required) – semantic version of the sidecar schema (e.g., `0.1.0`). Used by the
  handler to route to the correct validator.
- `scope` (string, optional) – the scope of this sidecar. One of `file` (default), `series`,
  or `collection`. Scope controls merge priority during ingest.
- `importer_hints` (object, optional) – provenance hints for the importer or handler. Keys:
  - `source_system` (string): e.g., `plex`, `filesystem`, `s3`.
  - `source_uri` (string): importer-native locator, e.g., `plex://server/library/12345`.
  The handler may ignore this; it is primarily for provenance and routing.
- `authoritative_fields` (array[string]) – list of field keys in this sidecar that should be treated
  as authoritative (same precedence as manual/editorial). Only the listed keys gain priority; other
  fields follow standard source priority.
- `notes` (string, optional) – freeform note for provenance/documentation.

Example shape
```json
{
  "asset_type": "episode",
  "title": "...",
  "genres": ["comedy"],
  "runtime_seconds": 1487,
  "relationships": {
    "series_id": "11111111-2222-3333-4444-555555555555",
    "season_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
  },
  "_meta": {
    "schema": "retrovue.sidecar",
    "version": "0.1.0",
    "scope": "file",
    "importer_hints": {
      "source_system": "plex",
      "source_uri": "plex://server/library/12345"
    },
    "authoritative_fields": ["title", "genres"],
    "notes": "Curated by archivist A on 2025-10-31"
  }
}
```

Relationships object
- Purpose: explicit cross-links so the importer/handler doesn’t guess from folders.
- Allowed keys (UUID strings):
  - `series_id` – parent Series identifier
  - `season_id` – parent Season (if modeled) identifier
  - `promoted_asset_id` – for `promo`, the referenced asset
  - Future keys may be added as taxonomy evolves (e.g., `franchise_id`).

Station operations extension (optional)
- Purpose: TV scheduling metadata separate from editorial fields; consumed by the scheduler and
  playlog builder.
- Keys (see `docs/metadata/scheduling-tags.md` for enums):
  - `content_class`: `cartoon`, `sitcom`, `live_action_kids`, `movie`, `promo`, `bumper`, `ad`
  - `daypart_profile`: `weekday_morning`, `after_school`, `prime`, `late_night`, `overnight`
  - `ad_avail_model`: `none`, `kids_30`, `standard_30`, `movie_longform`

Example snippet
```json
{
  "station_ops": {
    "content_class": "cartoon",
    "daypart_profile": "after_school",
    "ad_avail_model": "kids_30"
  }
}
```

Validation
- The Metadata Handler validates keys and types against the taxonomy models.
- Unknown keys are rejected by default.

---

### Authoritative fields and source resolution

- Resolution priority (high → low): Manual/Sidecar(authoritative) > Sidecar(standard) > Plex >
  Embedded > Filename > AI; with Probe always winning for technical fields.
- Mark a field authoritative by listing its key in `_meta.authoritative_fields`.
- Authoritative applies per key, not globally.
- Do not mark technical fields (`runtime_seconds`, `resolution`, `aspect_ratio`, `audio_*`) as
  authoritative; Probe remains the source of truth.

---

### Attachment rules (Filesystem importer)

Place sidecar JSON next to the media file. The handler discovers sidecars using the following
patterns (checked in order):

For a media file `Show.S01E02.mkv`:
1) `Show.S01E02.retrovue.json`
2) `Show.S01E02.json`
3) `.retrovue/Show.S01E02.json` (in a hidden `.retrovue` directory alongside the file)

Series-level sidecars (optional, for Series defaults):
- In series folder: `series.retrovue.json` or `series.json`.
- Must declare `"_meta": { "scope": "series", ... }`.
- Applied to episodes in that folder as defaults for missing fields. If `authoritative_fields` is
  present, it applies within the series scope only.

Collection-scoped sidecars (optional):
- Provided by importer when the unit of organization is a collection/source rather than a file
  hierarchy.
- Must declare `"_meta": { "scope": "collection", ... }`.
- Applied with the lowest priority among sidecars.

Merge order (highest → lowest)
1) File-scoped sidecar (`scope = file`)
2) Series-scoped sidecar (`scope = series`)
3) Collection-scoped sidecar (`scope = collection`)

Authoritative fields are evaluated per scope. For a given key, if a file-scoped sidecar marks it
authoritative, it wins over series/collection scopes and platform metadata. If only the
series-scoped sidecar marks it authoritative, it wins over collection scope and platform, but is
still overridden by a file-scoped authoritative declaration for the same key.

Other importers (e.g., Plex) may deliver sidecar content via their API; the structure is identical.

---

### Field mapping and types

- Keys must match `metadata-taxonomy.md` exactly (snake_case).
- Types must match Pydantic models in `src/retrovue/domain/metadata_schema.py`.
- Arrays should omit empty values; omit unknown/empty fields entirely.
- Dates are ISO-8601 `YYYY-MM-DD`; durations are integer seconds.

Common fields (subset reminder; see taxonomy for full list):
- `title` (string)
- `description` (string)
- `genres` (array[string])
- `production_year` (integer)
- `release_date` (date)
- `content_rating` (object: `{system, code, reason?}`)
- `runtime_seconds` (integer)
- `aspect_ratio` (string)
- `resolution` (string: `480p`|`720p`|`1080p`|`2160p`)

---

### Examples

Episode sidecar (S01E02)
```json
{
  "asset_type": "episode",
  "title": "Pilot (Part 2)",
  "season_number": 1,
  "episode_number": 2,
  "description": "Part two of the pilot.",
  "genres": ["comedy"],
  "runtime_seconds": 1487,
  "aspect_ratio": "4:3",
  "resolution": "480p",
  "content_rating": { "system": "TVPG", "code": "TV-PG" },
  "external_ids": { "imdb_id": "tt0092401" },
  "relationships": {
    "series_id": "b1c2c1b2-aaaa-bbbb-cccc-ddee88990011",
    "season_id": "0f0e0d0c-aaaa-bbbb-cccc-999988887777"
  },
  "_meta": {
    "schema": "retrovue.sidecar",
    "version": "0.1.0",
    "scope": "file",
    "authoritative_fields": ["title", "genres", "content_rating"],
    "notes": "Verified against TV guide"
  }
}
```

Movie sidecar
```json
{
  "asset_type": "movie",
  "title": "Retro Nights",
  "description": "A nostalgic journey...",
  "production_year": 1986,
  "release_date": "1986-06-21",
  "genres": ["drama", "romance"],
  "runtime_seconds": 5400,
  "content_rating": { "system": "MPAA", "code": "PG" },
  "poster_image_url": "https://example.org/posters/retro-nights.jpg",
  "external_ids": { "imdb_id": "tt0089999" },
  "_meta": {
    "schema": "retrovue.sidecar",
    "version": "0.1.0",
    "scope": "file",
    "authoritative_fields": ["release_date", "genres"],
    "notes": "Curated festival metadata"
  }
}
```

Promo sidecar
```json
{
  "asset_type": "promo",
  "title": "Retro Hour — New Season Promo",
  "runtime_seconds": 30,
  "promoted_asset_type": "series",
  "promoted_asset_id": "b1c2c1b2-aaaa-bbbb-cccc-ddee88990011",
  "campaign_name": "Season 3 Launch",
  "air_window_start": "1989-09-01",
  "air_window_end": "1989-10-01",
  "call_to_action": "Saturdays 8/7c",
  "relationships": {
    "promoted_asset_id": "b1c2c1b2-aaaa-bbbb-cccc-ddee88990011"
  },
  "_meta": {
    "schema": "retrovue.sidecar",
    "version": "0.1.0",
    "scope": "file",
    "authoritative_fields": ["campaign_name", "air_window_start", "air_window_end"],
    "notes": "Pulled from station logs"
  }
}
```

---

### Processing notes

- If a sidecar provides a field not present in the taxonomy, the ingest should reject the sidecar
  (or ignore the unknown field based on configuration) and log a validation error.
- `_meta.schema` and `_meta.version` are required. If missing, the handler may reject the sidecar or
  attempt to infer defaults; explicit values are strongly recommended to avoid ambiguity across
  schema revisions.
- Authoritative fields apply only to keys present in the sidecar payload. They do not implicitly
  elevate omitted keys.
- Array merge policy for fields like `genres`, `keywords`:
  - If an array field is listed in `_meta.authoritative_fields`, the sidecar replaces the array.
    - Example: authoritative_fields contains `"genres"` → `final.genres = sidecar.genres`.
  - If an array field is not listed as authoritative, the sidecar prefix-merges and de-duplicates
    with lower-priority sources.
    - Example: authoritative_fields does NOT contain `"genres"` →
      `final.genres = sidecar.genres + other.genres` (dedup, preserve first-seen order).
- Media probe precedence (enforced): The following fields are never honored as authoritative and
  will be overwritten by probe results during ingest: `runtime_seconds`, `resolution`, `aspect_ratio`,
  `audio_channels`, `audio_format`, `container`, `video_codec`.


