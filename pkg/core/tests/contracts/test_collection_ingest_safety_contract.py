import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app
from retrovue.domain.entities import Asset, Container, Source

from ._fakes import FakeDB


class _FakeImporter:
    """Importer that returns configured items from discover()."""

    def __init__(self, name: str, items: list[dict]):
        self.name = name
        self._items = items

    def validate_ingestible(self, _collection) -> bool:
        return True

    def discover(self) -> list[dict]:
        return list(self._items)


class TestCollectionIngestSafetyContract:
    def setup_method(self):
        self.runner = CliRunner()

    def _make_collection(self):
        coll = SimpleNamespace(
            uuid=uuid.uuid4(),
            id=str(uuid.uuid4()),
            name="Movies",
            sync_enabled=True,
            ingestible=True,
            source_id=str(uuid.uuid4()),
            config={},
            external_id=str(uuid.uuid4()),
        )
        return coll

    def _make_db(self, existing_assets=None):
        db = FakeDB()
        db.seed(Asset, existing_assets or [])
        db.seed(Container, [])
        db.seed(Source, [])
        return db

    def test_ingest_aborts_when_max_new_exceeded(self):
        collection = self._make_collection()

        # Three new items to ingest
        items = [
            {"path": f"/media/m{i}.mkv"}
            for i in range(3)
        ]

        importer = _FakeImporter("mock", items)

        db = self._make_db()

        with patch("retrovue.cli.commands.collection.session") as mock_session, \
             patch("retrovue.cli.commands.collection.resolve_container_selector", return_value=collection), \
             patch("retrovue.cli.commands.collection.get_importer", return_value=importer):

            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                [
                    "container",
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
        collection = self._make_collection()

        # Three existing items that will trigger updates (changed content hash)
        items = [
            {"path": f"/media/e{i}.mkv"}
            for i in range(3)
        ]

        importer = _FakeImporter("mock", items)

        # Build existing assets so reconciliation yields no_action (fingerprint match)
        from retrovue.infra.canonical import canonical_hash, canonical_key_for

        existing_assets = []
        for item in items:
            ck = canonical_key_for(item, container=collection, provider="mock")
            ck_hash = canonical_hash(ck)
            asset = SimpleNamespace(
                uuid=uuid.uuid4(),
                container_id=collection.uuid,
                source_id=collection.source_id,
                canonical_key=ck,
                canonical_key_hash=ck_hash,
                uri=item["path"],
                canonical_uri=item["path"],
                is_deleted=False,
                file_size=None,
                file_mtime=None,
                state="ready",
            )
            existing_assets.append(asset)

        db = self._make_db(existing_assets=existing_assets)

        with patch("retrovue.cli.commands.collection.session") as mock_session, \
             patch("retrovue.cli.commands.collection.resolve_container_selector", return_value=collection), \
             patch("retrovue.cli.commands.collection.get_importer", return_value=importer):

            mock_session.return_value.__enter__.return_value = db

            result = self.runner.invoke(
                app,
                [
                    "container",
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
        collection = self._make_collection()

        importer = _FakeImporter("mock", [])

        SessionForTest = MagicMock()
        test_db_session = MagicMock()
        SessionForTest.return_value = test_db_session

        with patch("retrovue.cli.commands.collection.get_sessionmaker", return_value=SessionForTest) as mock_get_sm, \
             patch("retrovue.cli.commands.collection.resolve_container_selector", return_value=collection), \
             patch("retrovue.cli.commands.collection.get_importer", return_value=importer):

            result = self.runner.invoke(
                app,
                [
                    "container",
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
