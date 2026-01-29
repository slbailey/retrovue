### RetroVue Metadata Sources and Resolution (v0.1)

Last updated: 2025-11-02

This document defines where each metadata field may originate and how RetroVue resolves
conflicts between sources. It complements `docs/metadata/metadata-taxonomy.md` by
specifying data source priority, normalization rules, and example transformations.

- Applies to: filesystem importer, Plex importer, embedded tags, NFO/sidecar JSON,
  manual entry, AI enrichment, and media probe (ffprobe).

---

### Global resolution strategy

Resolution principles (highest → lowest priority). Field-level tables may override:

1) Manual/Editorial and Sidecar JSON
   - Treat as authoritative human-provided data.
   - Sidecar JSON (RetroVue schema) = manual.

2) Technical measurements
   - For technical fields (runtime_seconds, resolution, aspect_ratio, audio_*), prefer
     media probe over other sources. Do not override technical probe values with
     editorial sources.

3) Platform metadata
   - Prefer Plex API metadata over embedded tags and filename parsing for editorial
     fields if manual/sidecar are absent.

4) Embedded tags
   - Use MP4/ID3/Matroska tags when platform metadata is unavailable/incomplete.

5) Deterministic filename parsing
   - Use only when high-confidence; must pass format checks (e.g., `S01E02`).

6) AI enrichment
   - Use only as last resort for editorial fields; never for IDs, counts, technical fields.
   - AI outputs must pass normalization and validation.

Tie-breakers:
- Newer timestamp wins if two entries from the same source conflict and provide
  timestamps.
- For arrays: merge unique values, preserving higher-priority order (see normalization).
- Prefer structured/typed data when sources are the same priority (e.g., sidecar object
  over plain string tag).

Normalization rules (applied per eligible field):
- Trim leading/trailing whitespace; collapse internal runs to single spaces.
- Normalize Unicode to NFC; strip control characters.
- Case conventions:
  - Titles/descriptions: preserve case; do not auto-titlecase.
  - Acronyms/codes: use canonical case (e.g., `TV-PG`, `US`, `en-US`).
  - Language codes: BCP-47; lower-case language, upper-case region (e.g., `pt-BR`).
- Dates: ISO-8601 `YYYY-MM-DD`; timestamps: ISO-8601 `YYYY-MM-DDThh:mm:ssZ`.
- Durations: integer seconds, rounded to nearest whole second.
- Arrays: de-duplicate (case-insensitive); preserve order from highest-priority source;
  remove empty/blank values.
- Enums: map synonyms to canonical vocabulary (see taxonomy).
- Numbers: coerce to integers where specified; reject if not numeric after trimming.
- Aspect ratio: normalize to simplest `W:H` string (e.g., `16:9`, `4:3`).
- External IDs: validate format per provider; strip prefixes (`imdb://` → `tt...`).
- Content rating: normalize to `{system, code, reason?}`; ensure known system codes.

Legend for "Sources" column:
- Manual: editorial entry via UI or curated sidecar JSON, conforming to taxonomy
- Sidecar: machine-authored sidecar JSON (non-editorial), conforming to taxonomy
- Plex: Plex API fields
- Embedded: MP4/ID3/Matroska tags
- Filename: deterministic filename/folder parser
- Probe: media probe (ffprobe) results
- AI: AI enrichment outputs

---

### Shared/common fields

