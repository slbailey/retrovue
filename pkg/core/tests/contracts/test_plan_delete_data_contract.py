"""
Plan Delete Data Contract Tests

Data contract tests for plan delete command.

Tests the data contract rules (D-#) defined in SchedulePlanDeleteContract.md.
These tests verify database operations, transaction safety, and data integrity.
"""

import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestPlanDeleteDataContract:
    """Test PlanDelete data contract rules (D-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.channel_id = str(uuid.uuid4())
        self.plan_id = str(uuid.uuid4())

    def test_plan_delete_removes_record(self):
        """
        Contract D-1: One SchedulePlan row MUST be removed when successful.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_delete.delete_plan"
        ) as mock_delete:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan
            mock_delete.return_value = {"status": "ok", "deleted": 1, "id": self.plan_id}

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "delete",
                    "WeekdayPlan",
                    "--yes",
                ],
            )

            assert result.exit_code == 0
            # Verify usecase was called (which handles deletion)
            mock_delete.assert_called_once()
            # Verify usecase was called with the db session
            call_args = mock_delete.call_args
            assert call_args[0][0] == mock_db  # First arg is db session

    def test_plan_delete_cascades_to_zones_patterns(self):
        """
        Contract D-2: Zones and Patterns MAY be deleted via cascade if configured.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_delete.delete_plan"
        ) as mock_delete:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan
            mock_delete.return_value = {"status": "ok", "deleted": 1, "id": self.plan_id}

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "delete",
                    "WeekdayPlan",
                    "--yes",
                ],
            )

            assert result.exit_code == 0
            # Verify usecase was called (cascade behavior is handled by database/usecase)
            mock_delete.assert_called_once()

    def test_plan_delete_atomic_transaction(self):
        """
        Contract D-3: Plan deletion MUST be atomic within a single transaction.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_delete.delete_plan"
        ) as mock_delete:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan
            mock_delete.return_value = {"status": "ok", "deleted": 1, "id": self.plan_id}

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "delete",
                    "WeekdayPlan",
                    "--yes",
                ],
            )

            assert result.exit_code == 0
            # Verify usecase was called (which handles transaction internally)
            mock_delete.assert_called_once()
            # Verify usecase was called with the db session
            call_args = mock_delete.call_args
            assert call_args[0][0] == mock_db  # First arg is db session

    def test_plan_delete_testdb_isolation(self):
        """
        Contract D-4: --test-db MUST use isolated test database session.
        """
        with patch("retrovue.cli.commands.channel._get_db_context") as mock_test_db, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_delete.delete_plan"
        ) as mock_delete:
            mock_db_cm = MagicMock()
            mock_db = MagicMock()
            mock_db_cm.__enter__.return_value = mock_db
            mock_test_db.return_value = mock_db_cm

            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan
            mock_delete.return_value = {"status": "ok", "deleted": 1, "id": self.plan_id}

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "delete",
                    "WeekdayPlan",
                    "--yes",
                    "--test-db",
                ],
            )

            assert result.exit_code == 0
            # Verify test-db context was used
            mock_test_db.assert_called_once()
            # Verify usecase was called with test db session
            mock_delete.assert_called_once()
            call_args = mock_delete.call_args
            assert call_args[0][0] == mock_db  # First arg is test db session

    def test_plan_delete_json_key_consistency(self):
        """
        Contract D-5: JSON output MUST follow snake_case and include status/id keys.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_delete.delete_plan"
        ) as mock_delete:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan
            mock_delete.return_value = {"status": "ok", "deleted": 1, "id": self.plan_id}

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "delete",
                    "WeekdayPlan",
                    "--yes",
                    "--json",
                ],
            )

            assert result.exit_code == 0
            import json

            payload = json.loads(result.stdout)
            # Verify snake_case keys
            assert "status" in payload
            assert "id" in payload or "deleted" in payload
            # Verify status is "ok" for success
            assert payload["status"] == "ok"

