"""
Contract tests for ``retrovue asset list``.

Ensures operators can list assets in a container and quickly identify
invalid-duration and non-broadcast-ready assets.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestAssetListContract:
    def setup_method(self):
        self.runner = CliRunner()

    def test_help_flag_exits_zero(self):
        result = self.runner.invoke(app, ["asset", "list", "--help"])
        assert result.exit_code == 0
        assert "List assets in a container" in result.stdout

    def test_requires_container_scope(self):
        result = self.runner.invoke(app, ["asset", "list"])
        assert result.exit_code == 1
        out = result.stderr or result.stdout
        assert "--container" in out

    def test_json_output_includes_duration_and_readiness_signals(self):
        rows = [
            {
                "uuid": "11111111-1111-1111-1111-111111111111",
                "collection_uuid": "22222222-2222-2222-2222-222222222222",
                "container_name": "bumpers",
                "uri": "/media/bumpers/a.mp4",
                "state": "enriching",
                "approved_for_broadcast": False,
                "duration_ms": 0,
                "invalid_duration": True,
                "broadcast_ready": False,
                "discovered_at": "2026-04-14T01:02:03+00:00",
            }
        ]
        with patch(
            "retrovue.usecases.asset_list.list_assets_for_container",
            return_value=rows,
        ):
            result = self.runner.invoke(
                app,
                ["asset", "list", "--container", "bumpers", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["total"] == 1
        assert payload["assets"][0]["invalid_duration"] is True
        assert payload["assets"][0]["broadcast_ready"] is False

    def test_issues_only_flag_forwards_to_usecase(self):
        with patch(
            "retrovue.usecases.asset_list.list_assets_for_container",
            return_value=[],
        ) as list_fn:
            result = self.runner.invoke(
                app,
                ["asset", "list", "--container", "bumpers", "--issues-only", "--limit", "50"],
            )

        assert result.exit_code == 0
        list_fn.assert_called_once()
        kwargs = list_fn.call_args[1]
        assert kwargs["container_selector"] == "bumpers"
        assert kwargs["issues_only"] is True
        assert kwargs["limit"] == 50

    def test_invalid_duration_only_filters_rows_after_usecase(self):
        rows = [
            {
                "uuid": "11111111-1111-1111-1111-111111111111",
                "collection_uuid": "22222222-2222-2222-2222-222222222222",
                "container_name": "bumpers",
                "uri": "/media/bumpers/ok.mp4",
                "state": "ready",
                "approved_for_broadcast": True,
                "duration_ms": 5000,
                "invalid_duration": False,
                "broadcast_ready": True,
                "discovered_at": "2026-04-14T01:02:03+00:00",
            },
            {
                "uuid": "33333333-3333-3333-3333-333333333333",
                "collection_uuid": "22222222-2222-2222-2222-222222222222",
                "container_name": "bumpers",
                "uri": "/media/bumpers/bad.mp4",
                "state": "enriching",
                "approved_for_broadcast": False,
                "duration_ms": 0,
                "invalid_duration": True,
                "broadcast_ready": False,
                "discovered_at": "2026-04-14T01:02:03+00:00",
            },
        ]
        with patch("retrovue.usecases.asset_list.list_assets_for_container", return_value=rows):
            result = self.runner.invoke(
                app,
                ["asset", "list", "--container", "bumpers", "--invalid-duration-only", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["total"] == 1
        assert payload["assets"][0]["uri"].endswith("bad.mp4")
