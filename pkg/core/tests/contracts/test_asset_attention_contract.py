"""
Contract tests for Asset Attention command.

Tests the behavioral contract rules (B-#) for listing assets that need
operator attention after ingest downgraded or flagged them.

Scope:
- Help behavior and exit codes
- Read-only listing behavior
- JSON and human-readable outputs
"""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestAssetAttentionContract:
    def setup_method(self):
        self.runner = CliRunner()

    def test_help_flag_exits_zero(self):
        """
        Contract B-7: The command MUST support help and exit with code 0.
        """
        result = self.runner.invoke(app, ["asset", "attention", "--help"])
        assert result.exit_code == 0
        assert "List assets needing attention" in result.stdout or "attention" in result.stdout

    def test_no_assets_needing_attention_prints_message_and_exits_zero(self):
        """
        Contract B-1: When no assets need attention, command exits 0 and prints informative message.
        """
        with patch(
            "retrovue.usecases.asset_attention.list_assets_needing_attention",
            return_value=[],
        ):
            result = self.runner.invoke(app, ["asset", "attention"]) 
        assert result.exit_code == 0
        assert "No assets need attention" in result.stdout

    def test_json_output_when_assets_present(self):
        """
        Contract B-2: The command MUST support JSON output with --json flag.
        """
        rows = [
            {
                "uuid": "11111111-1111-1111-1111-111111111111",
                "collection_uuid": "22222222-2222-2222-2222-222222222222",
                "uri": "/media/a.mp4",
                "state": "enriching",
                "approved_for_broadcast": False,
                "discovered_at": "2025-10-30T12:00:00Z",
            },
            {
                "uuid": "33333333-3333-3333-3333-333333333333",
                "collection_uuid": "22222222-2222-2222-2222-222222222222",
                "uri": "/media/b.mp4",
                "state": "ready",
                "approved_for_broadcast": False,
                "discovered_at": "2025-10-30T12:10:00Z",
            },
        ]
        with patch(
            "retrovue.usecases.asset_attention.list_assets_needing_attention",
            return_value=rows,
        ):
            result = self.runner.invoke(app, ["asset", "attention", "--json"]) 

        assert result.exit_code == 0
        # Must be valid JSON and wrapped in stable envelope
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict)
        assert payload.get("status") == "ok"
        assert payload.get("total") == len(rows)
        assert payload.get("assets") == rows

    def test_collection_filter(self):
        """
        Contract: The command MUST support filtering by collection UUID via --collection.
        """
        rows = [
            {
                "uuid": "11111111-1111-1111-1111-111111111111",
                "collection_uuid": "22222222-2222-2222-2222-222222222222",
                "uri": "/media/a.mp4",
                "state": "enriching",
                "approved_for_broadcast": False,
                "discovered_at": "2025-10-30T12:00:00Z",
            }
        ]
        collection_uuid = "22222222-2222-2222-2222-222222222222"
        with patch(
            "retrovue.usecases.asset_attention.list_assets_needing_attention",
            return_value=rows,
        ) as list_fn:
            result = self.runner.invoke(app, ["asset", "attention", "--collection", collection_uuid])

        assert result.exit_code == 0
        list_fn.assert_called_once()
        # Verify collection_uuid was passed to the usecase
        call_kwargs = list_fn.call_args[1]
        assert call_kwargs.get("collection_uuid") == collection_uuid

    def test_limit_parameter(self):
        """
        Contract: The command MUST support limiting results via --limit.
        """
        rows = [
            {
                "uuid": f"11111111-1111-1111-1111-11111111111{i}",
                "collection_uuid": "22222222-2222-2222-2222-222222222222",
                "uri": f"/media/a{i}.mp4",
                "state": "enriching",
                "approved_for_broadcast": False,
                "discovered_at": "2025-10-30T12:00:00Z",
            }
            for i in range(3)
        ]
        with patch(
            "retrovue.usecases.asset_attention.list_assets_needing_attention",
            return_value=rows,
        ) as list_fn:
            result = self.runner.invoke(app, ["asset", "attention", "--limit", "50"])

        assert result.exit_code == 0
        list_fn.assert_called_once()
        # Verify limit was passed to the usecase
        call_kwargs = list_fn.call_args[1]
        assert call_kwargs.get("limit") == 50


