from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestCollectionEnricherAttachDetachContract:
    def setup_method(self):
        self.runner = CliRunner()

    def test_attach_enricher_success_human(self):
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.collection_enrichers.attach_enricher_to_collection"
        ) as attach_fn:
            fake_db = MagicMock()
            session_ctx.return_value.__enter__.return_value = fake_db
            attach_fn.return_value = {
                "collection_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "collection_name": "TV Shows",
                "enricher_id": "enricher-ffprobe-1",
                "priority": 1,
                "status": "attached",
            }

            result = self.runner.invoke(
                app,
                [
                    "collection",
                    "attach-enricher",
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "enricher-ffprobe-1",
                    "--priority",
                    "1",
                ],
            )

        assert result.exit_code == 0
        assert "attached enricher" in result.stdout.lower()
        attach_fn.assert_called_once()

    def test_attach_enricher_success_json(self):
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.collection_enrichers.attach_enricher_to_collection"
        ) as attach_fn:
            fake_db = MagicMock()
            session_ctx.return_value.__enter__.return_value = fake_db
            attach_fn.return_value = {
                "collection_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "collection_name": "TV Shows",
                "enricher_id": "enricher-ffprobe-1",
                "priority": 2,
                "status": "attached",
            }

            result = self.runner.invoke(
                app,
                [
                    "collection",
                    "attach-enricher",
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "enricher-ffprobe-1",
                    "--priority",
                    "2",
                    "--json",
                ],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["action"] == "attached"
        assert payload["collection_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        assert payload["enricher_id"] == "enricher-ffprobe-1"
        assert payload["priority"] == 2

    def test_attach_enricher_not_found_exits_one(self):
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.collection_enrichers.attach_enricher_to_collection",
            side_effect=ValueError("Collection not found"),
        ):
            fake_db = MagicMock()
            session_ctx.return_value.__enter__.return_value = fake_db

            result = self.runner.invoke(
                app,
                [
                    "collection",
                    "attach-enricher",
                    "missing",
                    "enricher-ffprobe-1",
                    "--priority",
                    "1",
                ],
            )

        assert result.exit_code == 1
        assert "error" in result.stdout.lower() or "error" in result.stderr.lower()

    def test_detach_enricher_success_human(self):
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.collection_enrichers.detach_enricher_from_collection"
        ) as detach_fn:
            fake_db = MagicMock()
            session_ctx.return_value.__enter__.return_value = fake_db
            detach_fn.return_value = {
                "collection_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "collection_name": "Movies",
                "enricher_id": "enricher-ffprobe-1",
                "status": "detached",
            }

            result = self.runner.invoke(
                app,
                [
                    "collection",
                    "detach-enricher",
                    "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "enricher-ffprobe-1",
                ],
            )

        assert result.exit_code == 0
        assert "detached enricher" in result.stdout.lower()
        detach_fn.assert_called_once()

    def test_detach_enricher_success_json(self):
        with patch("retrovue.infra.uow.session") as session_ctx, patch(
            "retrovue.usecases.collection_enrichers.detach_enricher_from_collection"
        ) as detach_fn:
            fake_db = MagicMock()
            session_ctx.return_value.__enter__.return_value = fake_db
            detach_fn.return_value = {
                "collection_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "collection_name": "Movies",
                "enricher_id": "enricher-ffprobe-1",
                "status": "detached",
            }

            result = self.runner.invoke(
                app,
                [
                    "collection",
                    "detach-enricher",
                    "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "enricher-ffprobe-1",
                    "--json",
                ],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["action"] == "detached"
        assert payload["collection_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        assert payload["enricher_id"] == "enricher-ffprobe-1"


