"""Contract tests for INV-ASSET-TAG-PERSISTENCE-001.

Every tag assigned to an asset MUST be persisted in the asset_tags normalized
association table with its normalized form, and MUST be returned verbatim on
any subsequent read. Tags MUST NOT be stored only in JSONB payloads.

Rules:
1. A tag written to asset_tags MUST be readable back verbatim (round-trip).
2. The canonical tag set MUST live in asset_tags, NOT only in asset_editorial.payload.
"""

import uuid

import pytest

from retrovue.domain.entities import AssetTag
from retrovue.domain.tag_normalization import normalize_tag, normalize_tag_set


# ---------------------------------------------------------------------------
# Rule 1: Tags survive a round-trip through normalization
# ---------------------------------------------------------------------------

class TestRuleTagRoundTrip:
    """Rule 1: normalize_tag(tag) is stable under a second application."""

    # Tier: 2 | Scheduling logic invariant
    def test_lowercase_string_is_stable(self):
        """A pre-normalized tag must be returned verbatim."""
        tag = "hbo"
        result = normalize_tag(tag)
        assert result == tag, (
            f"INV-ASSET-TAG-PERSISTENCE-001 Rule 1: "
            f"normalize_tag({tag!r}) changed a normalized tag: got {result!r}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_normalization_is_idempotent(self):
        """Applying normalize_tag twice MUST yield the same result as once."""
        raw = "  HBO Max  "
        once = normalize_tag(raw)
        twice = normalize_tag(once)
        assert once == twice, (
            f"INV-ASSET-TAG-PERSISTENCE-001 Rule 1: "
            f"normalize_tag is not idempotent: once={once!r}, twice={twice!r}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_assetag_model_accepts_normalized_tag(self):
        """AssetTag must be constructible with a normalized tag value."""
        asset_id = uuid.uuid4()
        tag_obj = AssetTag(asset_uuid=asset_id, tag="hbo", source="ingest")
        assert tag_obj.tag == "hbo", (
            f"INV-ASSET-TAG-PERSISTENCE-001 Rule 1: "
            f"AssetTag.tag round-trip failed: {tag_obj.tag!r}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_normalize_tag_set_deduplicates(self):
        """normalize_tag_set must deduplicate normalized duplicates."""
        result = normalize_tag_set(["HBO", "hbo", "  HBO  "])
        assert result == ["hbo"], (
            f"INV-ASSET-TAG-PERSISTENCE-001 Rule 1: "
            f"normalize_tag_set did not deduplicate: {result!r}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_normalize_tag_set_sorts(self):
        """normalize_tag_set must return a sorted list."""
        result = normalize_tag_set(["zebra", "apple", "mango"])
        assert result == sorted(result), (
            f"INV-ASSET-TAG-PERSISTENCE-001 Rule 1: "
            f"normalize_tag_set result is not sorted: {result!r}"
        )


# ---------------------------------------------------------------------------
# Rule 2: Tags must NOT be stored only in JSONB; asset_tags is canonical
# ---------------------------------------------------------------------------

class TestRuleTagNotOnlyInJsonb:
    """Rule 2: AssetTag model exists and is the canonical storage mechanism."""

    # Tier: 2 | Scheduling logic invariant
    def test_assetag_class_exists_with_required_columns(self):
        """AssetTag MUST exist with asset_uuid, tag, source, created_at columns."""
        assert hasattr(AssetTag, "__tablename__"), (
            "INV-ASSET-TAG-PERSISTENCE-001 Rule 2: AssetTag has no __tablename__"
        )
        assert AssetTag.__tablename__ == "asset_tags", (
            f"INV-ASSET-TAG-PERSISTENCE-001 Rule 2: "
            f"expected __tablename__='asset_tags', got {AssetTag.__tablename__!r}"
        )
        table_cols = {c.name for c in AssetTag.__table__.columns}
        for col in ("asset_uuid", "tag", "source", "created_at"):
            assert col in table_cols, (
                f"INV-ASSET-TAG-PERSISTENCE-001 Rule 2: "
                f"AssetTag is missing required column {col!r}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_asset_has_tags_relationship(self):
        """Asset.tags relationship MUST exist to support eager/lazy loading."""
        from retrovue.domain.entities import Asset
        assert hasattr(Asset, "tags"), (
            "INV-ASSET-TAG-PERSISTENCE-001 Rule 2: Asset has no 'tags' relationship"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_assetag_primary_key_is_composite(self):
        """Primary key MUST be (asset_uuid, tag) — ensures uniqueness per asset."""
        pk_cols = {c.name for c in AssetTag.__table__.primary_key.columns}
        assert pk_cols == {"asset_uuid", "tag"}, (
            f"INV-ASSET-TAG-PERSISTENCE-001 Rule 2: "
            f"Expected PK (asset_uuid, tag), got {pk_cols}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_assetag_source_has_default(self):
        """source column MUST have a server_default (operator is default provenance)."""
        source_col = AssetTag.__table__.c["source"]
        assert source_col.server_default is not None, (
            "INV-ASSET-TAG-PERSISTENCE-001 Rule 2: "
            "AssetTag.source must have a server_default"
        )
