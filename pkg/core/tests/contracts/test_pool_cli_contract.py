"""
Contract tests for Pool CLI commands.

Validates:
- INV-CLI-NO-BUSINESS-LOGIC-001: CLI delegates to workflow
- INV-POOL-CLI-DELEGATES-001: pool CLI is a thin wrapper
- create_pool with valid input → pool created
- create_pool with duplicate name → error exit 1
- list_pools returns pools (human + JSON)
- inspect_pool returns PoolDiagnostics (INV-POOL-RESOLUTION-VISIBILITY-001)
- inspect_pool with zero matches → diagnostics explain why
- assign_pool with valid pool + channel → assignment created
- assign_pool with non-existent pool → error exit 1
- assign_pool with non-existent channel → error exit 1
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app
from retrovue.domain.entities import Pool, PoolAssignment
from retrovue.runtime.asset_resolver import PoolDiagnostics


class TestPoolCreateCommand:
    """retrovue pool create contract tests."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_create_pool_success_human(self):
        """Create pool with valid input prints confirmation and exits 0."""
        pool = Pool(name="horror_movies", match_criteria={"type": "movie", "tags": ["horror"]})
        pool.id = uuid.uuid4()

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_create_pool", return_value=pool) as mock_create:
                result = self.runner.invoke(app, [
                    "pool", "create", "horror_movies",
                    "--match", '{"type": "movie", "tags": ["horror"]}',
                ])

        assert result.exit_code == 0
        assert "horror_movies" in result.stdout
        mock_create.assert_called_once_with(
            mock_db,
            name="horror_movies",
            match_criteria={"type": "movie", "tags": ["horror"]},
            description=None,
        )

    def test_create_pool_success_json(self):
        """Create pool with --json outputs JSON envelope and exits 0."""
        pool = Pool(name="comedies", match_criteria={"type": "episode"}, description="All comedies")
        pool.id = uuid.uuid4()
        pool.created_at = None

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_create_pool", return_value=pool):
                result = self.runner.invoke(app, [
                    "pool", "create", "comedies",
                    "--match", '{"type": "episode"}',
                    "--description", "All comedies",
                    "--json",
                ])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["pool"]["name"] == "comedies"
        assert payload["pool"]["description"] == "All comedies"

    def test_create_pool_with_description(self):
        """Create pool with --description passes it to workflow."""
        pool = Pool(name="test", match_criteria={"type": "movie"}, description="desc")
        pool.id = uuid.uuid4()

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_create_pool", return_value=pool) as mock_create:
                result = self.runner.invoke(app, [
                    "pool", "create", "test",
                    "--match", '{"type": "movie"}',
                    "--description", "desc",
                ])

        assert result.exit_code == 0
        mock_create.assert_called_once_with(
            mock_db,
            name="test",
            match_criteria={"type": "movie"},
            description="desc",
        )

    def test_create_pool_duplicate_name_exits_1(self):
        """INV-POOL-NAME-UNIQUE-001: duplicate name exits 1 with error."""
        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch(
                "retrovue.cli.commands.pool.wf_create_pool",
                side_effect=ValueError("Pool 'existing' already exists"),
            ):
                result = self.runner.invoke(app, [
                    "pool", "create", "existing",
                    "--match", '{"type": "movie"}',
                ])

        assert result.exit_code == 1

    def test_create_pool_invalid_match_exits_1(self):
        """Invalid --match value (not JSON/YAML) exits 1."""
        result = self.runner.invoke(app, [
            "pool", "create", "test",
            "--match", ":::not valid:::",
        ])
        assert result.exit_code == 1

    def test_create_pool_yaml_match(self):
        """Create pool accepts YAML match criteria."""
        pool = Pool(name="yaml_pool", match_criteria={"type": "episode"})
        pool.id = uuid.uuid4()

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_create_pool", return_value=pool) as mock_create:
                result = self.runner.invoke(app, [
                    "pool", "create", "yaml_pool",
                    "--match", "type: episode",
                ])

        assert result.exit_code == 0
        mock_create.assert_called_once_with(
            mock_db,
            name="yaml_pool",
            match_criteria={"type": "episode"},
            description=None,
        )


