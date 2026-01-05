import json
import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestCollectionIngestSafetyContract:
    def setup_method(self):
        self.runner = CliRunner()

    def _mock_collection(self):
        mc = MagicMock()
        mc.uuid = uuid.uuid4()
        mc.id = str(mc.uuid)
        mc.name = "Movies"
        mc.sync_enabled = True
        mc.ingestible = True
        mc.source_id = uuid.uuid4()
        return mc

    def test_ingest_aborts_when_max_new_exceeded(self):
        collection = self._mock_collection()

        # Three new items to ingest
        items = [
            {"uri": f"/media/m{i}.mkv", "size": 100 + i}
            for i in range(3)
        ]

        importer = MagicMock()
        importer.name = "mock"
        importer.validate_ingestible.return_value = True
        importer.discover.return_value = items

        with patch("retrovue.cli.commands.collection.session") as mock_session, \
             patch("retrovue.cli.commands.collection.resolve_collection_selector", return_value=collection), \
             patch("retrovue.cli.commands.collection.construct_importer_for_collection", return_value=importer), \
             patch("retrovue.cli.commands._ops.collection_ingest_service.canonical_key_for", side_effect=lambda it, **_: it.get("uri")), \
             patch("retrovue.cli.commands._ops.collection_ingest_service.canonical_hash", side_effect=lambda key: key):

            # DB behavior: no existing assets
            db = MagicMock()
            mock_session.return_value.__enter__.return_value = db
            db.scalar.return_value = None

            result = self.runner.invoke(
                app,
                [
                    "collection",
                    "ingest",
                    str(collection.uuid),
                    "--json",
                    "--max-new",
                    "1",
                ],
            )

            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert payload["stats"]["assets_ingested"] == 1
            assert any("max_new exceeded" in e for e in payload["stats"]["errors"])  # abort reason present

    def test_ingest_ignores_max_updates_when_updates_disallowed(self):
        collection = self._mock_collection()

        # Three existing items that will trigger updates (changed content hash)
        items = [
            {"uri": f"/media/e{i}.mkv", "size": 200 + i}
            for i in range(3)
        ]

        importer = MagicMock()
        importer.name = "mock"
        importer.validate_ingestible.return_value = True
        importer.discover.return_value = items

        # Existing asset objects
        existing = MagicMock()
        existing.state = "ready"
        existing.uuid = uuid.uuid4()

        with patch("retrovue.cli.commands.collection.session") as mock_session, \
             patch("retrovue.cli.commands.collection.resolve_collection_selector", return_value=collection), \
             patch("retrovue.cli.commands.collection.construct_importer_for_collection", return_value=importer), \
             patch("retrovue.cli.commands._ops.collection_ingest_service.canonical_key_for", side_effect=lambda it, **_: it.get("uri")), \
             patch("retrovue.cli.commands._ops.collection_ingest_service.canonical_hash", side_effect=lambda key: key):

            db = MagicMock()
            mock_session.return_value.__enter__.return_value = db
            # Return an existing asset for each lookup
            db.scalar.return_value = existing

            result = self.runner.invoke(
                app,
                [
                    "collection",
                    "ingest",
                    str(collection.uuid),
                    "--json",
                    "--max-updates",
                    "1",
                ],
            )

            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            # Updates are disallowed during collection ingest; no updates counted or aborted
            assert payload["stats"]["assets_updated"] == 0
            assert payload["stats"]["assets_changed_content"] + payload["stats"]["assets_changed_enricher"] == 0
            assert not payload["stats"]["errors"]

    def test_ingest_uses_test_db_when_flag_set(self):
        collection = self._mock_collection()

        importer = MagicMock()
        importer.name = "mock"
        importer.validate_ingestible.return_value = True
        importer.discover.return_value = []

        SessionForTest = MagicMock()
        test_db_session = MagicMock()
        SessionForTest.return_value = test_db_session

        with patch("retrovue.cli.commands.collection.get_sessionmaker", return_value=SessionForTest) as mock_get_sm, \
             patch("retrovue.cli.commands.collection.resolve_collection_selector", return_value=collection), \
             patch("retrovue.cli.commands.collection.construct_importer_for_collection", return_value=importer), \
             patch("retrovue.cli.commands._ops.collection_ingest_service.canonical_key_for", side_effect=lambda it, **_: it.get("uri")), \
             patch("retrovue.cli.commands._ops.collection_ingest_service.canonical_hash", side_effect=lambda key: key):

            result = self.runner.invoke(
                app,
                [
                    "collection",
                    "ingest",
                    str(collection.uuid),
                    "--json",
                    "--test-db",
                ],
            )

            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert payload.get("mode") == "test"
            # Ensure we asked for a test sessionmaker
            mock_get_sm.assert_called_once_with(for_test=True)
            # Ensure a session was created and used (entered/exited context)
            assert SessionForTest.called
            assert test_db_session.__enter__.called
            assert test_db_session.__exit__.called




