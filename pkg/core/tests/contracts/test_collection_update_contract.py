import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def test_collection_update_supports_test_db_uses_test_sessionmaker():
    runner = CliRunner()

    with patch("retrovue.cli.commands.collection.get_sessionmaker") as mock_get_sm, \
         patch("retrovue.cli.commands.collection.session") as mock_session, \
         patch("os.path.exists", return_value=True), \
         patch("os.path.isdir", return_value=True), \
         patch("os.access", return_value=True):
        # Mock test sessionmaker
        TestSessionMaker = MagicMock()
        test_db = MagicMock()
        TestSessionMaker.return_value = test_db
        mock_get_sm.return_value = TestSessionMaker

        # Prepare DB query responses
        mock_db = MagicMock()
        test_db.__enter__.return_value = mock_db

        # Mock resolve_collection_selector to return a fake collection
        fake_collection = MagicMock()
        fake_collection.uuid = "col-1"
        fake_collection.name = "Movies"
        fake_collection.sync_enabled = False
        fake_collection.ingestible = False
        with patch("retrovue.cli.commands.collection.resolve_collection_selector", return_value=fake_collection):
            # Patch PathMapping query chain
            mock_query = MagicMock()
            mock_db.query.return_value = mock_query
            mock_query.filter.return_value.delete.return_value = 1

            result = runner.invoke(
                app,
                [
                    "collection",
                    "update",
                    "Movies",
                    "--local-path",
                    "Z:/Movies",
                    "--sync-enabled",
                    "--json",
                    "--test-db",
                ],
            )

    assert result.exit_code == 0
    mock_get_sm.assert_called_once_with(for_test=True)
    mock_session.assert_not_called()

    data = json.loads(result.stdout)
    assert data["status"] == "updated"