class TestPoolListCommand:
    """retrovue pool list contract tests."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_list_pools_empty(self):
        """List with no pools prints message and exits 0."""
        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_list_pools", return_value=[]):
                result = self.runner.invoke(app, ["pool", "list"])

        assert result.exit_code == 0
        assert "No pools configured" in result.stdout

    def test_list_pools_human(self):
        """List pools shows pool names."""
        pool_a = Pool(name="alpha", match_criteria={"type": "movie"})
        pool_b = Pool(name="beta", match_criteria={"type": "episode"}, description="Beta pool")

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_list_pools", return_value=[pool_a, pool_b]):
                result = self.runner.invoke(app, ["pool", "list"])

        assert result.exit_code == 0
        assert "alpha" in result.stdout
        assert "beta" in result.stdout

    def test_list_pools_json(self):
        """List pools with --json outputs JSON envelope."""
        pool = Pool(name="alpha", match_criteria={"type": "movie"})
        pool.id = uuid.uuid4()
        pool.created_at = None

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_list_pools", return_value=[pool]):
                result = self.runner.invoke(app, ["pool", "list", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["total"] == 1
        assert payload["pools"][0]["name"] == "alpha"


class TestPoolInspectCommand:
    """retrovue pool inspect contract tests."""

    def setup_method(self):
        self.runner = CliRunner()

    def _make_inspect_result(self, matched_count=5, matched_ids=None, total_considered=10):
        from retrovue.workflows.pool_management import PoolInspectResult

        if matched_ids is None:
            matched_ids = [f"asset_{i}" for i in range(matched_count)]

        diagnostics = PoolDiagnostics(
            total_considered=total_considered,
            excluded_by_type=2,
            excluded_by_tags=1,
            excluded_by_rating=1,
            excluded_by_duration=1,
            excluded_by_editorial=0,
            matched=matched_count,
            exclusion_reasons={},
        )
        return PoolInspectResult(
            pool_name="horror",
            match_criteria={"type": "movie", "tags": ["horror"]},
            matched_asset_ids=matched_ids,
            matched_count=matched_count,
            diagnostics=diagnostics,
        )

    def test_inspect_pool_success_human(self):
        """INV-POOL-RESOLUTION-VISIBILITY-001: inspect shows diagnostics."""
        inspect_result = self._make_inspect_result()

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.runtime.catalog_resolver.CatalogAssetResolver"):
                with patch("retrovue.cli.commands.pool.wf_inspect_pool", return_value=inspect_result):
                    result = self.runner.invoke(app, ["pool", "inspect", "horror"])

        assert result.exit_code == 0
        assert "horror" in result.stdout
        assert "Matched assets: 5" in result.stdout
        assert "Total considered: 10" in result.stdout
        assert "Excluded by type: 2" in result.stdout
        assert "Excluded by tags: 1" in result.stdout

    def test_inspect_pool_success_json(self):
        """Inspect with --json outputs JSON envelope with diagnostics."""
        inspect_result = self._make_inspect_result()

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.runtime.catalog_resolver.CatalogAssetResolver"):
                with patch("retrovue.cli.commands.pool.wf_inspect_pool", return_value=inspect_result):
                    result = self.runner.invoke(app, ["pool", "inspect", "horror", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["matched_count"] == 5
        assert payload["diagnostics"]["total_considered"] == 10
        assert payload["diagnostics"]["excluded_by_type"] == 2

    def test_inspect_pool_zero_matches_shows_diagnostics(self):
        """INV-POOL-RESOLUTION-VISIBILITY-001: zero matches still shows diagnostics."""
        inspect_result = self._make_inspect_result(matched_count=0, matched_ids=[], total_considered=10)

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.runtime.catalog_resolver.CatalogAssetResolver"):
                with patch("retrovue.cli.commands.pool.wf_inspect_pool", return_value=inspect_result):
                    result = self.runner.invoke(app, ["pool", "inspect", "empty_pool"])

        assert result.exit_code == 0
        assert "Matched assets: 0" in result.stdout
        assert "Total considered: 10" in result.stdout

    def test_inspect_pool_not_found_exits_1(self):
        """Inspect non-existent pool exits 1."""
        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.runtime.catalog_resolver.CatalogAssetResolver"):
                with patch(
                    "retrovue.cli.commands.pool.wf_inspect_pool",
                    side_effect=ValueError("Pool 'nonexistent' not found"),
                ):
                    result = self.runner.invoke(app, ["pool", "inspect", "nonexistent"])

        assert result.exit_code == 1


class TestPoolAssignCommand:
    """retrovue pool assign contract tests."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_assign_pool_success_human(self):
        """Assign pool to channel prints confirmation and exits 0."""
        assignment = PoolAssignment(pool_id=uuid.uuid4(), channel_id=uuid.uuid4())
        assignment.id = uuid.uuid4()
        assignment.created_at = None

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_assign_pool", return_value=assignment) as mock_assign:
                result = self.runner.invoke(app, ["pool", "assign", "horror", "retro-horror"])

        assert result.exit_code == 0
        assert "horror" in result.stdout
        assert "retro-horror" in result.stdout
        mock_assign.assert_called_once_with(mock_db, pool_name="horror", channel_name="retro-horror")

    def test_assign_pool_success_json(self):
        """Assign with --json outputs JSON envelope."""
        assignment = PoolAssignment(pool_id=uuid.uuid4(), channel_id=uuid.uuid4())
        assignment.id = uuid.uuid4()
        assignment.created_at = None

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_assign_pool", return_value=assignment):
                result = self.runner.invoke(app, [
                    "pool", "assign", "horror", "retro-horror", "--json",
                ])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert "assignment" in payload

    def test_assign_pool_missing_pool_exits_1(self):
        """Assign with non-existent pool exits 1."""
        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch(
                "retrovue.cli.commands.pool.wf_assign_pool",
                side_effect=ValueError("Pool 'nonexistent' not found"),
            ):
                result = self.runner.invoke(app, ["pool", "assign", "nonexistent", "ch1"])

        assert result.exit_code == 1

    def test_assign_pool_missing_channel_exits_1(self):
        """Assign with non-existent channel exits 1."""
        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch(
                "retrovue.cli.commands.pool.wf_assign_pool",
                side_effect=ValueError("Channel 'nonexistent' not found"),
            ):
                result = self.runner.invoke(app, ["pool", "assign", "horror", "nonexistent"])

        assert result.exit_code == 1


