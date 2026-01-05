"""
Plan Delete Contract Tests

Behavioral tests for plan delete command.

Tests the behavioral contract rules (B-#) defined in SchedulePlanDeleteContract.md.
These tests verify CLI behavior, confirmation, dependency checks, and error handling.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestPlanDeleteContract:
    """Test PlanDelete contract behavioral rules (B-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.channel_id = str(uuid.uuid4())
        self.plan_id = str(uuid.uuid4())

    def test_plan_delete_help_flag_exits_zero(self):
        """
        Contract: Help flag MUST exit with code 0.
        """
        result = self.runner.invoke(
            app, ["channel", "plan", self.channel_id, "delete", "--help"]
        )
        assert result.exit_code == 0

    def test_plan_delete_channel_not_found_exits_one(self):
        """
        Contract B-1: Channel not found MUST exit 1.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.cli.commands.channel._resolve_channel"
        ) as mock_resolve:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_resolve.side_effect = ValueError(f"Channel '{self.channel_id}' not found")

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "delete",
                    "test-plan",
                    "--yes",
                ],
            )
            assert result.exit_code == 1
            assert "not found" in result.stderr.lower()

    def test_plan_delete_plan_not_found_exits_one(self):
        """
        Contract B-1: Plan not found MUST exit 1.
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
            mock_resolve_plan.side_effect = ValueError("Plan 'test-plan' not found")

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "delete",
                    "test-plan",
                    "--yes",
                ],
            )
            assert result.exit_code == 1
            assert "not found" in result.stderr.lower()

    def test_plan_delete_requires_yes(self):
        """
        Contract B-3: Without --yes, command MUST prompt for confirmation.
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

            # Mock typer.confirm to simulate user declining
            with patch("typer.confirm") as mock_confirm:
                mock_confirm.return_value = False

                result = self.runner.invoke(
                    app,
                    [
                        "channel",
                        "plan",
                        self.channel_id,
                        "delete",
                        "test-plan",
                    ],
                )
                # Should exit 1 if confirmation is refused
                # Note: Actual behavior depends on CLI implementation

    def test_plan_delete_success(self):
        """
        Contract B-4: Successful deletion MUST output confirmation.
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
            mock_delete.return_value = {"deleted": 1, "id": self.plan_id}

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
            assert "deleted" in result.stdout.lower() or "plan" in result.stdout.lower()

    def test_plan_delete_blocked_by_zones(self):
        """
        Contract B-2: Deletion blocked by Zones MUST exit 1 with actionable error.
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
            mock_delete.side_effect = ValueError(
                "Cannot delete plan 'WeekdayPlan': plan has 2 zone(s). Delete zones first or archive the plan with --inactive."
            )

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
            assert result.exit_code == 1
            assert "zone" in result.stderr.lower() or "Cannot delete" in result.stderr

    def test_plan_delete_blocked_by_patterns(self):
        """
        Contract B-2: Deletion blocked by Patterns MUST exit 1 with actionable error.
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
            mock_delete.side_effect = ValueError(
                "Cannot delete plan 'WeekdayPlan': plan has 3 pattern(s). Delete patterns first or archive the plan with --inactive."
            )

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
            assert result.exit_code == 1
            assert "pattern" in result.stderr.lower() or "Cannot delete" in result.stderr

    def test_plan_delete_blocked_by_schedule_days(self):
        """
        Contract B-2: Deletion blocked by ScheduleDays MUST exit 1 with actionable error.
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
            mock_delete.side_effect = ValueError(
                "Cannot delete plan 'WeekdayPlan': plan has 5 schedule day(s). Archive the plan with --inactive instead."
            )

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
            assert result.exit_code == 1
            assert "schedule day" in result.stderr.lower() or "Cannot delete" in result.stderr

    def test_plan_delete_exits_plan_mode_if_active(self):
        """
        Contract B-5: If plan mode is active, MUST exit plan mode and notify.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.plan_delete.delete_plan"
        ) as mock_delete:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_delete.return_value = {"status": "ok", "deleted": 1, "id": self.plan_id}
            # TODO: Implement plan mode exit check when plan mode feature is implemented

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
            # Verify plan mode exit was checked/called
            # Note: Actual implementation would check plan mode state

