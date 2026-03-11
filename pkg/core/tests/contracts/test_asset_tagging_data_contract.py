"""Data contract tests for Asset Tagging (AssetTaggingContract.md D-1..D-5).

These tests enforce persistence and data integrity guarantees.
They MUST fail before the asset_tags table + persistence logic is implemented.

Invariant: INV-ASSET-TAG-PERSISTENCE-001
"""

import uuid
from unittest.mock import MagicMock, call, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _make_asset(is_deleted=False, state="ready"):
    asset = MagicMock()
    asset.uuid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    asset.is_deleted = is_deleted
    asset.state = state
    return asset


class TestAssetTaggingDataContractD1toD5:
    """Persistence and data integrity rules for asset tagging."""

    def setup_method(self):
        self.runner = CliRunner()
        self.asset_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    # ------------------------------------------------------------------
    # D-1: Tags are stored in a normalized association (asset_tags join
    #       table), unique per asset after normalization.
    # ------------------------------------------------------------------
    def test_d1_tags_stored_in_asset_tags_table(self):
        """
        Contract D-1 / INV-ASSET-TAG-PERSISTENCE-001: Tags MUST be written
        to the asset_tags table (not only to JSONB payloads).
        AssetTag rows MUST be created for each tag in the final set.
        """
        from retrovue.domain.entities import AssetTag

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
                ["asset", "update", self.asset_id, "--tags", "hbo,1982"],
            )
            assert result.exit_code == 0, result.output

            # Verify rows were added via session.add or session.merge for AssetTag instances
            all_calls = db.add.call_args_list + db.merge.call_args_list
            tag_objects = [
                c.args[0] for c in all_calls
                if isinstance(c.args[0] if c.args else None, AssetTag)
            ]
            added_tags = {t.tag for t in tag_objects}
            # D-6: CLI writes namespaced tags (TAG: prefix for plain values)
            assert "TAG:hbo" in added_tags, f"Expected 'TAG:hbo' in {added_tags}"
            assert "TAG:1982" in added_tags, f"Expected 'TAG:1982' in {added_tags}"

    # ------------------------------------------------------------------
    # D-2: Tag normalization enforced on write; persisted values are
    #       normalized forms.
    # ------------------------------------------------------------------
    def test_d2_normalization_enforced_on_write(self):
        """
        Contract D-2 / INV-ASSET-TAG-PERSISTENCE-001: Persisted AssetTag
        rows MUST use normalized (lowercase, stripped) tag values.
        Un-normalized forms ('HBO', '  1982 ') MUST NOT be persisted.
        """
        from retrovue.domain.entities import AssetTag

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
                ["asset", "update", self.asset_id, "--tags", "HBO,  1982  "],
            )
            assert result.exit_code == 0, result.output

            all_calls = db.add.call_args_list + db.merge.call_args_list
            tag_objects = [
                c.args[0] for c in all_calls
                if isinstance(c.args[0] if c.args else None, AssetTag)
            ]
            for tag_obj in tag_objects:
                # D-6: Namespaced tags use uppercase prefix (TAG:, NETWORK:, etc.)
                # The value part after the colon MUST be normalized (lowercase, stripped).
                tag = tag_obj.tag
                if ":" in tag:
                    prefix, value = tag.split(":", 1)
                    assert prefix == prefix.upper(), (
                        f"INV-ASSET-TAG-PERSISTENCE-001: namespace prefix {prefix!r} must be uppercase"
                    )
                    assert value == value.strip().lower(), (
                        f"INV-ASSET-TAG-PERSISTENCE-001: tag value {value!r} is not normalized"
                    )
                else:
                    assert tag == tag.strip().lower(), (
                        f"INV-ASSET-TAG-PERSISTENCE-001: persisted tag {tag!r} is not normalized"
                    )

    # ------------------------------------------------------------------
    # D-3: Updates occur in a single Unit of Work; partial failures
    #       MUST roll back.
    # ------------------------------------------------------------------
    def test_d3_unit_of_work_rollback_on_failure(self):
        """
        Contract D-3: If an exception occurs mid-write, the session MUST be
        rolled back so no partial tag state is committed.
        """
        asset = _make_asset()
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = []
            # Simulate a DB failure on add/merge
            db.add.side_effect = Exception("simulated DB failure")
            db.merge.side_effect = Exception("simulated DB failure")
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "hbo"],
            )
            # Must not exit 0 if write failed
            assert result.exit_code != 0, "Expected non-zero exit on DB failure"
            # Rollback must be called (via context manager __exit__ with exception)
            # The context manager exit with an exception triggers rollback
            assert db.commit.call_count == 0, "commit must not be called on failure"

    # ------------------------------------------------------------------
    # D-4: Soft-deleted assets MUST reject tagging with exit code 1.
    # ------------------------------------------------------------------
    def test_d4_soft_deleted_asset_rejects_tagging(self):
        """
        Contract D-4 / INV-ASSET-TAG-PERSISTENCE-001: An asset with
        is_deleted=True MUST cause the tagging operation to fail with exit 1.
        No writes MUST occur.
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
                ["asset", "update", self.asset_id, "--tags", "any_tag"],
            )
            assert result.exit_code == 1, (
                f"INV-ASSET-TAG-PERSISTENCE-001: soft-deleted asset must reject tagging (exit 1), got {result.exit_code}"
            )
            db.add.assert_not_called()
            db.merge.assert_not_called()
            db.commit.assert_not_called()

    # ------------------------------------------------------------------
    # D-5: Retired assets MAY be tagged; tagging does not alter lifecycle
    #       state.
    # ------------------------------------------------------------------
    def test_d5_retired_asset_accepts_tagging_without_state_change(self):
        """
        Contract D-5: An asset in 'retired' state MUST accept tagging
        (exit 0) and its lifecycle state MUST NOT be changed by the operation.
        """
        asset = _make_asset(state="retired")
        with (
            patch("retrovue.cli.commands.asset.session") as mock_session,
            patch("retrovue.cli.commands.asset.resolve_asset_selector", return_value=asset),
        ):
            db = MagicMock()
            db.query.return_value.filter_by.return_value.all.return_value = []
            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                ["asset", "update", self.asset_id, "--tags", "archive"],
            )
            assert result.exit_code == 0, (
                f"Contract D-5: retired asset must accept tagging, got exit {result.exit_code}: {result.output}"
            )
            # State must not be changed
            assert asset.state == "retired", (
                f"Contract D-5: lifecycle state must not change, got {asset.state}"
            )