class TestPoolCLIDelegation:
    """INV-CLI-NO-BUSINESS-LOGIC-001: CLI delegates all logic to workflow."""

    def test_create_delegates_to_workflow(self):
        """pool create calls wf_create_pool, not inline business logic."""
        pool = Pool(name="test", match_criteria={"type": "movie"})
        pool.id = uuid.uuid4()

        runner = CliRunner()
        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_create_pool", return_value=pool) as mock_wf:
                runner.invoke(app, [
                    "pool", "create", "test", "--match", '{"type": "movie"}',
                ])

        mock_wf.assert_called_once()

    def test_list_delegates_to_workflow(self):
        """pool list calls wf_list_pools."""
        runner = CliRunner()
        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_list_pools", return_value=[]) as mock_wf:
                runner.invoke(app, ["pool", "list"])

        mock_wf.assert_called_once_with(mock_db)

    def test_assign_delegates_to_workflow(self):
        """pool assign calls wf_assign_pool."""
        assignment = PoolAssignment(pool_id=uuid.uuid4(), channel_id=uuid.uuid4())
        assignment.id = uuid.uuid4()
        assignment.created_at = None

        runner = CliRunner()
        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.cli.commands.pool.wf_assign_pool", return_value=assignment) as mock_wf:
                runner.invoke(app, ["pool", "assign", "test_pool", "ch1"])

        mock_wf.assert_called_once_with(mock_db, pool_name="test_pool", channel_name="ch1")
