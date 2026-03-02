# INV-ASSET-TAG-PERSISTENCE-001

## Statement

Every tag assigned to an asset — whether via ingest-time path inference or an operator
`asset update --tags` action — MUST be persisted as a row in the `asset_tags` normalized
association table with its normalized form, and MUST be returned verbatim on any subsequent
read of that table.

Tags MUST NOT be stored only in JSONB payloads (e.g., `asset_editorial.payload`).
`asset_tags` is the canonical, queryable source of truth for asset tags.

## Canonical Pattern

```python
# Writing
from retrovue.domain.tag_normalization import normalize_tag_set
from retrovue.domain.entities import AssetTag

normalized = normalize_tag_set(raw_tags)   # strip, lower, dedup, sort
for tag in normalized:
    session.merge(AssetTag(asset_uuid=asset.uuid, tag=tag, source=source))
session.commit()

# Reading
tags = session.query(AssetTag).filter_by(asset_uuid=asset.uuid).all()
tag_strings = [t.tag for t in tags]
# tag_strings == normalized (verbatim round-trip guaranteed)
```

## Affected Components

- `pkg/core/src/retrovue/domain/entities.py` — `AssetTag` model, `Asset.tags` relationship
- `pkg/core/src/retrovue/domain/tag_normalization.py` — normalization primitives
- `pkg/core/src/retrovue/cli/commands/_ops/collection_ingest_service.py` — ingest-time persistence
- `pkg/core/src/retrovue/cli/commands/asset.py` — operator-time persistence (`asset update --tags`)
- `pkg/core/alembic/versions/*_add_asset_tags_table.py` — schema migration

## Failure Modes

- Tags stored only in `asset_editorial.payload` are not queryable by tag-filter operations;
  they will be silently lost on metadata replacement.
- Tags stored without normalization violate deduplication guarantees (B-2, D-2).
- Tags written outside a Unit of Work can produce partial state on failure.

## Origin

Defined to enforce AssetTaggingContract.md D-1 and D-2, which require a normalized association
table and write-time normalization enforcement.

## Test Coverage

- `pkg/core/tests/contracts/runtime/test_inv_asset_tag_persistence.py`
  - `TestRuleTagRoundTrip` — writes a tag, queries it, asserts verbatim equality
  - `TestRuleTagNotOnlyInJsonb` — confirms canonical tag set lives in `asset_tags`, not JSONB
