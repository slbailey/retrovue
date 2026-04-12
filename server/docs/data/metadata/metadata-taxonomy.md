### RetroVue Metadata Taxonomy (v0.1)

Last updated: 2025-11-02

This document defines the complete metadata taxonomy that RetroVue recognizes across
all entity types and import sources. It is the authoritative reference for metadata
handlers, importers, and enrichers.

- Applies to: filesystem importer, Plex importer, embedded tags, and sidecar JSON.
- Enrichment: AI and human processes may add or refine optional fields
  (e.g., summaries, keywords, tone, decade, genre refinements).

Entity index:
- [Series](#series)
- [Episode](#episode)
- [Movie](#movie)
- [Bumper](#bumper)
- [Promo](#promo)
- [Ad](#ad)
- [Block](#block)

Reference and shared material:
- [Conventions and types](#conventions-and-types)
- [Shared/common fields](#sharedcommon-fields)
- [Controlled vocabularies and enums](#controlled-vocabularies-and-enums)
- [Importer source notes](#importer-source-notes)

Cross-links:
- Episode → Series → (optional) Franchise
- Promo → promoted asset (Episode, Movie, Series)
- Block → lineup entries referencing Episodes, Movies, Bumpers, Promos, Ads

Note on franchise: RetroVue supports an optional higher-level grouping (`franchise_id`)
referenced by `Series`. Franchise itself is not a core entity here; if present, it follows
the same conventions as `Series` with minimal fields (`franchise_id`, `title`).

---

### Conventions and types

- Key naming: snake_case.
- Identifiers: UUIDv4 strings for all primary keys (`*_id`). External IDs retain their
  native formats.
- Dates/times: ISO-8601. Use `YYYY-MM-DD` for dates, full timestamp with `Z` for UTC
  datetimes (e.g., `2023-08-17T21:03:00Z`).
- Durations: integer seconds (`runtime_seconds`).
- Languages: BCP-47 codes (`en`, `en-US`, `pt-BR`).
- Countries/regions: ISO 3166-1 alpha-2 (`US`, `GB`).
- Aspect ratios: string form like `4:3`, `16:9`.
- Resolution labels: `480p`, `720p`, `1080p`, `2160p`.
- Arrays: JSON arrays; omit empty arrays rather than supplying empty unless explicitly
  required by a client.
- Nullability: If a field is unknown, omit the key. Do not emit null values unless a
  client explicitly requires it.

Types used in tables:
- string, integer, boolean, date, datetime, array[string], array[object], object,
  enum[string]

Primary key pattern:
- Each entity defines a primary key named `<entity>_id` (e.g., `series_id`, `episode_id`).
- Cross-references also use typed IDs (e.g., `series_id` on an Episode).

Canonical keying:
- Importers should supply a stable `canonical_key` when possible, derived with shared
  logic in the application (see `src/retrovue/infra/canonical.py`). This key is used to
  consistently reconcile duplicates across sources.

---

### Shared/common fields

These fields may appear on multiple entities; not all are required for every entity.
Entity-specific sections declare which are required.

| **Field**            | **Type**     | **Description**           | **Example**               | **Source notes**         |
|----------------------|--------------|---------------------------|---------------------------|--------------------------|
| `title`              | string       | Primary display title     | "The Retro Hour"          | Filesystem, Plex, tags   |
| `original_title`     | string       | Original/air title        | "Retro Hour"              | Plex, tags, manual entry |
| `sort_title`         | string       | Title for sorting         | "Retro Hour, The"         | Generated, Plex          |
| `description`        | string       | Synopsis/summary          | "A look back at..."       | Plex, sidecar, enrich    |
| `tagline`            | string       | Short marketing phrase    | "Classic vibes..."        | Enrich, manual           |
| `genres`             | array[string]| High-level genres         | ["comedy", "family"]      | Plex, sidecar, enrich    |
| `subgenres`          | array[string]| More granular genres      | ["sketch", "variety"]     | Enrichment               |
| `themes`             | array[string]| Narrative/subject themes  | ["friendship","nostalgia"]| Enrichment               |
| `keywords`           | array[string]| Freeform keywords         | ["retro","80s"]           | Enrich, sidecar          |
| `tone`               | enum[string] | Overall tone              | "light"                   | Enrichment               |
| `mood`               | array[string]| Vibe descriptors          | ["upbeat","whimsical"]    | Enrichment               |
| `production_year`    | integer      | Year produced             | 1987                      | Plex, tags               |
| `release_date`       | date         | Premier date              | 1987-09-12                | Plex, tags, sidecar      |
| `original_air_date`  | date         | TV first air date         | 1988-01-05                | TVDB/Plex, sidecar       |
| `decade`             | enum[string] | Decade bucketing          | "1980s"                   | Enrich (from year)       |
| `country_of_origin`  | string       | ISO country code          | "US"                      | Plex                     |
| `original_language`  | string       | Primary language          | "en"                      | Plex, tags               |
| `spoken_languages`   | array[string]| Languages present         | ["en"]                    | Media probe, Plex        |
| `content_rating`     | object       | Rating system/code        | {"system":"TVPG",...}     | Plex, sidecar            |
| `runtime_seconds`    | integer      | Program duration (sec)    | 1487                      | Probe, Plex              |
| `aspect_ratio`       | string       | Display aspect ratio      | "4:3"                     | Media probe              |
| `resolution`         | enum[string] | Resolution tier           | "480p"                    | Media probe              |
| `color`              | enum[string] | Colorization              | "bw"                      | Enrich, sidecar          |
| `audio_channels`     | integer      | Channel count             | 2                         | Media probe              |
| `audio_format`       | string       | Audio layout              | "stereo"                  | Media probe              |
| `closed_captions`    | boolean      | CC present                | true                      | Probe, sidecar           |
| `subtitles`          | array[string]| Subtitle language codes   | ["en"]                    | Probe, sidecar           |
| `poster_image_url`   | string       | Primary poster URL        | "https://.../poster.jpg"  | Plex, sidecar            |
| `backdrop_image_url` | string       | Background URL            | "https://.../bg.jpg"      | Plex, sidecar            |
| `thumbnail_url`      | string       | Thumbnail URL             | "https://.../thumb.jpg"   | Generated, Plex, sidecar |
| `credits`            | object       | People/roles (see below)  | {"directors":[...]}       | Plex, enrich, sidecar    |
| `external_ids`       | object       | Known external IDs        | {"imdb_id":"tt0092400"}   | Plex, sidecar            |
| `source_name`        | string       | Importer name             | "plex"                    | Importer                 |
| `source_uid`         | string       | Unique source ref         | "plex://.../12345"        | Plex path                |
| `source_path`        | string       | Filesystem path           | "X:\\TV\\...\\S01E02.mkv" | Filesystem               |
| `file_sha256`        | string       | Content hash              | "7b1e..."                 | Probe                    |
| `canonical_key`      | string       | Canonical dedupe key      | "series:retro-hour|s01e02"| Canonical logic          |
| `ai_summary`         | string       | AI-generated summary      | "A throwback..."          | Enrichment               |
| `ai_keywords`        | array[string]| AI-generated keywords     | ["commercials","nostalgia"]| Enrichment              |
| `ai_genres`          | array[string]| AI-suggested genres       | ["variety","talk"]        | Enrichment               |
| `ai_tone`            | enum[string] | AI-inferred tone          | "whimsical"               | Enrichment               |

Credits structure (common):

| Subfield    | Type          | Description        | Example                      |
|-------------|---------------|--------------------|------------------------------|
| directors   | array[object] | Director credits   | [{"name":"Jane Doe"}]        |
| writers     | array[object] | Writer credits     | [{"name":"John Roe"}]        |
| cast        | array[object] | On-screen cast     | [{"name":"A. Star",...
| producers   | array[object] | Producers          | [{"name":"P. Exec"}]         |
| guest_stars | array[object] | Guest performers   | [{"name":"C. Guest"}]        |

Each credit object may include:
`{ "name": string, "person_id": string (optional), "role": string (optional), "character": string (optional) }`.

---

### Series

Represents a television series or program with one or more episodes. Cross-links: Episodes
reference `series_id`. Series may optionally reference a higher-level `franchise_id`.

Required fields (Series):

| Field       | Type         | Description         | Example        | Source notes          |
|-------------|--------------|---------------------|----------------|----------------------|
| series_id   | string       | UUID primary key    | "b1c2..."      | Assigned by RetroVue |
| title       | string       | Series title        | "Retro Hour"   | Plex/Filesystem/etc  |
| asset_type  | enum[string] | Constant "series"   | "series"       | Importer/normalizer  |

Optional/enrichment fields (Series):

| Field              | Type         | Description           | Example         | Source notes    |
|--------------------|--------------|-----------------------|-----------------|-----------------|
| original_title     | string       | Original series title | "The Retro Hour"| Plex            |
| sort_title         | string       | Sort-friendly title   | "Retro Hour,The"| Generated       |
| description        | string       | Series synopsis       | "A weekly dive..." | Plex/enrich   |
| production_year    | integer      | Debut year            | 1987            | Plex            |
| release_date       | date         | Premiere date         | 1987-09-12      | Plex/sidecar    |
| decade             | enum[string] | Era grouping          | "1980s"         | Enrich/derived  |
| studio             | string       | Producing studio      | "RetroWorks"    | Plex/sidecar    |
| network            | string       | Network               | "WXYZ"          | Enrich/sidecar  |
| country_of_origin  | string       | Origin country        | "US"            | Plex            |
| original_language  | string       | Original language     | "en"            | Plex            |
| content_rating     | object       | Series-level rating   | {"system":"TVPG","code":"TV-PG"} | Plex |
| seasons_count      | integer      | Number of seasons     | 3               | Derived         |
| episode_count      | integer      | Number of episodes    | 42              | Derived         |
| poster_image_url   | string       | Poster image          | "https://.../series.jpg" | Plex    |
| backdrop_image_url | string       | Background            | "https://.../bg.jpg"    | Plex    |
| external_ids       | object       | External refs         | {"tvdb_id":"12345"}     | Plex    |
| franchise_id       | string       | Franchise group       | "f9a0..."       | Enrich/sidecar  |
| canonical_key      | string       | Canonical key         | "series:retro-hour"     | Canonical      |

---

### Episode

Represents a single episode belonging to a Series. Cross-links: references `series_id`.

Required fields (Episode):

| Field           | Type         | Description            | Example         | Source notes          |
|-----------------|--------------|------------------------|-----------------|----------------------|
| episode_id      | string       | UUID primary key       | "e2d3..."       | Assigned by RetroVue |
| asset_type      | enum[string] | Constant "episode"     | "episode"       | Importer/normalizer  |
| series_id       | string       | Parent Series          | "b1c2..."       | From Series          |
| season_number   | integer      | Season index (1-based) | 1               | Parsed/Plex          |
| episode_number  | integer      | Index in season        | 2               | Parsed/Plex          |
| title           | string       | Episode title          | "Pilot (Part 2)"| Plex/file name       |
| runtime_seconds | integer      | Duration               | 1487            | Probe/Plex           |

Optional/enrichment fields (Episode):

| Field                  | Type         | Description     | Example         | Source notes        |
|------------------------|--------------|-----------------|-----------------|---------------------|
| absolute_episode_number| integer      | Absolute index  | 3               | Enrich/sidecar      |
| production_code        | string       | Prod. code      | "RH-102"        | Sidecar             |
| original_air_date      | date         | TV first air    | 1987-09-19      | Plex/TVDB           |
| description            | string       | Synopsis        | "Part two..."   | Plex/enrich         |
| guest_stars           | array[object]| Guest stars     | [{"name":"..." }] | Plex/enrich       |
| content_rating         | object       | Rating object   | {"system":"TVPG","code":"TV-PG"} | Plex  |
| poster_image_url       | string       | Poster          | "https://.../e102.jpg"            | Plex  |
| external_ids           | object       | External refs   | {"imdb_id":"tt0092401"}           | Plex  |
| source_path            | string       | File path       | "X:\\TV\\...S01E02.mkv"           | FS   |
| file_sha256            | string       | Content hash    | "7b1e..."                         | Probe|
| aspect_ratio           | string       | Aspect ratio    | "4:3"                             | Probe|
| resolution             | enum[string] | Resolution      | "480p"                            | Probe|
| subtitles              | array[string]| Subtitles       | ["en"]                            | Probe|
| ai_summary             | string       | AI summary      | "In this episode..."              | Enrich|
| ai_keywords            | array[string]| AI keywords     | ["pilot","retro"]                 | Enrich|
| canonical_key          | string       | Canonical key   | "series:retro-hour|s01e02"        | Canonical|

---

### Movie

Represents a single, standalone film.

Required fields (Movie):

| Field           | Type         | Description      | Example              | Source notes          |
|-----------------|--------------|------------------|----------------------|----------------------|
| movie_id        | string       | UUID primary key | "m3f4..."            | Assigned by RetroVue |
| asset_type      | enum[string] | Constant "movie" | "movie"              | Importer/normalizer  |
| title           | string       | Movie title      | "Retro Nights"       | Plex/file name       |
| runtime_seconds | integer      | Duration         | 5400                 | Probe/Plex           |

Optional/enrichment fields (Movie):

| Field           | Type          | Description    | Example           | Source notes     |
|-----------------|---------------|----------------|-------------------|------------------|
| release_date    | date          | Release date   | 1986-06-21        | Plex/sidecar     |
| production_year | integer       | Year produced  | 1986              | Plex             |
| description     | string        | Synopsis       | "A nostalgic..."  | Plex/enrich      |
| genres          | array[string] | Genres         | ["drama","romance"]| Plex/enrich     |
| content_rating  | object        | Rating         | {"system":"MPAA","code":"PG"}| Plex     |
| directors       | array[object] | Directors      | [{"name":"J.Dir"}]| Plex             |
| writers         | array[object] | Writers        | [{"name":"S.Wri"}]| Plex             |
| cast            | array[object] | Cast           | [{"name":"Lead..."}]| Plex           |
| external_ids    | object        | External refs  | {"imdb_id":"tt0089999"}| Plex          |
| poster_image_url| string        | Poster         | "https://...jpg"  | Plex             |
| source_path     | string        | File path      | "X:\\Movies\\Retro Nights..."| FS      |
| file_sha256     | string        | Content hash   | "a9f0..."         | Probe            |
| ai_summary      | string        | AI summary     | "A heartfelt..."  | Enrich           |
| canonical_key   | string        | Canonical key  | "movie:retro-nights|1986" | Canonical   |

---

### Bumper

Represents a short interstitial such as a network ident, slate, or rating bumper.

Required fields (Bumper):

| Field           | Type         | Description     | Example              | Source notes     |
|-----------------|--------------|-----------------|----------------------|------------------|
| bumper_id       | string       | UUID primary key| "b4a5..."            | Assigned by RetroVue |
| asset_type      | enum[string] | Constant "bumper"| "bumper"            | Importer/normalizer  |
| title           | string       | Short title      | "WXYZ Station ID..." | File/sidecar        |
| bump_type       | enum[string] | Bumper subtype   | "station_id"         | Enrich/sidecar      |
| runtime_seconds | integer      | Duration         | 10                   | Probe              |

Optional/enrichment fields (Bumper):

| Field            | Type         | Description     | Example         | Source notes     |
|------------------|--------------|-----------------|-----------------|------------------|
| era              | enum[string] | Era label       | "1980s"         | Enrich           |
| network          | string       | Network/brand   | "WXYZ"          | Sidecar          |
| description      | string       | Notes           | "Animated logo..."| Sidecar         |
| content_rating   | object       | Rating          | {"system":"TVPG","code":"TV-G"}| Sidecar|
| source_path      | string       | File path       | "X:\\Bumpers\\...mov"| Filesystem     |
| file_sha256      | string       | Hash            | "3fe2..."        | Probe            |
| aspect_ratio     | string       | Aspect          | "4:3"            | Probe            |
| resolution       | enum[string] | Resolution      | "480p"           | Probe            |
| canonical_key    | string       | Canonical key   | "bumper:wxyz...|1989"| Canonical      |

---

### Promo

Represents a promotional clip advertising an upcoming/current program or movie.

Required fields (Promo):

| Field           | Type         | Description           | Example              | Source notes        |
|-----------------|--------------|-----------------------|----------------------|---------------------|
| promo_id        | string       | UUID primary key      | "p5c6..."            | Assigned by RetroVue|
| asset_type      | enum[string] | Constant "promo"      | "promo"              | Importer/normalizer |
| title           | string       | Promo title/slug      | "Retro Hour — New..."| File/sidecar        |
| runtime_seconds | integer      | Duration              | 30                   | Probe/Plex          |

Optional/enrichment fields (Promo):

| Field              | Type         | Description         | Example        | Source notes      |
|--------------------|--------------|---------------------|--------------- |-------------------|
| promoted_asset_type| enum[string] | Target entity type  | "series"       | Sidecar/enrich    |
| promoted_asset_id  | string       | Target entity id    | "b1c2..."      | Resolved/linking  |
| campaign_name      | string       | Campaign label      | "Season 3..."  | Sidecar           |
| air_window_start   | date         | Start of promo run  | 1989-09-01     | Sidecar           |
| air_window_end     | date         | End of promo run    | 1989-10-01     | Sidecar           |
| network           | string       | Network/brand       | "WXYZ"         | Sidecar           |
| call_to_action    | string       | CTA text            | "Saturdays..." | Sidecar           |
| content_rating    | object       | Rating              | {"system":"TVPG","code":"TV-G"} | Sidecar|
| source_path       | string       | File path           | "X:\\Promos\\...mov" | FS             |
| file_sha256       | string       | Hash                | "c1d2..."      | Probe             |
| ai_summary        | string       | AI summary          | "Highlights..."| Enrich            |
| canonical_key     | string       | Canonical key       | "promo:retro-hour|s3|30s" | Canonical |

---

### Ad

Represents a commercial advertisement.

Required fields (Ad):

| Field           | Type         | Description           | Example           | Source notes       |
|-----------------|--------------|-----------------------|-------------------|--------------------|
| ad_id           | string       | UUID primary key      | "a6d7..."         | Assigned by RetroVue|
| asset_type      | enum[string] | Constant "ad"         | "ad"              | Importer/normalizer|
| title           | string       | Brand title           | "Tasty Cereal..." | File/sidecar       |
| advertiser      | string       | Brand/advertiser      | "Tasty Cereal Co."| Sidecar/enrich     |
| runtime_seconds | integer      | Duration              | 30                | Probe/Plex         |

Optional/enrichment fields (Ad):

| Field                   | Type         | Description        | Example                | Source notes      |
|-------------------------|--------------|--------------------|------------------------|-------------------|
| product                 | string       | Product line       | "Tasty Cereal Classic" | Sidecar           |
| campaign_name           | string       | Campaign label     | "Kids Breakfast '89"   | Sidecar           |
| air_date                | date         | Known air date     | 1989-03-12             | Sidecar           |
| air_window_start        | date         | Run window start   | 1989-03-01             | Sidecar           |
| air_window_end          | date         | Run window end     | 1989-06-01             | Sidecar           |
| region                  | string       | Target region      | "US"                   | Sidecar           |
| regulatory_disclaimers  | array[string]| Required disclaimers| ["Part of a..."]       | Sidecar           |
| content_warnings        | array[string]| Sensitive content  | ["alcohol"]            | Enrich            |
| source_path             | string       | File path          | "X:\\Ads\\...mov"      | Filesystem        |
| file_sha256             | string       | Hash               | "9ab3..."              | Probe             |
| canonical_key           | string       | Canonical key      | "ad:tasty-cereal..."   | Canonical         |

---

### Block

Represents a curated or scheduled programming block consisting of multiple lineup entries.
Cross-links: lineup items reference assets by their typed IDs.

Required fields (Block):

| Field        | Type           | Description        | Example                | Source notes         |
|--------------|----------------|--------------------|------------------------|----------------------|
| block_id     | string         | UUID primary key   | "k7e8..."              | Assigned by RetroVue |
| asset_type   | enum[string]   | Constant "block"   | "block"                | Importer/normalizer  |
| title        | string         | Block title        | "Saturday Morning..."  | Sidecar/editorial    |
| date         | date           | Block date         | 1989-03-12             | Sidecar/editorial    |
| lineup       | array[object]  | Ordered entries    | [ ... ]                | Sidecar/editorial    |

Lineup entry structure:

| Field                   | Type           | Description            | Example      |
|-------------------------|----------------|------------------------|-------------|
| position                | integer        | 1-based order          | 1           |
| asset_type              | enum[string]   | episode/movie/etc      | "episode"   |
| asset_id                | string         | Referenced entity id   | "e2d3..."   |
| scheduled_runtime_seconds | integer      | Planned runtime        | 1487        |
| start_offset_seconds    | integer        | Optional offset        | 0           |
| notes                   | string         | Editorial notes        | "Use restored cut" |

Optional/enrichment fields (Block):

| Field            | Type         | Description       | Example               | Source notes        |
|------------------|--------------|-------------------|-----------------------|---------------------|
| theme            | string       | Block theme       | "Retro Cartoons"      | Editorial           |
| description      | string       | Block notes       | "Includes interstitials" | Editorial         |
| curator          | string       | Assembled by      | "Archivist A"         | Editorial           |
| timezone         | string       | Display timezone  | "America/New_York"    | Editorial           |
| canonical_key    | string       | Canonical key     | "block:1989-03-12|..." | Canonical         |

---

### Controlled vocabularies and enums

These lists are not exhaustive; they define accepted values and recommended practice.
Importers should prefer source values where available and map to these vocabularies as
reasonable.

Asset type (`asset_type`): `series`, `episode`, `movie`, `bumper`, `promo`, `ad`, `block`.

Tone (`tone` / `ai_tone`): `light`, `serious`, `humorous`, `dark`, `whimsical`, `edgy`,
`earnest`.

Decade (`decade`): `1950s`, `1960s`, `1970s`, `1980s`, `1990s`, `2000s`, `2010s`, `2020s`.

Color (`color`): `color`, `bw`, `colorized`.

Bumper type (`bump_type`): `station_id`, `rating_bump`, `network_ident`, `coming_up_next`,
`interstitial`, `slate`.

Content rating object schema:
```json
{
  "system": "TVPG" | "MPAA" | "BBFC" | "OFLC" | ...,
  "code": "TV-PG" | "PG" | "U" | ...,
  "reason": "string (optional)"
}
```

External IDs (`external_ids`) common keys:
- Series/Episode: `imdb_id`, `tvdb_id`, `tvrage_id`
- Movie: `imdb_id`, `tmdb_id`
- Generic: `gracenote_id`, `wikidata_id`

Credits object role fields: `directors`, `writers`, `cast`, `producers`, `guest_stars`.

---

### Importer source notes

- Filesystem importer:
  - `title`, `season_number`, `episode_number` parsed from folder/file naming (e.g.,
    `Show Name/S01E02 - Title.mkv`).
  - `runtime_seconds`, `resolution`, `aspect_ratio`, `audio_channels` via media probe
    (ffprobe).
  - `file_sha256` computed from bytes; `source_path` set to normalized absolute path.
  - `canonical_key` computed using shared canonical logic from parsed attributes.

- Plex importer:
  - Uses Plex library metadata for `title`, `description`, `genres`, `year`,
    `originallyAvailableAt`, `duration`, artwork URLs.
  - Maps Plex GUIDs to `external_ids` (IMDb/TVDB/TMDB) when determinable.
  - Normalizes to RetroVue enums (e.g., content ratings) where possible.

- Embedded tags:
  - MP4 atoms, ID3, Matroska tags can provide `title`, `description`, `original_title`,
    `year`, sometimes `content_rating`.

- Sidecar JSON:
  - May provide hard-to-derive fields (`production_code`, `bump_type`, `campaign_name`,
    `promoted_asset_id`).
  - Should follow this taxonomy for keys and types.

---

### Cross-links summary

- Episode → `series_id` → Series (and Series may → `franchise_id`).
- Promo → `promoted_asset_type` + `promoted_asset_id` → Series/Movie/Episode.
- Block → `lineup[]` referencing `asset_type` + `asset_id` of Episodes, Movies,
  Bumpers, Promos, Ads.

This ensures navigability and consistent normalization across importers and enrichers.

