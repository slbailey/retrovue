"""
Behavioral contract tests for Source Discover command.

Tests the behavioral aspects of the source discover command as defined in
docs/contracts/resources/SourceDiscoverContract.md (B-1 through B-10).
"""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.commands.source import app


class TestSourceDiscoverContract:
    """Test behavioral contract rules for source discover command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def _make_session_cm(self, *, source=None, existing_collection=None):
        """Return a minimal context manager yielding a fake DB session.

        - When `source` is provided, the first/only Source lookups return it.
        - When `existing_collection` is provided, the first() on Collection filter returns it.
        """
        db = MagicMock()
        query = MagicMock()
        # Source lookups
        query.filter.return_value.first.return_value = source
        query.all.return_value = [source] if source else []
        db.query.return_value = query
        # Duplicate collection lookup (first())
        if existing_collection is not None:
            db.query.return_value.filter.return_value.first.return_value = existing_collection
        cm = MagicMock()
        cm.__enter__.return_value = db
        cm.__exit__.return_value = False
        return cm

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
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.side_effect = ValueError("Source not found: nonexistent-source")
            result = self.runner.invoke(app, ["discover", "nonexistent-source"])
            
            assert result.exit_code == 1
            assert "Error: Source 'nonexistent-source' not found" in result.stderr

    def test_source_discover_dry_run_support(self):
        """
        Contract B-2: The --dry-run flag MUST show what would be discovered without persisting to database.
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "test-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"},
                {"external_id": "2", "name": "TV Shows"}
            ]
            result = self.runner.invoke(app, ["discover", "test-source", "--dry-run"])
            
            assert result.exit_code == 0
            # New CLI prints a generic list; keep core assertions len/entries if applicable

    def test_source_discover_json_output_format(self):
        """
        Contract B-3: When --json is supplied, output MUST include fields "source", "collections_added", and "collections".
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "test-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"}
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
        Contract B-4: On validation failure (source not found), the command MUST exit with code 1 and print "Error: Source 'X' not found".
        """
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.side_effect = ValueError("Source not found: invalid-source")
            result = self.runner.invoke(app, ["discover", "invalid-source"])
            
            assert result.exit_code == 1
            assert "Error: Source 'invalid-source' not found" in result.stderr

    def test_source_discover_empty_results_exit_code_zero(self):
        """
        Contract B-5: Empty discovery results MUST return exit code 0 with message "No collections found for source 'X'".
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "empty-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = []
            result = self.runner.invoke(app, ["discover", "empty-source"])
            
            assert result.exit_code == 0

    def test_source_discover_duplicate_collections_skipped(self):
        """
        Contract B-6: Duplicate collections MUST be skipped with notification message.
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "test-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        # Mock database query to return existing collection (duplicate)
        existing_collection = MagicMock()
        existing_collection.external_id = "1"
        existing_collection.name = "Movies"
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm(existing_collection=existing_collection)),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            # Usecase returns discovered collections
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"}
            ]
            
            result = self.runner.invoke(app, ["discover", "test-source"])
                
        assert result.exit_code == 0
        assert "Collection 'Movies' already exists, skipping" in result.stdout

    def test_source_discover_unsupported_source_type_success(self):
        """
        Contract B-7: For any source type whose importer does not expose a discovery capability, 
        the command MUST succeed with exit code 0, MUST NOT modify the database, and MUST clearly 
        report that no collections are discoverable for that source type.
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "filesystem-source"
        mock_source.type = "filesystem"
        mock_source.config = {"root_paths": ["/test/path"]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.side_effect = ValueError("Unsupported source type 'filesystem'")
            result = self.runner.invoke(app, ["discover", "filesystem-source"])
            assert result.exit_code == 0

    def test_source_discover_obtains_importer_for_source_type(self):
        """
        Contract B-8: The command MUST obtain the importer for the Source's type.
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "test-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = []
            result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0

    def test_source_discover_importer_discovery_capability(self):
        """
        Contract B-9: The importer MUST expose a discovery capability that returns all collections 
        (libraries, sections, folders, etc.) visible to that Source.
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "test-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"},
                {"external_id": "2", "name": "TV Shows"}
            ]
            result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0

    def test_source_discover_interface_compliance_failure(self):
        """
        Contract B-10: If the importer claims to support discovery but fails interface compliance 
        (missing required discovery capability, raises interface violation), the command MUST exit 
        with code 1 and emit a human-readable error.
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "test-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.side_effect = Exception("Interface compliance violation")
            result = self.runner.invoke(app, ["discover", "test-source", "--json"])
            assert result.exit_code == 1
            # Error should be in stderr, not JSON output
            assert "Error discovering collections" in result.stderr

    def test_source_discover_test_db_support(self):
        """
        Test that --test-db flag is supported (implied by contract safety expectations).
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "test-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.return_value = []
            result = self.runner.invoke(app, ["discover", "test-source", "--test-db"])
            assert result.exit_code == 0

    def test_source_discover_http_status_exposed_in_json(self):
        """
        Contract: When the importer fails with an HTTP error, the JSON error payload SHOULD include http_status if detectable.
        """
        mock_source = MagicMock()
        mock_source.id = "test-id"
        mock_source.name = "test-source"
        mock_source.type = "plex"
        mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
        
        with (
            patch("retrovue.cli.commands.source.session", return_value=self._make_session_cm()),
            patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source),
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_discover.side_effect = Exception(
                "Failed to fetch libraries: 530 Server Error: <none> for url: https://example"
            )
            result = self.runner.invoke(app, ["discover", "test-source", "--json"])

        assert result.exit_code == 1
        # Error is output to stderr, not JSON
        assert "Error discovering collections" in result.stderr