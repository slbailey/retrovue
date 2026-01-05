"""
Contract tests for Asset Resolve command (Milestone 3C).

Verifies minimal operator write path to resolve a single asset:
- approve and/or mark ready
- stable JSON envelope
- correct exit codes and messages
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestAssetResolveContract:
    def setup_method(self):
        self.runner = CliRunner()

    def test_resolve_enriching_asset_with_approve_and_ready(self):
        # Arrange a fake asset object returned by the usecase layer
        fake_asset = SimpleNamespace(
            uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            collection_uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            uri="/media/a.mp4",
            state="enriching",
            approved_for_broadcast=False,
        )

        fake_db = MagicMock()
        # The usecase will call db.add with the mutated object
        def _add(obj):
            assert obj is fake_asset
            return None

        fake_db.add.side_effect = _add

        # Patch session context to yield our fake db, and patch the usecase behavior
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.asset_update.update_asset_review_status"
        ) as update_fn:
            session_ctx.return_value.__enter__.return_value = fake_db
            # Simulate the usecase performing db.add on the same object
            def _side_effect(db, *, asset_uuid: str, approved=None, state=None):  # noqa: ANN001
                fake_db.add(fake_asset)
                return {
                    "uuid": fake_asset.uuid,
                    "collection_uuid": fake_asset.collection_uuid,
                    "uri": fake_asset.uri,
                    "state": "ready",
                    "approved_for_broadcast": True,
                }
            update_fn.side_effect = _side_effect

            # Act
            result = self.runner.invoke(
                app,
                [
                    "asset",
                    "resolve",
                    fake_asset.uuid,
                    "--approve",
                    "--ready",
                ],
            )

        # Assert
        assert result.exit_code == 0
        assert "updated" in result.stdout.lower()
        fake_db.add.assert_called_once()

    def test_missing_asset_exits_one(self):
        with patch("retrovue.infra.uow.session") as session_ctx:
            session_ctx.return_value.__enter__.return_value = MagicMock()
            # Ensure get_asset_summary path also raises not found when flags missing
            with patch(
                "retrovue.usecases.asset_update.update_asset_review_status",
                side_effect=ValueError("Asset not found"),
            ):
                result = self.runner.invoke(
                    app,
                    [
                        "asset",
                        "resolve",
                        "ffffffff-ffff-ffff-ffff-ffffffffffff",
                        "--approve",
                    ],
                )

        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_read_only_mode_displays_info(self):
        """
        Contract: When no flags are provided, the command operates in read-only mode.
        """
        asset_summary = {
            "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "collection_uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "uri": "/media/a.mp4",
            "state": "enriching",
            "approved_for_broadcast": False,
        }

        fake_db = MagicMock()
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.asset_update.get_asset_summary"
        ) as get_fn:
            session_ctx.return_value.__enter__.return_value = fake_db
            get_fn.return_value = asset_summary

            result = self.runner.invoke(
                app,
                [
                    "asset",
                    "resolve",
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                ],
            )

        assert result.exit_code == 0
        assert "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" in result.stdout
        assert "enriching" in result.stdout
        assert "approved=False" in result.stdout
        assert "/media/a.mp4" in result.stdout
        get_fn.assert_called_once()
        call_kwargs = get_fn.call_args[1]
        assert call_kwargs.get("asset_uuid") == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    def test_read_only_mode_json_output(self):
        """
        Contract: Read-only mode supports --json flag.
        """
        asset_summary = {
            "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "collection_uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "uri": "/media/a.mp4",
            "state": "enriching",
            "approved_for_broadcast": False,
        }

        fake_db = MagicMock()
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.asset_update.get_asset_summary"
        ) as get_fn:
            session_ctx.return_value.__enter__.return_value = fake_db
            get_fn.return_value = asset_summary

            result = self.runner.invoke(
                app,
                [
                    "asset",
                    "resolve",
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "--json",
                ],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload == {"status": "ok", "asset": asset_summary}

    def test_json_output_format(self):
        """
        Contract: The command MUST support JSON output with --json flag.
        """
        asset_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        fake_db = MagicMock()
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.asset_update.update_asset_review_status"
        ) as update_fn:
            session_ctx.return_value.__enter__.return_value = fake_db
            update_fn.return_value = {
                "uuid": asset_uuid,
                "collection_uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "uri": "/media/a.mp4",
                "state": "ready",
                "approved_for_broadcast": True,
            }

            result = self.runner.invoke(
                app,
                [
                    "asset",
                    "resolve",
                    asset_uuid,
                    "--approve",
                    "--ready",
                    "--json",
                ],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert "asset" in payload
        assert payload["asset"]["uuid"] == asset_uuid
        assert payload["asset"]["state"] == "ready"
        assert payload["asset"]["approved_for_broadcast"] is True

    def test_single_approve_flag(self):
        """
        Contract: The --approve flag alone sets approved_for_broadcast=True.
        """
        asset_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        fake_db = MagicMock()
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.asset_update.update_asset_review_status"
        ) as update_fn:
            session_ctx.return_value.__enter__.return_value = fake_db
            update_fn.return_value = {
                "uuid": asset_uuid,
                "collection_uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "uri": "/media/a.mp4",
                "state": "enriching",
                "approved_for_broadcast": True,
            }

            result = self.runner.invoke(
                app,
                [
                    "asset",
                    "resolve",
                    asset_uuid,
                    "--approve",
                ],
            )

        assert result.exit_code == 0
        update_fn.assert_called_once()
        call_kwargs = update_fn.call_args[1]
        assert call_kwargs.get("approved") is True
        assert call_kwargs.get("state") is None

    def test_single_ready_flag(self):
        """
        Contract: The --ready flag alone sets state='ready'.
        """
        asset_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        fake_db = MagicMock()
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.asset_update.update_asset_review_status"
        ) as update_fn:
            session_ctx.return_value.__enter__.return_value = fake_db
            update_fn.return_value = {
                "uuid": asset_uuid,
                "collection_uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "uri": "/media/a.mp4",
                "state": "ready",
                "approved_for_broadcast": False,
            }

            result = self.runner.invoke(
                app,
                [
                    "asset",
                    "resolve",
                    asset_uuid,
                    "--ready",
                ],
            )

        assert result.exit_code == 0
        update_fn.assert_called_once()
        call_kwargs = update_fn.call_args[1]
        assert call_kwargs.get("approved") is None
        assert call_kwargs.get("state") == "ready"


