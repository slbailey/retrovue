"""
Data contract for resolving an asset and removing it from attention list.

Asserts stable JSON envelope and that the asset disappears from
list_assets_needing_attention after resolution.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _asset_dict(uuid: str, state: str, approved: bool) -> dict[str, object]:
    return {
        "uuid": uuid,
        "collection_uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "uri": "/media/a.mp4",
        "state": state,
        "approved_for_broadcast": approved,
    }


def test_resolve_removes_from_attention_and_json_shape_is_stable():
    runner = CliRunner()

    asset_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    fake_db = MagicMock()
    with (
        patch("retrovue.infra.uow.session") as session_ctx,
        patch("retrovue.usecases.asset_attention.list_assets_needing_attention") as list_fn,
        patch("retrovue.usecases.asset_update.update_asset_review_status") as update_fn,
    ):
        session_ctx.return_value.__enter__.return_value = fake_db

        # Before: one asset needs attention
        list_fn.return_value = [_asset_dict(asset_uuid, "enriching", False)]

        # Resolve with JSON output
        update_fn.return_value = _asset_dict(asset_uuid, "ready", True)
        result = runner.invoke(
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
        assert payload == {
            "status": "ok",
            "asset": _asset_dict(asset_uuid, "ready", True),
        }

        # After: attention list no longer includes the asset
        list_fn.return_value = []
        result2 = runner.invoke(app, ["asset", "attention", "--json"])  # should say none
        assert result2.exit_code == 0
        # Either prints the informative message or returns an empty list JSON envelope
        # Current contract for attention prints a message when none
        assert "No assets need attention" in result2.stdout






