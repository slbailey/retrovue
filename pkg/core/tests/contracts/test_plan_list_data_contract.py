"""
Plan List Data Contract Tests

Data contract tests for plan list command.

Tests the data contract rules (D-#) defined in SchedulePlanListContract.md.
These tests verify database operations and data integrity.
"""

import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestPlanListDataContract:
    """Test PlanList data contract rules (D-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.channel_id = str(uuid.uuid4())

    def test_plan_list_reflects_current_state(self):
        """
        Contract D-1: List MUST reflect current database state.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.usecases.plan_list.list_plans"
        ) as mock_list:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel

            # Mock current state - usecase returns dict with status/total/plans
            mock_list.return_value = {
                "status": "ok",
                "total": 1,
                "plans": [
                    {
                        "id": str(uuid.uuid4()),
                        "channel_id": self.channel_id,
                        "name": "CurrentPlan",
                        "priority": 10,
                        "is_active": True,
                    }
                ],
            }

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "list",
                    "--json",
                ],
            )

            assert result.exit_code == 0
            # Verify list reflects current state
            mock_list.assert_called_once()

    def test_plan_list_testdb_isolation(self):
        """
        Contract D-4: --test-db MUST use isolated test database session.
        """
        with patch("retrovue.cli.commands.channel._get_db_context") as mock_test_db, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.usecases.plan_list.list_plans"
        ) as mock_list:
            mock_db_cm = MagicMock()
            mock_db = MagicMock()
            mock_db_cm.__enter__.return_value = mock_db
            mock_test_db.return_value = mock_db_cm

            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_list.return_value = {"status": "ok", "total": 0, "plans": []}

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "list",
                    "--test-db",
                ],
            )

            assert result.exit_code == 0
            # Verify test-db context was used
            mock_test_db.assert_called_once()

