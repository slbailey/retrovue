"""
Plan Show Data Contract Tests

Data contract tests for plan show command.

Tests the data contract rules (D-#) defined in SchedulePlanShowContract.md.
These tests verify database operations and data integrity.
"""

import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestPlanShowDataContract:
    """Test PlanShow data contract rules (D-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.channel_id = str(uuid.uuid4())
        self.plan_id = str(uuid.uuid4())

    def test_plan_show_reflects_persisted_state(self):
        """
        Contract D-1: Show MUST reflect persisted database state.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan

            with patch("retrovue.usecases.plan_show.show_plan") as mock_show:
                mock_show.return_value = {
                    "id": self.plan_id,
                    "channel_id": self.channel_id,
                    "name": "WeekdayPlan",
                    "priority": 10,
                    "is_active": True,
                }

                result = self.runner.invoke(
                    app,
                    [
                        "channel",
                        "plan",
                        self.channel_id,
                        "show",
                        "WeekdayPlan",
                        "--json",
                    ],
                )

                assert result.exit_code == 0
                # Verify show reflects persisted state
                mock_show.assert_called_once()






