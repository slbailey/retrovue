from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestCollectionShowContract:
    def setup_method(self):
        self.runner = CliRunner()

    def test_show_collection_json_includes_enrichers_and_config(self):
        with patch("retrovue.cli.commands.collection._get_db_context") as get_ctx, patch(
            "retrovue.cli.commands.collection.resolve_collection_selector"
        ) as resolve:
            fake_cm = MagicMock()
            fake_db = MagicMock()
            fake_cm.__enter__.return_value = fake_db
            get_ctx.return_value = fake_cm

            # Fake collection with config including enrichers
            collection = MagicMock()
            collection.uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            collection.external_id = "lib-123"
            collection.name = "TV Shows"
            collection.sync_enabled = True
            collection.ingestible = True
            collection.source_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            collection.config = {
                "plex_section_ref": "library://sections/1",
                "enrichers": [
                    {"enricher_id": "enricher-ffprobe-1", "priority": 1},
                    {"enricher_id": "enricher-qc-2", "priority": 2},
                ],
            }
            resolve.return_value = collection

            # Path mappings query
            mock_pm = MagicMock()
            mock_pm.plex_path = "/plex/TV_Shows"
            mock_pm.local_path = "Z:/TV_Shows"
            fake_db.query.return_value.filter.return_value.all.return_value = [mock_pm]

            # Enricher rows lookups
            def _first_side_effect():
                m = MagicMock()
                m.enricher_id = "enricher-ffprobe-1"
                m.type = "ffprobe"
                m.scope = "ingest"
                m.name = "FFprobe"
                return m

            def _first_side_effect_qc():
                m = MagicMock()
                m.enricher_id = "enricher-qc-2"
                m.type = "qc"
                m.scope = "ingest"
                m.name = "Quality Check"
                return m

            # Configure successive calls to .first()
            fake_db.query.return_value.filter.return_value.first.side_effect = [
                _first_side_effect(),
                _first_side_effect_qc(),
            ]

            result = self.runner.invoke(
                app, ["collection", "show", "TV Shows", "--json"]
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["collection_id"] == collection.uuid
        assert payload["name"] == "TV Shows"
        assert payload["sync_enabled"] is True
        assert payload["ingestible"] is True
        assert isinstance(payload.get("config"), dict)
        # Path mappings key present (may be empty depending on DB state)
        assert isinstance(payload.get("path_mappings"), list)
        # Enrichers present with resolved details
        enr = payload.get("enrichers", [])
        ids = {e["enricher_id"] for e in enr}
        assert "enricher-ffprobe-1" in ids and "enricher-qc-2" in ids

    def test_show_collection_human_mentions_enricher(self):
        with patch("retrovue.cli.commands.collection._get_db_context") as get_ctx, patch(
            "retrovue.cli.commands.collection.resolve_collection_selector"
        ) as resolve:
            fake_cm = MagicMock()
            fake_db = MagicMock()
            fake_cm.__enter__.return_value = fake_db
            get_ctx.return_value = fake_cm

            collection = MagicMock()
            collection.uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            collection.external_id = "lib-123"
            collection.name = "Movies"
            collection.sync_enabled = False
            collection.ingestible = False
            collection.source_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            collection.config = {"enrichers": [{"enricher_id": "enricher-ffprobe-1", "priority": 5}]}
            resolve.return_value = collection

            fake_db.query.return_value.filter.return_value.all.return_value = []

            enr_row = MagicMock()
            enr_row.enricher_id = "enricher-ffprobe-1"
            enr_row.type = "ffprobe"
            enr_row.scope = "ingest"
            enr_row.name = "FFprobe"
            fake_db.query.return_value.filter.return_value.first.return_value = enr_row

            result = self.runner.invoke(app, ["collection", "show", "Movies"])

        assert result.exit_code == 0
        assert "Movies" in result.stdout
        assert "enricher-ffprobe-1" in result.stdout or "FFprobe" in result.stdout

    def test_show_collection_supports_test_db(self):
        with patch("retrovue.cli.commands.collection._get_db_context") as get_ctx, patch(
            "retrovue.cli.commands.collection.resolve_collection_selector"
        ) as resolve:
            fake_cm = MagicMock()
            fake_db = MagicMock()
            fake_cm.__enter__.return_value = fake_db
            get_ctx.return_value = fake_cm

            collection = MagicMock()
            collection.uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
            collection.external_id = "lib-999"
            collection.name = "Docs"
            collection.sync_enabled = True
            collection.ingestible = True
            collection.source_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
            collection.config = {}
            resolve.return_value = collection

            fake_db.query.return_value.filter.return_value.all.return_value = []
            fake_db.query.return_value.filter.return_value.first.return_value = None

            result = self.runner.invoke(app, ["collection", "show", "Docs", "--test-db", "--json"])

        assert result.exit_code == 0
        get_ctx.assert_called_once()

