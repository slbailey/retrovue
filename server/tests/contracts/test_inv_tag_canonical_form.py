"""Contract tests for INV-TAG-CANONICAL-FORM-001 and INV-TAG-MIGRATION-IDEMPOTENT-001.

All persisted tags MUST be in `namespace.value` canonical form.
Tag migration from legacy colon format MUST be idempotent.

Reference: docs/contracts/tag_canonical_form.md
"""

from __future__ import annotations

import pytest

from retrovue.domain.tag_normalization import normalize_tag


# ---------------------------------------------------------------------------
# We expect a canonicalize_tag() function to exist per contract E-3.
# ---------------------------------------------------------------------------
try:
    from retrovue.domain.tag_normalization import canonicalize_tag
except ImportError:
    pytestmark = pytest.mark.skip(reason="canonicalize_tag not yet implemented")
    canonicalize_tag = None  # type: ignore[assignment]


# ===========================================================================
# A. Canonical Form — INV-TAG-CANONICAL-FORM-001
# ===========================================================================


class TestCanonicalFormA:
    """Contract section A: tags stored in namespace.value form."""

    def test_a1_plain_tag_gets_tag_namespace(self):
        """A-1/B-2: Plain tag 'hbo' → 'tag.hbo'."""
        assert canonicalize_tag("hbo") == "tag.hbo"

    def test_a1_explicit_namespace_preserved(self):
        """A-1: 'network.cbs' stays 'network.cbs'."""
        assert canonicalize_tag("network.cbs") == "network.cbs"

    def test_a2_namespace_is_lowercase(self):
        """A-2: Namespace must be lowercase."""
        result = canonicalize_tag("GENRE:comedy")
        assert result == "genre.comedy"

    def test_a3_value_is_normalized(self):
        """A-3: Value is stripped, lowercased, whitespace collapsed."""
        assert canonicalize_tag("  HBO Max  ") == "tag.hbo max"

    def test_a4_single_dot_separator(self):
        """A-4: Canonical form has exactly one dot."""
        result = canonicalize_tag("tag.hbo")
        assert result.count(".") == 1

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("tag.hbo", "tag.hbo"),
            ("network.cbs", "network.cbs"),
            ("genre.comedy", "genre.comedy"),
            ("rating.tv-14", "rating.tv-14"),
            ("tag.presentation", "tag.presentation"),
        ],
    )
    def test_a5_canonical_examples(self, raw, expected):
        """A-5: Contract examples must round-trip."""
        assert canonicalize_tag(raw) == expected


# ===========================================================================
# C. Migration Semantics — INV-TAG-MIGRATION-IDEMPOTENT-001
# ===========================================================================


class TestMigrationC:
    """Contract section C: legacy colon-prefixed tags migrate to canonical."""

    @pytest.mark.parametrize(
        "legacy, expected",
        [
            ("TAG:hbo", "tag.hbo"),
            ("NETWORK:cbs", "network.cbs"),
            ("GENRE:comedy", "genre.comedy"),
            ("RATING:tv-14", "rating.tv-14"),
        ],
    )
    def test_c1_colon_prefix_migrated(self, legacy, expected):
        """C-1: Legacy colon-prefixed tags MUST migrate to canonical form."""
        assert canonicalize_tag(legacy) == expected

    @pytest.mark.parametrize("plain, expected", [
        ("hbo", "tag.hbo"),
        ("classic", "tag.classic"),
    ])
    def test_c2_plain_tags_get_tag_namespace(self, plain, expected):
        """C-2: Plain tags with no prefix MUST migrate to tag.{value}."""
        assert canonicalize_tag(plain) == expected

    @pytest.mark.parametrize("canonical", [
        "tag.hbo",
        "network.cbs",
        "genre.comedy",
        "rating.tv-14",
    ])
    def test_c3_migration_is_idempotent(self, canonical):
        """C-3: Applying canonicalize_tag to an already-canonical tag MUST return it unchanged."""
        assert canonicalize_tag(canonical) == canonical
        # Double application
        assert canonicalize_tag(canonicalize_tag(canonical)) == canonical


# ===========================================================================
# D. Backward Compatibility — expand_tag_match_set
# ===========================================================================


class TestBackwardCompatD:
    """Contract section D: expand_tag_match_set must expand canonical tags."""

    def test_d1_canonical_tag_expands_to_all_forms(self):
        """D-1/D-2: Canonical 'tag.hbo' expands to {tag.hbo, TAG:hbo, tag:hbo, hbo}."""
        from retrovue.domain.tag_normalization import expand_tag_match_set

        expanded = expand_tag_match_set({"tag.hbo"})
        # Must match all three historical forms
        assert "tag.hbo" in expanded, "canonical form must be in expanded set"
        assert "hbo" in expanded, "plain form must be in expanded set"
        assert "tag:hbo" in expanded, "legacy colon form must be in expanded set"

    def test_d1_network_canonical_expands(self):
        """D-1: network.cbs expands to {network.cbs, network:cbs, cbs}."""
        from retrovue.domain.tag_normalization import expand_tag_match_set

        expanded = expand_tag_match_set({"network.cbs"})
        assert "network.cbs" in expanded
        assert "cbs" in expanded
        assert "network:cbs" in expanded

    def test_d1_legacy_colon_tags_still_expand(self):
        """D-1: Legacy TAG:hbo in DB still expands correctly during transition."""
        from retrovue.domain.tag_normalization import expand_tag_match_set

        expanded = expand_tag_match_set({"TAG:hbo"})
        assert "hbo" in expanded
        assert "tag:hbo" in expanded


# ===========================================================================
# E. Storage Rules — CLI and ingest write canonical form
# ===========================================================================


class TestStorageE:
    """Contract section E: new tags written in canonical form."""

    def test_e2_cli_writes_canonical_form(self):
        """E-2: CLI 'retrovue asset update --tags hbo' persists 'tag.hbo'."""
        import json
        import uuid
        from unittest.mock import MagicMock, patch

        from typer.testing import CliRunner

        from retrovue.cli.main import app
        from retrovue.domain.entities import AssetTag

        runner = CliRunner()
        asset_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        asset = MagicMock()
        asset.uuid = uuid.UUID(asset_id)
        asset.is_deleted = False
        asset.state = "ready"

        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = []
            mock_session.return_value.__enter__.return_value = db

            result = runner.invoke(app, ["asset", "update", asset_id, "--tags", "hbo,comedy"])
            assert result.exit_code == 0, result.output

            all_calls = db.add.call_args_list + db.merge.call_args_list
            tag_objects = [
                c.args[0] for c in all_calls
                if isinstance(c.args[0] if c.args else None, AssetTag)
            ]
            persisted_tags = {t.tag for t in tag_objects}
            # Must be canonical form, not legacy TAG: form
            assert "tag.hbo" in persisted_tags, f"Expected 'tag.hbo' in {persisted_tags}"
            assert "tag.comedy" in persisted_tags, f"Expected 'tag.comedy' in {persisted_tags}"
            assert not any(":" in t for t in persisted_tags), (
                f"No colon-separated tags should be persisted: {persisted_tags}"
            )
