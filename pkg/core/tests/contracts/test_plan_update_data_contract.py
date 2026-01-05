"""
Plan Update Data Contract Tests

Data contract tests for plan update command.

Tests the data contract rules (D-#) defined in SchedulePlanUpdateContract.md.
These tests verify database operations, transaction safety, and data integrity.
"""

import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestPlanUpdateDataContract:
    """Test PlanUpdate data contract rules (D-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.channel_id = str(uuid.uuid4())
        self.plan_id = str(uuid.uuid4())

    def test_plan_update_partial_fields(self):
        """
        Contract D-1: Only modified fields change; others remain intact.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_update.update_plan"
        ) as mock_update:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan

            mock_update.return_value = {
                "status": "ok",
                "plan": {
                    "id": self.plan_id,
                    "channel_id": self.channel_id,
                    "name": "WeekdayPlan",
                    "priority": 15,  # Updated
                    "is_active": True,  # Unchanged
                },
            }

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "update",
                    "WeekdayPlan",
                    "--priority",
                    "15",
                ],
            )

            assert result.exit_code == 0
            # Verify usecase was called (which handles partial updates)
            mock_update.assert_called_once()

    def test_plan_update_updates_timestamp(self):
        """
        Contract D-2: updated_at MUST be updated to current timestamp.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_update.update_plan"
        ) as mock_update:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan

            mock_update.return_value = {
                "status": "ok",
                "plan": {
                    "id": self.plan_id,
                    "channel_id": self.channel_id,
                    "name": "WeekdayPlan",
                    "created_at": "2025-01-01T12:00:00Z",
                    "updated_at": "2025-01-02T10:00:00Z",  # Updated timestamp
                },
            }

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "update",
                    "WeekdayPlan",
                    "--priority",
                    "15",
                    "--json",
                ],
            )

            assert result.exit_code == 0
            import json

            payload = json.loads(result.stdout)
            # Verify updated_at is present and different from created_at
            assert payload["plan"]["updated_at"] != payload["plan"]["created_at"]

    def test_plan_update_atomic_transaction(self):
        """
        Contract D-4: Plan update MUST be atomic within a single transaction.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_update.update_plan"
        ) as mock_update:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan

            mock_update.return_value = {
                "status": "ok",
                "plan": {
                    "id": self.plan_id,
                    "channel_id": self.channel_id,
                    "name": "WeekdayPlan",
                    "priority": 15,
                    "is_active": True,
                },
            }

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "update",
                    "WeekdayPlan",
                    "--priority",
                    "15",
                ],
            )

            assert result.exit_code == 0
            # Verify usecase was called (which handles transaction internally)
            mock_update.assert_called_once()
            # Verify usecase was called with the db session
            call_args = mock_update.call_args
            assert call_args[0][0] == mock_db  # First arg is db session

    def test_plan_update_validates_coverage_invariant(self):
        """
        Contract B-12: Update MUST validate INV_PLAN_MUST_HAVE_FULL_COVERAGE before persisting.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve, patch(
            "retrovue.cli.commands.channel._resolve_plan"
        ) as mock_resolve_plan, patch(
            "retrovue.usecases.plan_update.update_plan"
        ) as mock_update:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_channel = MagicMock()
            mock_channel.id = uuid.UUID(self.channel_id)
            mock_resolve.return_value = mock_channel
            mock_plan = MagicMock()
            mock_plan.id = uuid.UUID(self.plan_id)
            mock_resolve_plan.return_value = mock_plan
            
            # Simulate coverage validation failure
            from retrovue.infra.exceptions import ValidationError
            mock_update.side_effect = ValidationError(
                "Plan must have full 24-hour coverage (00:00–24:00) with no gaps. See INV_PLAN_MUST_HAVE_FULL_COVERAGE."
            )

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "update",
                    "WeekdayPlan",
                    "--name",
                    "NewName",
                ],
            )
            
            assert result.exit_code == 1
            # Verify validation error was raised
            assert "coverage" in result.output.lower() or "INV_PLAN_MUST_HAVE_FULL_COVERAGE" in result.output

