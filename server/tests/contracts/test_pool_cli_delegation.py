"""Contract tests for Pool CLI delegation — INV-POOL-CLI-DELEGATES-001.

Validates:
- POOL-CLI-003: Pool CLI inspect command delegates to workflow inspect_pool
- POOL-CLI-005: Pool CLI module contains no ORM queries or entity mutations
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import uuid
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app
from retrovue.domain.entities import Pool
from retrovue.runtime.asset_resolver import PoolDiagnostics


class TestInspectDelegatesToWorkflow:
    """POOL-CLI-003: pool inspect delegates to workflow inspect_pool."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_inspect_delegates_to_wf_inspect_pool(self):
        """pool inspect calls wf_inspect_pool, not inline resolution logic."""
        from retrovue.workflows.pool_management import PoolInspectResult

        diagnostics = PoolDiagnostics(
            total_considered=10,
            excluded_by_type=3,
            excluded_by_tags=2,
            excluded_by_rating=0,
            excluded_by_duration=0,
            excluded_by_editorial=0,
            matched=5,
            exclusion_reasons={},
        )
        inspect_result = PoolInspectResult(
            pool_name="horror",
            match_criteria={"type": "movie", "tags": ["horror"]},
            matched_asset_ids=["a1", "a2", "a3", "a4", "a5"],
            matched_count=5,
            diagnostics=diagnostics,
        )

        with patch("retrovue.cli.commands.pool.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            with patch("retrovue.runtime.catalog_resolver.CatalogAssetResolver"):
                with patch(
                    "retrovue.cli.commands.pool.wf_inspect_pool",
                    return_value=inspect_result,
                ) as mock_wf:
                    self.runner.invoke(app, ["pool", "inspect", "horror"])

        mock_wf.assert_called_once()


class TestPoolCLINoBusinessLogic:
    """POOL-CLI-005: Pool CLI module contains no ORM queries or entity mutations.

    INV-POOL-CLI-DELEGATES-001 requires that pool CLI commands are limited to
    argument parsing, IO formatting, session management, and calling the workflow.
    This test statically scans the pool CLI module source for forbidden patterns.
    """

    # ORM / entity-mutation patterns that must NOT appear in CLI commands
    FORBIDDEN_PATTERNS = {
        "db.query",
        "db.add",
        "db.delete",
        "db.merge",
        "db.execute",
        "db.commit",
        "session.query",
        "session.add",
        "session.delete",
        "session.merge",
        "session.execute",
        "session.commit",
    }

    # Imports that indicate business logic leaking into CLI
    FORBIDDEN_IMPORTS = {
        "sqlalchemy.select",
        "sqlalchemy.insert",
        "sqlalchemy.update",
        "sqlalchemy.delete",
    }

    def _get_pool_cli_source(self) -> str:
        """Read the pool CLI module source."""
        import retrovue.cli.commands.pool as pool_mod
        return inspect.getsource(pool_mod)

    def test_no_orm_queries_in_pool_cli(self):
        """POOL-CLI-005: Pool CLI module has no direct ORM query calls."""
        source = self._get_pool_cli_source()

        violations = []
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern in source:
                violations.append(pattern)

        assert not violations, (
            f"Pool CLI module contains forbidden ORM patterns: {violations}. "
            f"All domain logic must live in workflows/pool_management.py "
            f"(INV-POOL-CLI-DELEGATES-001)."
        )

    def test_no_sqlalchemy_direct_imports_in_pool_cli(self):
        """POOL-CLI-005: Pool CLI module does not import SQLAlchemy query builders."""
        source = self._get_pool_cli_source()
        tree = ast.parse(source)

        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imported_names.add(f"{module}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name)

        violations = imported_names & self.FORBIDDEN_IMPORTS
        assert not violations, (
            f"Pool CLI module imports forbidden SQLAlchemy symbols: {violations}. "
            f"CLI must delegate to workflow (INV-POOL-CLI-DELEGATES-001)."
        )

    def test_pool_cli_only_imports_workflow_entry_points(self):
        """Pool CLI module imports pool operations only from workflows."""
        source = self._get_pool_cli_source()
        tree = ast.parse(source)

        pool_operation_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Check for imports that look like pool operations but don't
                # come from the workflow module
                for alias in node.names:
                    name = alias.name
                    if any(op in name for op in ("create_pool", "list_pool", "inspect_pool", "assign_pool")):
                        if "workflow" not in node.module:
                            pool_operation_imports.append(
                                f"{node.module}.{name}"
                            )

        assert not pool_operation_imports, (
            f"Pool CLI imports pool operations from non-workflow modules: "
            f"{pool_operation_imports}. Must use workflows/pool_management.py."
        )
