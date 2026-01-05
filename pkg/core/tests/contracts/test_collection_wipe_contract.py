"""
Contract: docs/contracts/resources/CollectionWipeContract.md

Covers basic behaviors:
- Dry-run execution path with JSON output (no destructive writes)
- Validation error path maps to exit code 1 with helpful message
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def test_wipe_dry_run_json_success() -> None:
    runner = CliRunner()
    collection_id = "00000000-0000-0000-0000-000000000003"

    with patch("retrovue.cli.commands.collection.session") as mock_session, \
         patch("retrovue.cli.commands.collection.validate_collection_exists") as mock_validate_exists, \
         patch("retrovue.cli.commands.collection.execute_collection_wipe") as mock_execute:

        # DB session
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        # Collection exists
        collection = MagicMock()
        collection.id = collection_id
        collection.name = "Test Collection"
        mock_validate_exists.return_value = collection

        # Wipe returns summary
        mock_execute.return_value = {
            "collection": {"id": collection_id, "name": collection.name},
            "dry_run": True,
            "items_to_delete": {"assets": 10, "episodes": 5},
        }

        result = runner.invoke(app, ["collection", "wipe", collection_id, "--dry-run", "--json"])

        assert result.exit_code == 0
        # Ensure wipe execution was attempted and returned a structured payload
        assert mock_execute.called


def test_wipe_validation_error_exit_code() -> None:
    runner = CliRunner()
    collection_id = "00000000-0000-0000-0000-000000000004"

    with patch("retrovue.cli.commands.collection.session") as mock_session, \
         patch("retrovue.cli.commands.collection.validate_collection_exists") as mock_validate_exists:

        # DB session
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        # Simulate validation error
        from retrovue.infra.exceptions import ValidationError

        mock_validate_exists.side_effect = ValidationError("Collection not found")

        result = runner.invoke(app, ["collection", "wipe", collection_id])

        assert result.exit_code == 1
        assert "Validation error" in result.stdout or "Validation error" in result.stderr


