### RetroVue Metadata Enrichment Framework (v0.1)

Last updated: 2025-11-02

This document explains how RetroVue extends metadata beyond importer-provided fields, the
enrichment lifecycle, supported enrichers, storage model for enriched data, example
transformations, and versioning/provenance tracking.

Related docs:
- Taxonomy: `docs/metadata/metadata-taxonomy.md`
- Sources and resolution: `docs/metadata/metadata-sources.md`

---

### Enrichment lifecycle

High-level flow: ingest → normalize → enrich → persist → expose

1) Ingest
- Importer produces raw metadata plus technical probe outputs and `source_uri`.
- Minimal normalization (types, trimming) is applied by the importer where safe.

2) Normalize
- Apply full normalization and resolution rules (see Sources doc) to produce the resolved
  baseline record for the entity (e.g., `episode`, `movie`).
- At this stage, fields are filled from manual/sidecar, platform, tags, filename, etc.

3) Enrich
- Run zero or more enrichers to augment the baseline with additional, derived, or inferred data.
- Enrichers output into designated `ai_*` fields or propose candidate updates to existing fields
  (e.g., genre refinement suggestions).
- Enrichment results are recorded with provenance; conflicts are handled by resolution priorities
  (Manual/Sidecar > Platform/Tags > AI; with technical fields never overridden by AI).

4) Persist
- Persist the current values for `ai_*` fields directly on the asset row.
- Persist a detailed `enrichment_event` entry for each enricher run (versioned log).
- Optionally persist suggested promotions/refinements in a separate suggestion object for review.

5) Expose
- API/CLI present both resolved fields and enriched fields. Resolution rules may allow enriched
  data to backfill missing editorial fields (e.g., `genres` if absent), but never override
  higher-priority sources automatically.

Idempotency and safety
- Enrichers must be idempotent per input hash; re-running with identical inputs should produce the
  same outputs and avoid duplicative events.
- Enrichers must not modify technical fields (`runtime_seconds`, `resolution`, ...).

---

### Supported enrichers

| Enricher key | Description | Inputs | Outputs | Notes |
| --- | --- | --- | --- | --- |
| `ai_summary` | Generates concise summary of content | title, description, transcripts (optional), thumbnails | `ai_summary` (string) | Max ~700 chars; neutral tone |
| `genre_classifier` | Refines/infers genres/subgenres | title, description, existing genres | `ai_genres` (array[string]), `subgenres` (suggested) | Maps to controlled vocab; confidence per label |
| `tone_classifier` | Infers tone/mood | title, description | `ai_tone` (enum), `mood` (array[string]) | Vocab from taxonomy |
| `keyword_extractor` | Extracts topical keywords | title, description | `ai_keywords` (array[string]) | Lowercase, deduped |
| `commercial_tagger` | Detects commercial subtypes | ad/break content, OCR (optional) | `content_warnings`, `campaign_name` (suggested) | For `ad` assets only |
| `decade_infer` | Derives decade from dates | production_year, release_date | `decade` (enum) | Simple mapping; not AI |

Configuration knobs
- Per enricher: `enabled`, `model_id` (if AI), `max_tokens`/`temperature` (if AI), `confidence_threshold`.
- Per asset type: enable/disable specific enrichers (e.g., skip `commercial_tagger` for `movie`).

---

### Storage model for enriched data

Current values (on `Asset`)
- Enriched fields are stored in first-class columns where specified by the taxonomy:
  - `ai_summary` (text)
  - `ai_keywords` (text[])
  - `ai_genres` (text[])
  - `ai_tone` (text/enum)
  - Other non-AI enrichments that are deterministic (e.g., `decade`) may directly populate the
    canonical field.
- These columns are considered the latest resolved enriched values. They follow the source
  priority defined in `metadata-sources.md` (Manual > Platform/Tags > AI).

Event log (append-only provenance)

`enrichment_event` (one row per enricher run and asset)