| Field                | Possible Sources                                | Resolution (High→Low)                  | Normalization Rules                                          | Example                                                    |
|----------------------|-------------------------------------------------|----------------------------------------|-------------------------------------------------------------|------------------------------------------------------------|
| title                | Manual, Sidecar, Plex, Embedded, Filename, AI   | Manual/Sidecar > Plex > Embedded > Filename > AI      | trim; NFC; preserve case; collapse spaces                    | " Retro Hour  "(Plex)→"Retro Hour"                         |
| original_title       | Manual, Sidecar, Plex, Embedded                 | Manual/Sidecar > Plex > Embedded                   | trim; preserve case                                         | "RETRO HOUR"(tags)→"RETRO HOUR"                            |
| sort_title           | Manual, Generated, Plex                         | Manual > Generated > Plex                           | leading articles moved; ASCII fold; lower for compare        | "The Retro Hour" → "Retro Hour, The"                       |
| description          | Manual, Sidecar, Plex, Embedded, AI             | Manual/Sidecar > Plex > Embedded > AI               | trim; collapse spaces; retain paragraphs                     | "A look\n back"→"A look back"                              |
| tagline              | Manual, Sidecar, AI                             | Manual/Sidecar > AI                                 | trim; collapse spaces                                        | " Classic vibes. "→"Classic vibes."                        |
| genres               | Manual, Sidecar, Plex, AI                       | Manual/Sidecar > Plex > AI                          | lowercase; map synonyms; dedupe; preserve order              | ["Comedy","Family"]+AI["family"]→["comedy","family"]       |
| subgenres            | Manual, Sidecar, AI                             | Manual/Sidecar > AI                                 | lowercase; map synonyms; dedupe                              | ["Sketch","variety"]→["sketch","variety"]                  |
| themes               | Manual, Sidecar, AI                             | Manual/Sidecar > AI                                 | lowercase; dedupe                                            | ["Friendship","nostalgia"]→["friendship","nostalgia"]      |
| keywords             | Manual, Sidecar, AI                             | Manual/Sidecar > AI                                 | lowercase; dedupe; strip punctuation                         | ["Retro!","80s"]→["retro","80s"]                           |
| tone                 | Manual, Sidecar, AI                             | Manual/Sidecar > AI                                 | enum map; lowercase                                          | "Whimsical"→"whimsical"                                    |
| mood                 | Manual, Sidecar, AI                             | Manual/Sidecar > AI                                 | lowercase; dedupe                                            | ["Upbeat","whimsical","Upbeat"]→["upbeat","whimsical"]     |
| production_year      | Manual, Sidecar, Plex, Embedded                 | Manual/Sidecar > Plex > Embedded                    | int; 1878≤year≤current+1                                     | "1987"(Plex)→1987                                          |
| release_date         | Manual, Sidecar, Plex, Embedded                 | Manual/Sidecar > Plex > Embedded                    | ISO date; validate calendar                                  | "09/12/1987"→1987-09-12                                    |
| original_air_date    | Manual, Sidecar, Plex                           | Manual/Sidecar > Plex                               | ISO date                                                     | "1987-9-5"→1987-09-05                                      |
| decade               | Derived, AI                                     | Derived(from year/date) > AI                        | map year to decade label                                     | 1987→"1980s"                                               |
| country_of_origin    | Manual, Sidecar, Plex                           | Manual/Sidecar > Plex                               | ISO 3166-1 alpha-2 uppercase                                 | "us"→"US"                                                  |
| original_language    | Manual, Sidecar, Plex, Embedded                 | Manual/Sidecar > Plex > Embedded                    | BCP-47; lower-case lang; upper-case region                   | "EN_us"→"en-US"                                            |
| spoken_languages     | Probe, Manual, Sidecar, Plex                    | Probe > Manual/Sidecar > Plex                       | BCP-47 list; dedupe                                          | ["en","EN"]→["en"]                                         |
| content_rating       | Manual, Sidecar, Plex, Embedded, AI             | Manual/Sidecar > Plex > Embedded > AI               | {system,code,reason?}; known systems; code case              | "tv-pg"→{system:"TVPG",code:"TV-PG"}                       |
| runtime_seconds      | Probe, Plex, Sidecar                            | Probe > Plex > Sidecar                              | int seconds; round; ≥0                                       | "1486.7"→1487                                              |
| aspect_ratio         | Probe, Sidecar, Plex                            | Probe > Sidecar > Plex                              | simplify to W:H                                              | 1.777...→"16:9"                                            |
| resolution           | Probe, Sidecar, Plex                            | Probe > Sidecar > Plex                              | enum: 480p/720p/1080p/2160p                                  | 1920x1080→"1080p"                                          |
| color                | Sidecar, AI                                     | Sidecar > AI                                        | enum: color/bw/colorized                                     | "B&W"→"bw"                                                 |
| audio_channels       | Probe, Plex                                     | Probe > Plex                                        | int; ≥1                                                      | "2"→2                                                      |
| audio_format         | Probe, Plex                                     | Probe > Plex                                        | normalized strings ("stereo","mono","5.1")                   | "2.0"→"stereo"                                             |
| closed_captions      | Probe, Sidecar                                  | Probe > Sidecar                                     | boolean                                                      | "Yes"→true                                                 |
| subtitles            | Probe, Sidecar                                  | Probe > Sidecar                                     | BCP-47 codes; dedupe                                         | ["EN","en"]→["en"]                                         |
| poster_image_url     | Sidecar, Plex                                   | Sidecar > Plex                                      | trim; valid URL; https preferred                             | `http://...`→`https://...`                                 |
| backdrop_image_url   | Sidecar, Plex                                   | Sidecar > Plex                                      | trim; valid URL; https preferred                             | `http://...`→`https://...`                                 |
| thumbnail_url        | Generated, Plex, Sidecar                        | Sidecar > Plex > Generated                           | trim; valid URL                                              | generated frame URL                                        |
| credits              | Manual, Sidecar, Plex, AI                       | Manual/Sidecar > Plex > AI                           | {name,role?,character?}; trim names; dedupe                  | "Doe, Jane (Director)"→{name:"Jane Doe",role:"director"}   |
| external_ids         | Plex, Sidecar, Manual                           | Plex > Sidecar > Manual                              | validate per provider; strip prefixes; lowercase keys         | `imdb://tt123`→{imdb_id:"tt123"}                           |
| source_name          | Importer                                        | Importer only                                        | enum: `plex`,`filesystem`,`sidecar`                          | "plex"                                                     |
| source_uid           | Importer                                        | Importer only                                        | opaque, stable per importer                                  | `plex://library/metadata/12345`                            |
| source_path          | Importer                                        | Filesystem importer only                             | normalized absolute path                                     | `X:\TV\...\S01E02.mkv`                                     |
| file_sha256          | Probe                                           | Probe only                                           | lowercase hex; 64 chars                                      | `7B1E...`→`7b1e...`                                        |
| canonical_key        | Derived                                         | Derived only                                         | canonical builder; lowercase; stable                         | `series:retro-hour|s01e02`                                 |
| ai_summary           | AI, Manual                                      | Manual > AI                                          | trim; collapse spaces                                        | AI text→concise paragraph                                  |
| ai_keywords          | AI, Manual                                      | Manual > AI                                          | lowercase; dedupe                                            | ["Retro","retro"]→["retro"]                                |
| ai_genres            | AI, Manual                                      | Manual > AI                                          | lowercase; map to vocab; dedupe                              | ["Variety"]→["variety"]                                    |
| ai_tone              | AI, Manual                                      | Manual > AI                                          | enum; lowercase                                              | "Whimsical"→"whimsical"                                    |

