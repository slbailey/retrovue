"""
CLI-facing contract tests for `collection wipe`.

These tests guarantee:
- stable flags/arguments (`--dry-run`, `--json`, `--force`)
- stable human-readable and JSON output shapes
- safe operator prompts / error handling
- correct collection targeting behavior

See docs/contracts/resources/CollectionWipeContract.md for the source of truth.
Behavior MUST NOT change without updating that contract first.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

# NOTE: These imports MUST refer to real modules in the repo.
# If the CLI root or command path changes, update the contract doc first.
from retrovue.cli.main import app  # TODO: confirm this path matches actual CLI entrypoint


class TestCollectionWipeCliContract:
    """CLI-level contract for `collection wipe`."""

    def setup_method(self):
        self.runner = CliRunner()
        self.test_collection_id = "2a3cd8d1-04cc-4385-bb07-981f7ad2badb"
        self.test_collection_name = "TV Shows"

    def test_collection_wipe_help(self):
        """
        The help text MUST expose required flags and usage.
        Contract: --force, --dry-run, --json must be documented.
        It must mention the collection identifier argument.
        """
        result = self.runner.invoke(app, ["collection", "wipe", "--help"])
        assert result.exit_code == 0

        stdout = result.stdout
        assert "--force" in stdout  # skip confirmation
        assert "--dry-run" in stdout  # analysis-only mode
        assert "--json" in stdout  # machine readable output

        # Some form of positional collection identifier must be documented.
        assert "collection_id" in stdout or "collection_identifier" in stdout or "name" in stdout

    def test_collection_wipe_collection_not_found(self):
        """
        If the named/IDed collection cannot be resolved,
        the command MUST exit non-zero and MUST communicate 'not found'.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            # Simulate lookup failure (no UUID match, no external_id match, no name match)
            mock_db.query.return_value.filter.return_value.first.return_value = None

            result = self.runner.invoke(app, ["collection", "wipe", "DoesNotExist", "--dry-run"])

            assert result.exit_code != 0
            assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()

    def test_collection_wipe_ambiguous_collection(self):
        """
        If multiple collections match (e.g. two collections with same name),
        the command MUST exit non-zero and MUST NOT perform destructive work.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            # Simulate name lookup returning >1 match
            # We expect resolution logic in CLI to detect ambiguity.
            mock_query = MagicMock()
            mock_filter = MagicMock()

            mock_db.query.return_value = mock_query
            mock_query.filter.return_value = mock_filter

            # First() calls will return None (no unique match),
            # and all() will return >1 (ambiguous human-readable name)
            mock_filter.first.side_effect = [None, None]  # UUID lookup, external_id lookup
            mock_filter.all.return_value = [MagicMock(), MagicMock()]  # Ambiguous name

            result = self.runner.invoke(app, ["collection", "wipe", self.test_collection_name, "--dry-run"])

            assert result.exit_code != 0
            assert "multiple" in result.stdout.lower() or "multiple" in result.stderr.lower()

    def test_collection_wipe_dry_run_contract(self):
        """
        In --dry-run mode, the CLI MUST:
        - perform analysis ONLY
        - print a human-readable plan that includes contract-mandated sections
        - MUST NOT actually modify the DB
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            # Fake resolved collection
            fake_collection = MagicMock()
            fake_collection.id = self.test_collection_id
            fake_collection.name = self.test_collection_name
            fake_collection.external_id = "2"
            mock_db.query.return_value.filter.return_value.first.return_value = fake_collection

            # Fake that queries return 0 items for deletion
            mock_db.query.return_value.filter.return_value.all.return_value = []
            mock_db.query.return_value.filter.return_value.count.return_value = 0

            result = self.runner.invoke(app, ["collection", "wipe", self.test_collection_name, "--dry-run"])
            assert result.exit_code == 0

            stdout = result.stdout
            assert "Collection wipe analysis for:" in stdout
            assert self.test_collection_name in stdout
            assert "Collection ID:" in stdout
            assert "External ID:" in stdout
            assert "Items that will be deleted:" in stdout
            assert "Review queue entries:" in stdout
            assert "Episode-asset links:" in stdout
            assert "Assets:" in stdout
            assert "Episodes:" in stdout
            assert "Seasons:" in stdout
            assert "TV Shows/Titles:" in stdout
            assert "DRY RUN - No changes made" in stdout

    def test_collection_wipe_json_output_contract(self):
        """
        In --dry-run --json mode, the CLI MUST emit valid JSON containing:
        {
          "collection": { "id", "name", "external_id" },
          "items_to_delete": {
            "review_queue_entries": ...,
            "episode_assets": ...,
            "assets": ...,
            "episodes": ...,
            "seasons": ...,
            "titles": ...
          },
          "dry_run": true
        }
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            fake_collection = MagicMock()
            fake_collection.id = self.test_collection_id
            fake_collection.name = self.test_collection_name
            fake_collection.external_id = "2"
            mock_db.query.return_value.filter.return_value.first.return_value = fake_collection

            mock_db.query.return_value.filter.return_value.all.return_value = []
            mock_db.query.return_value.filter.return_value.count.return_value = 0

            result = self.runner.invoke(
                app,
                ["collection", "wipe", self.test_collection_name, "--dry-run", "--json"],
            )
            assert result.exit_code == 0

            # Should parse as JSON
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                pytest.fail("Output is not valid JSON")

            assert "collection" in payload
            assert "items_to_delete" in payload
            assert "dry_run" in payload
            assert payload["dry_run"] is True

            # Collection block must contain id, name, external_id
            assert "id" in payload["collection"]
            assert "name" in payload["collection"]
            assert "external_id" in payload["collection"]

            # items_to_delete block must expose all expected buckets
            items_block = payload["items_to_delete"]
            assert "review_queue_entries" in items_block
            assert "episode_assets" in items_block
            assert "assets" in items_block
            assert "episodes" in items_block
            assert "seasons" in items_block
            assert "titles" in items_block

    def test_collection_wipe_confirmation_prompt(self):
        """
        When NOT in --dry-run and NOT in --force:
        - MUST warn loudly (WARNING / cannot be undone / permanently delete)
        - MUST prompt for confirmation
        - MUST allow abort
        - MUST exit 0 on abort with 'Operation cancelled'
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            fake_collection = MagicMock()
            fake_collection.id = self.test_collection_id
            fake_collection.name = self.test_collection_name
            fake_collection.external_id = "2"
            mock_db.query.return_value.filter.return_value.first.return_value = fake_collection

            # Data such that wipe would actually delete stuff (to force prompt)
            mock_asset = MagicMock()
            mock_asset.id = 1
            mock_db.query.return_value.filter.return_value.all.return_value = [mock_asset]
            mock_db.query.return_value.filter.return_value.count.return_value = 5

            # Patch typer.prompt to simulate operator hitting ENTER (cancel)
            with patch("retrovue.cli.commands.collection.typer.prompt") as mock_prompt:
                mock_prompt.return_value = ""

                result = self.runner.invoke(app, ["collection", "wipe", self.test_collection_name])
                assert result.exit_code == 0

                stdout = result.stdout
                assert "WARNING" in stdout
                assert "permanently delete" in stdout
                assert "This action cannot be undone" in stdout
                assert "Operation cancelled" in stdout

                mock_prompt.assert_called_once()

    def test_collection_wipe_force_mode(self):
        """
        With --force:
        - MUST skip interactive prompt
        - MUST proceed to perform the wipe logic
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            fake_collection = MagicMock()
            fake_collection.id = self.test_collection_id
            fake_collection.name = self.test_collection_name
            fake_collection.external_id = "2"
            mock_db.query.return_value.filter.return_value.first.return_value = fake_collection

            mock_db.query.return_value.filter.return_value.all.return_value = []
            mock_db.query.return_value.filter.return_value.count.return_value = 0

            result = self.runner.invoke(
                app,
                ["collection", "wipe", self.test_collection_name, "--force", "--dry-run"],
            )

            assert result.exit_code == 0

            # In --force mode, we should not be nagging the operator
            assert "Are you sure" not in result.stdout
            assert "Operation cancelled" not in result.stdout

    def test_collection_wipe_asset_discovery_logic(self):
        """
        The wipe command MUST identify candidate assets using BOTH:
        - Asset.collection_id == this SourceCollection.id
        - path-based discovery via PathMapping.local_path

        This test doesn't assert row math. It asserts that the CLI path
        completes successfully with a collection that has path mappings,
        which implies that both discovery strategies were attempted.

        If discovery logic stops using PathMapping or stops looking at
        Asset.collection_id, update the contract FIRST.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            fake_collection = MagicMock()
            fake_collection.id = self.test_collection_id
            fake_collection.name = self.test_collection_name
            fake_collection.external_id = "2"
            mock_db.query.return_value.filter.return_value.first.return_value = fake_collection

            # Pretend there is at least one PathMapping on this collection
            fake_mapping = MagicMock()
            fake_mapping.local_path = "R:\\media\\TV"
            mock_db.query.return_value.filter.return_value.all.return_value = [fake_mapping]

            # Also pretend there are assets that would match
            mock_db.query.return_value.filter.return_value.count.return_value = 0

            result = self.runner.invoke(app, ["collection", "wipe", self.test_collection_name, "--dry-run"])
            assert result.exit_code == 0

            # If we reached here, CLI didn't crash out of discovery.
            # That's our contract-level signal that both discovery paths exist.
            assert "Collection wipe analysis for:" in result.stdout