| Column | Type | Notes |
| --- | --- | --- |
| enrichment_id | uuid | PK |
| asset_id | uuid | FK → Asset |
| enricher_key | text | e.g., `ai_summary`, `genre_classifier` |
| enricher_version | text | model or algorithm version (e.g., `gpt-4o-2025-08-12`, `clf-v3.1`) |
| input_hash | text | hash of the inputs considered (for idempotency) |
| input_snapshot | jsonb | optional copy of relevant inputs (sanitized) |
| output_json | jsonb | full machine output before normalization |
| normalized_fields | jsonb | fields written to the Asset (`{"ai_summary":"..."}`) |
| confidence | numeric | 0..1 averaged or per-field breakdown |
| created_by | text | `system:ai`, `system:classifier`, or `human` |
| created_at | timestamptz | timestamp of write |
| supersedes_enrichment_id | uuid | optional pointer to previous event superseded |
| trace_url | text | link to external logs if applicable |

Optional: suggestions table (for proposed promotions)

`enrichment_suggestion`

| Column | Type | Notes |
| --- | --- | --- |
| suggestion_id | uuid | PK |
| asset_id | uuid | FK → Asset |
| field | text | e.g., `genres` |
| proposed_value | jsonb | normalized candidate value |
| source_enrichment_id | uuid | FK → `enrichment_event` |
| confidence | numeric | 0..1 |
| status | text | `pending` | `accepted` | `rejected` |
| reviewed_by | text | nullable |
| reviewed_at | timestamptz | nullable |

---

### Before/after examples

Episode (before enrichment)
```json
{
  "asset_type": "episode",
  "title": "Retro Hour - S01E02",
  "description": "Part two of the pilot.",
  "genres": ["comedy"],
  "ai_summary": null,
  "ai_keywords": [],
  "ai_genres": [],
  "ai_tone": null
}
```

Run `ai_summary`, `keyword_extractor`, and `genre_classifier`

Episode (after enrichment)
```json
{
  "asset_type": "episode",
  "title": "Retro Hour - S01E02",
  "description": "Part two of the pilot.",
  "genres": ["comedy"],
  "ai_summary": "The crew wraps the two-part premiere with a nostalgic variety of skits and throwback bits.",
  "ai_keywords": ["retro","pilot","variety","sketch"],
  "ai_genres": ["variety","talk"],
  "ai_tone": "whimsical"
}
```

If `genres` were empty, resolution rules may allow `ai_genres` to backfill `genres`.
Manual edits to `genres` would always take precedence over `ai_genres`.

Ad (before/after commercial tagging)
```json
// before
{ "asset_type": "ad", "title": "Tasty Cereal — 30s", "content_warnings": [] }
// after
{ "asset_type": "ad", "title": "Tasty Cereal — 30s", "content_warnings": ["sugar"] }
```

---

### Versioning and provenance

Versioning
- Each enricher declares `enricher_key` and `enricher_version`. Changing the model or algorithm
  increments the version.
- Re-running with a new version appends a new `enrichment_event` and may update current `ai_*`
  fields if the new output is accepted (automatically or via review/policy).

Provenance and audit
- Each write to `ai_*` fields is accompanied by a corresponding `enrichment_event` row capturing
  inputs, normalized outputs, confidence, and actor (`created_by`).
- The `input_hash` ensures idempotency and allows traceability of exact inputs that produced the
  outputs.
- The optional `trace_url` can link to external job logs.

Rollbacks and supersession
- Accepting a suggestion or new event may mark a previous event as superseded via
  `supersedes_enrichment_id`.
- Rollback can restore prior `ai_*` values using the normalized snapshot stored in the event log.

Security and safety
- Do not store raw media in events; store small inputs (e.g., truncated transcripts) or hashes.
- PII and sensitive content should be redacted from `input_snapshot` where applicable.

---

### Integration with resolution priority

- Enriched fields are low priority compared to manual/sidecar and platform metadata. See
  `metadata-sources.md` for per-field priorities.
- Technical fields must not be enriched or overridden by AI.
- Backfill policy: When an editorial field is missing, a configured policy may promote enriched
  values to populate it (e.g., set `genres = ai_genres` if `genres` is empty).