---

### Series-specific fields

| Field           | Possible Sources              | Resolution (High→Low)          | Normalization Rules      | Example                                   |
|-----------------|------------------------------|--------------------------------|-------------------------|-------------------------------------------|
| studio          | Manual, Sidecar, Plex         | Manual/Sidecar > Plex           | trim; preserve case      | "RetroWorks  "→"RetroWorks"               |
| network         | Manual, Sidecar, Plex         | Manual/Sidecar > Plex           | trim; preserve case      | "WXYZ"→"WXYZ"                             |
| seasons_count   | Derived                       | Derived only                    | int; ≥0                  | computed from Episodes                     |
| episode_count   | Derived                       | Derived only                    | int; ≥0                  | computed from Episodes                     |
| franchise_id    | Manual, Sidecar               | Manual/Sidecar only             | UUIDv4                   | `f9a0...`                                  |

---

### Episode-specific fields

| Field                    | Possible Sources             | Resolution (High→Low)             | Normalization Rules          | Example                                 |
|--------------------------|-----------------------------|------------------------------------|-----------------------------|-----------------------------------------|
| series_id                | Resolver                    | Resolver only                      | valid foreign key            | matched Series UUID                      |
| season_number            | Filename, Plex, Sidecar     | Filename > Plex > Sidecar          | int; ≥0                      | "S01E02"→1                               |
| episode_number           | Filename, Plex, Sidecar     | Filename > Plex > Sidecar          | int; ≥0                      | "S01E02"→2                               |
| absolute_episode_number  | Manual, Sidecar             | Manual/Sidecar only                | int; ≥1                      | "3"→3                                    |
| production_code          | Manual, Sidecar, Plex       | Manual/Sidecar > Plex              | trim; preserve case           | "RH-102"                                 |

---

### Movie-specific fields

| Field      | Possible Sources       | Resolution (High→Low)         | Normalization Rules          | Example                                                  |
|------------|-----------------------|-------------------------------|-----------------------------|----------------------------------------------------------|
| directors  | Manual, Sidecar, Plex | Manual/Sidecar > Plex         | credits normalization        | "J. Director"→{name:"J. Director"}                       |
| writers    | Manual, Sidecar, Plex | Manual/Sidecar > Plex         | credits normalization        | "S. Writer"→{name:"S. Writer"}                           |
| cast       | Manual, Sidecar, Plex | Manual/Sidecar > Plex         | credits normalization        | "Lead Star as Alex"→{name:"Lead Star", character:"Alex"} |

---

### Bumper-specific fields

