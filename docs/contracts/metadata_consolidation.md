# Metadata Consolidation Contract

**Status:** Draft
**Owner:** Persistence Governance Engineer
**Parent:** RETA-104 Phase 6B

## Purpose

Extract frequently-queried editorial fields from the `asset_editorial.payload` JSONB column into dedicated, indexed columns on the `asset_editorial` table. This is a **performance optimization** — the JSONB payload remains the extensible store of record; the new columns are a query-optimized projection.

## Motivation

The `catalog_resolver.py` resolver loads **all** `AssetEditorial` rows into memory and extracts `series_title`, `season_number`, `episode_number`, `content_rating`, and `production_year` from JSONB at startup. Pool filtering then operates on these in-memory values. As the catalog grows, this approach has two costs:

1. **Memory** — every editorial JSONB blob is fully deserialized even when only five fields are needed.
2. **Query capability** — SQL-level filtering on JSONB paths cannot use B-tree indexes, preventing future migration to cursor-based or filtered queries.

The `AssetTag` extraction (Phase 5) established the pattern: normalize frequently-queried data into indexed columns while preserving the JSONB payload for extensibility.

## Scope

### In scope

- Add five nullable columns to `asset_editorial`.
- Create B-tree indexes for pool-filter access patterns.
- Backfill columns from existing JSONB payloads via data migration.
- Keep columns in sync during ingest writes (dual-write).
- Update `catalog_resolver.py` to use columns instead of JSONB path extraction.

### Out of scope

- Removing or restructuring the JSONB `payload` column.
- Changing pool match semantics (filtering behavior is unchanged).
- Adding new invariants (this is a performance optimization, not a behavioral change).
- Modifying any other metadata table (`asset_probed`, `asset_station_ops`, `asset_relationships`, `asset_sidecar`).

## Column Definitions

All columns are added to the existing `asset_editorial` table (PK: `asset_uuid`).

| Column | SQL Type | Nullable | Default | Source JSONB path |
|---|---|---|---|---|
| `series_title` | `VARCHAR(512)` | YES | `NULL` | `payload->'series_title'` |
| `season_number` | `INTEGER` | YES | `NULL` | `payload->'season_number'` |
| `episode_number` | `INTEGER` | YES | `NULL` | `payload->'episode_number'` |
| `content_rating` | `VARCHAR(32)` | YES | `NULL` | `payload->'content_rating'->'code'` (if dict) or `payload->'content_rating'` (if string) |
| `production_year` | `INTEGER` | YES | `NULL` | `payload->'production_year'` or `payload->'year'` |

### Notes

- **`series_title`**: Free-text; `VARCHAR(512)` accommodates long international titles. Stored as-is from the editorial payload (no case normalization at the DB level — pool filtering normalizes at query time).
- **`content_rating`**: The editorial payload stores this as either a bare string (`"TV-14"`) or a dict (`{"code": "TV-14", "source": "TVPG"}`). The column stores the resolved `code` string. This matches `catalog_resolver.py` line 218 behavior.
- **`production_year`**: The editorial payload uses either `production_year` or `year` (both are checked by `catalog_resolver.py` line 287). The column normalizes to a single `production_year` value.
- All columns are nullable because not every asset has editorial metadata for every field (e.g., movies lack `season_number`/`episode_number`).

## Index Definitions

```sql
-- Pool filtering: series_title lookups (case-insensitive via lower())
CREATE INDEX ix_asset_editorial_series_title_lower
    ON asset_editorial (lower(series_title));

-- Pool filtering: season/episode range scans
CREATE INDEX ix_asset_editorial_season_episode
    ON asset_editorial (season_number, episode_number);

-- Pool filtering: rating include/exclude
CREATE INDEX ix_asset_editorial_content_rating
    ON asset_editorial (content_rating);

-- Pool filtering: year-based queries
CREATE INDEX ix_asset_editorial_production_year
    ON asset_editorial (production_year);
```

## Migration Semantics

### Schema migration (DDL)

1. `ALTER TABLE asset_editorial ADD COLUMN` for each of the five columns.
2. Create all four indexes.

### Data migration (backfill)

A single `UPDATE` statement populates columns from existing JSONB payloads:

```sql
UPDATE asset_editorial
SET
    series_title = payload->>'series_title',
    season_number = (payload->>'season_number')::INTEGER,
    episode_number = (payload->>'episode_number')::INTEGER,
    content_rating = CASE
        WHEN jsonb_typeof(payload->'content_rating') = 'object'
        THEN payload->'content_rating'->>'code'
        ELSE payload->>'content_rating'
    END,
    production_year = COALESCE(
        (payload->>'production_year')::INTEGER,
        (payload->>'year')::INTEGER
    )
WHERE payload != '{}'::jsonb;
```

### Rollback

- Drop the five columns (cascading index drops). No data loss — JSONB payload is unchanged.

## Dual-Write Rule

**D-1: Write path must populate both JSONB and columns.**

Any code path that writes to `asset_editorial.payload` must also set the corresponding columns. This applies to:

- `container_ingest.py` — primary ingest workflow
- Any future enricher or manual metadata update path

The JSONB payload remains authoritative. If a discrepancy is detected between a column and its JSONB source, the JSONB value wins.

**D-2: Read path prefers columns.**

After migration, `catalog_resolver.py` should read the five indexed columns directly instead of deserializing the full JSONB payload for these fields. The JSONB payload is still loaded for other fields (e.g., `title`, `description`, `genres`, `interstitial_type`).

## Query Changes in catalog_resolver.py

### Before (current)

```python
editorial = editorials.get(uuid_str, {})
series_title = editorial.get("series_title", "")
season_raw = editorial.get("season_number")
episode_raw = editorial.get("episode_number")
rating_raw = editorial.get("content_rating")
production_year = editorial.get("production_year") or editorial.get("year")
```

### After

```python
# Columns read directly from ORM-mapped attributes
series_title = ed.series_title or ""
season = ed.season_number
episode_num = ed.episode_number
rating = ed.content_rating
production_year = ed.production_year
```

The full `payload` is still loaded for fields not promoted to columns (`title`, `description`, `genres`, `interstitial_type`, etc.).

## Backfill Checklist

- [ ] Verify column values match JSONB extraction for all existing rows (post-migration test).
- [ ] Handle `content_rating` dict-vs-string correctly (test both forms).
- [ ] Handle `production_year` / `year` fallback correctly.
- [ ] Verify NULL handling: missing JSONB keys produce NULL columns (not empty strings or zeros).
- [ ] Verify cast safety: non-integer `season_number` / `episode_number` values in JSONB must not crash the migration (use `NULLIF` or `TRY_CAST` pattern if needed).

## Rollback Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| Migration fails mid-backfill | Low | Transaction-wrapped; columns are nullable so partial state is safe |
| Column/JSONB drift after deploy | Medium | D-1 dual-write rule; add reconciliation query to health checks |
| Index bloat on large catalogs | Low | Standard B-tree; monitor with `pg_stat_user_indexes` |
| Rollback needed | Low | Drop columns; catalog_resolver falls back to JSONB extraction (revert code change) |

## Test Obligations

Since this is a performance optimization with no behavioral change, tests verify:

1. **Backfill correctness**: All existing editorial rows have columns matching JSONB extraction.
2. **Dual-write correctness**: New ingest writes populate both JSONB and columns.
3. **content_rating normalization**: Dict and string forms both resolve to the `code` value.
4. **production_year fallback**: `year` key is used when `production_year` is absent.
5. **NULL preservation**: Missing JSONB keys produce NULL columns.
6. **catalog_resolver equivalence**: Pool filtering results are identical before and after the column-read switch.
