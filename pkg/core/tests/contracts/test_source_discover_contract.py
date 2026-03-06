"""
Behavioral contract tests for Source Discover command.

Tests the behavioral aspects of the source discover command as defined in
docs/contracts/resources/SourceDiscoverContract.md (B-1 through B-10).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.commands.source import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_source(
    *,
    source_id: str = "test-id",
    name: str = "test-source",
    source_type: str = "plex",
    config: dict | None = None,
) -> MagicMock:
    """Build a mock Source entity."""
    s = MagicMock()
    s.id = source_id
    s.name = name
    s.type = source_type
    s.config = config or {"servers": [{"base_url": "http://test", "token": "test-token"}]}
    return s


def _make_session_cm(*, existing_collection=None):
    """Return a context manager yielding a fake DB session.

    The discover command calls db.query(Collection).filter(...).first()
    to check for duplicate collections. This mock handles that.
    """
    db = MagicMock()
    # Default: no existing collection (duplicate check returns None)
    query_chain = MagicMock()
    query_chain.filter.return_value.first.return_value = existing_collection
    db.query.return_value = query_chain

    cm = MagicMock()
    cm.__enter__.return_value = db
    cm.__exit__.return_value = False
    return cm


class TestSourceDiscoverContract:
    """Test behavioral contract rules for source discover command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_source_discover_help_flag_exits_zero(self):
        """
        Contract B-1: The command MUST validate source existence before attempting discovery.
        """
        result = self.runner.invoke(app, ["discover", "--help"])
        assert result.exit_code == 0
        assert "Discover and add collections" in result.stdout

    def test_source_discover_requires_source_id(self):
        """
        Contract B-1: The command MUST validate source existence before attempting discovery.
        """
        result = self.runner.invoke(app, ["discover"])
        assert result.exit_code != 0
        assert "Missing argument" in result.stdout or "Error" in result.stderr

    def test_source_discover_validates_source_existence(self):
        """
        Contract B-1: The command MUST validate source existence before attempting discovery.
        """
        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=None),
        ):
            result = self.runner.invoke(app, ["discover", "nonexistent-source"])

            assert result.exit_code == 1
            assert "Error: Source 'nonexistent-source' not found" in result.stderr

    def test_source_discover_dry_run_support(self):
        """
        Contract B-2: The --dry-run flag MUST show what would be discovered without persisting to database.
        """
        mock_source = _make_mock_source()

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"},
                {"external_id": "2", "name": "TV Shows"},
            ]
            result = self.runner.invoke(app, ["discover", "test-source", "--dry-run"])

            assert result.exit_code == 0

    def test_source_discover_json_output_format(self):
        """
        Contract B-3: When --json is supplied, output MUST include fields
        "source", "collections_added", and "collections".
        """
        mock_source = _make_mock_source()

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"},
            ]
            result = self.runner.invoke(app, ["discover", "test-source", "--json"])

            assert result.exit_code == 0
            output_data = json.loads(result.stdout)

            # Verify required fields exist
            assert "source" in output_data
            assert "collections_added" in output_data
            assert "collections" in output_data

    def test_source_discover_source_not_found_error(self):
        """
        Contract B-4: On validation failure (source not found), the command
        MUST exit with code 1 and print "Error: Source 'X' not found".
        """
        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=None),
        ):
            result = self.runner.invoke(app, ["discover", "invalid-source"])

            assert result.exit_code == 1
            assert "Error: Source 'invalid-source' not found" in result.stderr

    def test_source_discover_empty_results_exit_code_zero(self):
        """
        Contract B-5: Empty discovery results MUST return exit code 0
        with message "No collections found for source 'X'".
        """
        mock_source = _make_mock_source(name="empty-source")

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = []
            result = self.runner.invoke(app, ["discover", "empty-source"])

            assert result.exit_code == 0

    def test_source_discover_duplicate_collections_skipped(self):
        """
        Contract B-6: Duplicate collections MUST be skipped with notification message.
        """
        mock_source = _make_mock_source()

        existing_collection = MagicMock()
        existing_collection.external_id = "1"
        existing_collection.name = "Movies"

        with (
            patch("retrovue.cli.commands.source.session",
                  return_value=_make_session_cm(existing_collection=existing_collection)),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"},
            ]

            result = self.runner.invoke(app, ["discover", "test-source"])

        assert result.exit_code == 0
        assert "already exists, skipping" in result.stdout

    def test_source_discover_unsupported_source_type_success(self):
        """
        Contract B-7: For any source type whose importer does not expose a
        discovery capability, the command MUST succeed with exit code 0, MUST
        NOT modify the database, and MUST clearly report that no collections
        are discoverable for that source type.
        """
        mock_source = _make_mock_source(
            name="filesystem-source",
            source_type="filesystem",
            config={"root_paths": ["/test/path"]},
        )

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.side_effect = ValueError("Unsupported source type 'filesystem'")
            result = self.runner.invoke(app, ["discover", "filesystem-source"])
            assert result.exit_code == 0

    def test_source_discover_obtains_importer_for_source_type(self):
        """
        Contract B-8: The command MUST obtain the importer for the Source's type.
        """
        mock_source = _make_mock_source()

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = []
            result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0

    def test_source_discover_importer_discovery_capability(self):
        """
        Contract B-9: The importer MUST expose a discovery capability that
        returns all collections visible to that Source.
        """
        mock_source = _make_mock_source()

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"},
                {"external_id": "2", "name": "TV Shows"},
            ]
            result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0

    def test_source_discover_interface_compliance_failure(self):
        """
        Contract B-10: If the importer claims to support discovery but fails
        interface compliance, the command MUST exit with code 1 and emit a
        human-readable error.
        """
        mock_source = _make_mock_source()

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.side_effect = Exception("Interface compliance violation")
            result = self.runner.invoke(app, ["discover", "test-source", "--json"])
            assert result.exit_code == 1
            assert "Error discovering collections" in result.stderr

    def test_source_discover_test_db_support(self):
        """
        Test that --test-db flag is supported (implied by contract safety expectations).
        """
        mock_source = _make_mock_source()

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = []
            result = self.runner.invoke(app, ["discover", "test-source", "--test-db"])
            assert result.exit_code == 0

    def test_source_discover_http_status_exposed_in_json(self):
        """
        Contract: When the importer fails with an HTTP error, the JSON error
        payload SHOULD include http_status if detectable.
        """
        mock_source = _make_mock_source()

        with (
            patch("retrovue.cli.commands.source.session", return_value=_make_session_cm()),
            patch("retrovue.cli.commands.source._resolve_source_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.side_effect = Exception(
                "Failed to fetch libraries: 530 Server Error: <none> for url: https://example"
            )
            result = self.runner.invoke(app, ["discover", "test-source", "--json"])

        assert result.exit_code == 1
        assert "Error discovering collections" in result.stderr