| Field      | Possible Sources           | Resolution (High→Low)        | Normalization Rules    | Example                         |
|------------|---------------------------|------------------------------|-----------------------|---------------------------------|
| bump_type  | Manual, Sidecar, AI       | Manual/Sidecar > AI          | enum map              | "Station ID"→"station_id"       |
| era        | Manual, Sidecar, AI       | Manual/Sidecar > AI          | enum decade label      | "80s"→"1980s"                   |
| network    | Manual, Sidecar           | Manual/Sidecar               | trim                  | "WXYZ  "→"WXYZ"                  |

---

### Promo-specific fields

| Field                | Possible Sources         | Resolution (High→Low)     | Normalization Rules                    | Example                          |
|----------------------|-------------------------|---------------------------|----------------------------------------|----------------------------------|
| promoted_asset_type  | Manual, Sidecar         | Manual/Sidecar only       | enum: series/movie/episode             | "Series"→"series"                |
| promoted_asset_id    | Resolver                | Resolver only             | valid foreign key                      | Series UUID                      |
| campaign_name        | Manual, Sidecar         | Manual/Sidecar            | trim                                   | "Season 3 Launch"                |
| air_window_start     | Manual, Sidecar         | Manual/Sidecar            | ISO date                               | "09/01/1989"→1989-09-01          |
| air_window_end       | Manual, Sidecar         | Manual/Sidecar            | ISO date; must be ≥ start              | "10/01/1989"→1989-10-01          |
| call_to_action       | Manual, Sidecar         | Manual/Sidecar            | trim; collapse spaces                  | "Saturdays 8/7c"                 |
| network              | Manual, Sidecar         | Manual/Sidecar            | trim                                   | "WXYZ"                            |

---

### Ad-specific fields

| Field                  | Possible Sources         | Resolution (High→Low)       | Normalization Rules             | Example                                  |
|------------------------|-------------------------|-----------------------------|---------------------------------|------------------------------------------|
| advertiser             | Manual, Sidecar         | Manual/Sidecar              | trim; preserve case             | "Tasty Cereal Co."                       |
| product                | Manual, Sidecar         | Manual/Sidecar              | trim                            | "Tasty Cereal Classic"                   |
| campaign_name          | Manual, Sidecar         | Manual/Sidecar              | trim                            | "Kids Breakfast '89"                     |
| air_date               | Manual, Sidecar         | Manual/Sidecar              | ISO date                        | "3/12/1989"→1989-03-12                   |
| air_window_start       | Manual, Sidecar         | Manual/Sidecar              | ISO date                        | 1989-03-01                               |
| air_window_end         | Manual, Sidecar         | Manual/Sidecar              | ISO date; must be ≥ start        | 1989-06-01                               |
| region                 | Manual, Sidecar         | Manual/Sidecar              | ISO 3166-1 alpha-2              | "us"→"US"                                |
| regulatory_disclaimers | Manual, Sidecar         | Manual/Sidecar              | trim each; dedupe               | ["Part of a balanced breakfast"]          |
| content_warnings       | Manual, Sidecar, AI     | Manual/Sidecar > AI         | lowercase; enum map             | ["Alcohol"]→["alcohol"]                  |

---

### Block-specific fields

| Field                        | Possible Sources      | Resolution (High→Low)      | Normalization Rules        | Example                              |
|------------------------------|----------------------|----------------------------|---------------------------|--------------------------------------|
| title                        | Manual, Sidecar      | Manual/Sidecar             | trim; preserve case        | "Saturday Morning (Mar 12, 1989)"   |
| date                         | Manual, Sidecar      | Manual/Sidecar             | ISO date                   | "03/12/1989"→1989-03-12             |
| lineup.position              | Manual, Sidecar      | Manual/Sidecar             | int; ≥1                    | "1"→1                               |
| lineup.asset_type            | Manual, Sidecar      | Manual/Sidecar             | enum                       | "Episode"→"episode"                 |
| lineup.asset_id              | Resolver             | Resolver only              | valid foreign key           | "e2d3..."                           |
| lineup.scheduled_runtime_seconds | Manual, Sidecar  | Manual/Sidecar             | int; ≥0                     | "1487"→1487                         |
| lineup.start_offset_seconds  | Manual, Sidecar      | Manual/Sidecar             | int; ≥0                     | "0"→0                               |
| lineup.notes                 | Manual, Sidecar      | Manual/Sidecar             | trim                        | "Use restored cut"                  |

---

### Notes on implementation

- Failed normalization: If a value cannot be normalized (e.g., invalid date), drop the
  field from that source and continue resolving with lower-priority sources.
- Provenance: Importers should keep internal provenance for debugging; the final
  persisted row contains only the resolved value(s).
- Idempotency: Re-running import with the same inputs should produce the same
  resolved values.
