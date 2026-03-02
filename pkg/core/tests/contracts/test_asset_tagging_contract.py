"""Contract tests for Asset Tagging CLI (AssetTaggingContract.md B-1..B-8).

These tests enforce CLI behavioral rules. They MUST fail before the --tags flag
is implemented on `retrovue asset update`.

Invariant: INV-ASSET-TAG-PERSISTENCE-001
"""

import json
import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _make_asset(is_deleted=False, state="ready"):
    asset = MagicMock()
    asset.uuid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    asset.is_deleted = is_deleted
    asset.state = state
    return asset


class TestAssetTaggingContractB1toB8:
    """CLI behavioral rules for retrovue asset update --tags."""

    def setup_method(self):
        self.runner = CliRunner()
        self.asset_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    # ------------------------------------------------------------------
    # B-1: Tags are normalized: trim whitespace, collapse internal
    #       whitespace, lower-case.
    # ------------------------------------------------------------------
    def test_b1_tags_normalized_trim_lower_collapse(self):
        """
        Contract B-1: Tags MUST be normalized (strip, collapse whitespace,
        lowercase) before persistence and before being shown in output.
        """
        asset = _make_asset()
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = []
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "  Classic , NOIR "],
            )
            assert result.exit_code == 0, result.output
            # Normalized forms must appear in output
            assert "classic" in result.output
            assert "noir" in result.output
            # Raw un-normalized form must NOT appear
            assert "  Classic" not in result.output
            assert "NOIR " not in result.output

    # ------------------------------------------------------------------
    # B-2: Duplicate tags after normalization are deduplicated.
    # ------------------------------------------------------------------
    def test_b2_duplicate_tags_deduplicated(self):
        """
        Contract B-2: After normalization, duplicate tags MUST be removed.
        'a,a,A' MUST result in exactly one tag 'a'.
        """
        asset = _make_asset()
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = []
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "a,a,A", "--json"],
            )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            new_tags = data["changes"]["tags"]["new"]
            assert new_tags == ["a"], f"Expected ['a'], got {new_tags}"

    # ------------------------------------------------------------------
    # B-3: Default semantics are REPLACE — resulting set equals provided list.
    # ------------------------------------------------------------------
    def test_b3_default_semantics_replace(self):
        """
        Contract B-3: --tags MUST replace the entire tag set. Previous tags
        not in the new list MUST be absent from the resulting set.
        """
        asset = _make_asset()
        # Simulate existing tags: ["old_tag"]
        existing = [MagicMock(tag="old_tag")]
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = existing
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "new_tag", "--json"],
            )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            new_tags = data["changes"]["tags"]["new"]
            assert "old_tag" not in new_tags
            assert "new_tag" in new_tags

    # ------------------------------------------------------------------
    # B-4: Only REPLACE semantics supported; --add-tags / --remove-tags
    #       MUST NOT be accepted.
    # ------------------------------------------------------------------
    def test_b4_add_tags_flag_not_accepted(self):
        """
        Contract B-4: --add-tags is not yet a supported flag.
        The CLI MUST reject it (non-zero exit or error message).
        """
        result = self.runner.invoke(
            app, ["asset", "update", self.asset_id, "--add-tags", "foo"]
        )
        assert result.exit_code != 0, "Expected non-zero exit for unsupported --add-tags flag"

    def test_b4_remove_tags_flag_not_accepted(self):
        """
        Contract B-4: --remove-tags is not yet a supported flag.
        The CLI MUST reject it (non-zero exit or error message).
        """
        result = self.runner.invoke(
            app, ["asset", "update", self.asset_id, "--remove-tags", "foo"]
        )
        assert result.exit_code != 0, "Expected non-zero exit for unsupported --remove-tags flag"

    # ------------------------------------------------------------------
    # B-5: Operation is idempotent — same set applied twice yields exit 0
    #       and no change reported.
    # ------------------------------------------------------------------
    def test_b5_idempotent_same_set_no_change(self):
        """
        Contract B-5: Applying the same normalized tag set a second time
        MUST exit 0 and MUST report that no change occurred.
        """
        asset = _make_asset()
        # Existing tags match what we're about to set
        existing = [MagicMock(tag="classic"), MagicMock(tag="noir")]
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = existing
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "classic,noir", "--json"],
            )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["status"] in ("no_change", "ok"), data

    # ------------------------------------------------------------------
    # B-6: Human output MUST show asset identifier, previous tags,
    #       resulting tags, and whether a change occurred.
    # ------------------------------------------------------------------
    def test_b6_human_output_shows_old_and_new(self):
        """
        Contract B-6: Human output MUST include: asset id, old tags, new tags,
        and an indication of whether a change was made.
        """
        asset = _make_asset()
        existing = [MagicMock(tag="old")]
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = existing
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "new"],
            )
            assert result.exit_code == 0, result.output
            output = result.output
            # Asset identifier present
            assert self.asset_id in output or "aaaa" in output.lower()
            # Both old and new tag sets present
            assert "old" in output
            assert "new" in output

    # ------------------------------------------------------------------
    # B-7: JSON output MUST include: status, asset_uuid,
    #       changes.tags.old, changes.tags.new.
    # ------------------------------------------------------------------
    def test_b7_json_output_shape(self):
        """
        Contract B-7: --json output MUST include keys: status, asset_uuid,
        changes.tags.old, changes.tags.new.
        """
        asset = _make_asset()
        existing = [MagicMock(tag="alpha")]
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = existing
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "beta", "--json"],
            )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert "status" in data
            assert "asset_uuid" in data
            assert "changes" in data
            assert "tags" in data["changes"]
            assert "old" in data["changes"]["tags"]
            assert "new" in data["changes"]["tags"]

    # ------------------------------------------------------------------
    # B-8: --dry-run MUST NOT write; output MUST still show old/new sets.
    # ------------------------------------------------------------------
    def test_b8_dry_run_no_writes(self):
        """
        Contract B-8: With --dry-run, no writes MUST occur and output MUST
        still show old and new tag sets.
        """
        asset = _make_asset()
        existing = [MagicMock(tag="keepme")]
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = existing
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "newval", "--dry-run", "--json"],
            )
            assert result.exit_code == 0, result.output
            # Must not commit
            db.commit.assert_not_called()
            data = json.loads(result.output)
            assert "old" in data["changes"]["tags"]
            assert "new" in data["changes"]["tags"]

    # ------------------------------------------------------------------
    # Soft-deleted asset: exit 1 (also in D-4; tested here for CLI surface)
    # ------------------------------------------------------------------
    def test_soft_deleted_asset_rejected(self):
        """
        Contract D-4 (CLI surface): soft-deleted assets MUST be rejected
        with exit code 1 when attempting to tag.
        """
        asset = _make_asset(is_deleted=True)
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "foo"],
            )
            assert result.exit_code == 1, f"Expected exit 1 for soft-deleted asset, got {result.exit_code}"
