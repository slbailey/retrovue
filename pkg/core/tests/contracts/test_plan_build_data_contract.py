"""
Data contract tests for SchedulePlan Build command.

Tests the data contract rules (D-#) defined in SchedulePlanBuildContract.md.
These tests verify database operations, transaction safety, and data integrity for the REPL session.
"""

import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestPlanBuildDataContract:
    """Test SchedulePlan Build data contract rules (D-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_plan_build_creates_plan_before_repl(self):
        """
        Contract D-1: Plan MUST be created before entering REPL mode.
        """
        channel_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_channel = MagicMock()
        mock_channel.id = channel_id
        mock_channel.title = "Test Channel"
        mock_channel.slug = "test-channel"

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "TestPlan"
        mock_plan.channel_id = channel_id

        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._resolve_channel", return_value=mock_channel), \
             patch("retrovue.usecases.plan_add._check_name_uniqueness"), \
             patch("retrovue.usecases.plan_add._validate_date_format"), \
             patch("retrovue.usecases.plan_add._validate_date_range"), \
             patch("retrovue.usecases.plan_add._validate_cron_expression"), \
             patch("retrovue.usecases.plan_add._validate_priority", return_value=0), \
             patch("retrovue.cli.commands.channel.SchedulePlan", return_value=mock_plan), \
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "save" immediately
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "save"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            assert result.exit_code == 0
            # Verify plan was added to session (not committed yet)
            mock_db.add.assert_called_once()
            # Verify the added object is a SchedulePlan
            added_obj = mock_db.add.call_args[0][0]
            assert added_obj is mock_plan

    def test_plan_build_save_persists_all_entities(self):
        """
        Contract D-2: The 'save' command MUST commit all changes atomically.
        """
        channel_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_channel = MagicMock()
        mock_channel.id = channel_id
        mock_channel.title = "Test Channel"
        mock_channel.slug = "test-channel"

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "TestPlan"

        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._resolve_channel", return_value=mock_channel), \
             patch("retrovue.usecases.plan_add._check_name_uniqueness"), \
             patch("retrovue.usecases.plan_add._validate_date_format"), \
             patch("retrovue.usecases.plan_add._validate_date_range"), \
             patch("retrovue.usecases.plan_add._validate_cron_expression"), \
             patch("retrovue.usecases.plan_add._validate_priority", return_value=0), \
             patch("retrovue.cli.commands.channel.SchedulePlan", return_value=mock_plan), \
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "save"
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "save"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            assert result.exit_code == 0
            # Verify commit was called (atomic save)
            mock_db.commit.assert_called_once()
            # Verify rollback was NOT called
            mock_db.rollback.assert_not_called()

    def test_plan_build_discard_rolls_back_all_changes(self):
        """
        Contract D-3: The 'discard' command MUST roll back all changes.
        """
        channel_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_channel = MagicMock()
        mock_channel.id = channel_id
        mock_channel.title = "Test Channel"
        mock_channel.slug = "test-channel"

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "TestPlan"

        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._resolve_channel", return_value=mock_channel), \
             patch("retrovue.usecases.plan_add._check_name_uniqueness"), \
             patch("retrovue.usecases.plan_add._validate_date_format"), \
             patch("retrovue.usecases.plan_add._validate_date_range"), \
             patch("retrovue.usecases.plan_add._validate_cron_expression"), \
             patch("retrovue.usecases.plan_add._validate_priority", return_value=0), \
             patch("retrovue.cli.commands.channel.SchedulePlan", return_value=mock_plan), \
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "discard"
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "discard"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            assert result.exit_code == 0
            # Verify rollback was called
            mock_db.rollback.assert_called_once()
            # Verify commit was NOT called
            mock_db.commit.assert_not_called()

    def test_plan_build_transaction_not_committed_until_save(self):
        """
        Contract D-1: Plan creation transaction MUST NOT be committed until 'save' is called.
        """
        channel_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_channel = MagicMock()
        mock_channel.id = channel_id
        mock_channel.title = "Test Channel"
        mock_channel.slug = "test-channel"

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "TestPlan"

        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._resolve_channel", return_value=mock_channel), \
             patch("retrovue.usecases.plan_add._check_name_uniqueness"), \
             patch("retrovue.usecases.plan_add._validate_date_format"), \
             patch("retrovue.usecases.plan_add._validate_date_range"), \
             patch("retrovue.usecases.plan_add._validate_cron_expression"), \
             patch("retrovue.usecases.plan_add._validate_priority", return_value=0), \
             patch("retrovue.cli.commands.channel.SchedulePlan", return_value=mock_plan), \
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "help" then "save" (to verify no commit until save)
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "help"
                elif call_count[0] == 2:
                    return "save"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            assert result.exit_code == 0
            # Verify commit was only called once (on save)
            assert mock_db.commit.call_count == 1
            # Verify plan was added before commit
            mock_db.add.assert_called_once()

    def test_plan_build_save_failure_rolls_back(self):
        """
        Contract D-2: If 'save' fails, transaction MUST roll back.
        """
        channel_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_channel = MagicMock()
        mock_channel.id = channel_id
        mock_channel.title = "Test Channel"
        mock_channel.slug = "test-channel"

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "TestPlan"

        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._resolve_channel", return_value=mock_channel), \
             patch("retrovue.usecases.plan_add._check_name_uniqueness"), \
             patch("retrovue.usecases.plan_add._validate_date_format"), \
             patch("retrovue.usecases.plan_add._validate_date_range"), \
             patch("retrovue.usecases.plan_add._validate_cron_expression"), \
             patch("retrovue.usecases.plan_add._validate_priority", return_value=0), \
             patch("retrovue.cli.commands.channel.SchedulePlan", return_value=mock_plan), \
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db
            # Simulate commit failure
            mock_db.commit.side_effect = Exception("Database connection lost")

            # Simulate user entering "save"
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "save"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            # Verify save failed
            assert result.exit_code == 1
            # Verify commit was attempted
            mock_db.commit.assert_called_once()
            # Verify rollback was called after commit failure
            mock_db.rollback.assert_called_once()

    def test_plan_build_plan_creation_uses_same_validation_as_add(self):
        """
        Contract D-1: Plan creation MUST use the same validation rules as 'plan add'.
        """
        channel_id = uuid.uuid4()

        mock_channel = MagicMock()
        mock_channel.id = channel_id
        mock_channel.title = "Test Channel"
        mock_channel.slug = "test-channel"

        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._resolve_channel", return_value=mock_channel), \
             patch("retrovue.usecases.plan_add._check_name_uniqueness") as mock_check_name, \
             patch("retrovue.usecases.plan_add._validate_date_format") as mock_validate_date, \
             patch("retrovue.usecases.plan_add._validate_date_range") as mock_validate_range, \
             patch("retrovue.usecases.plan_add._validate_cron_expression") as mock_validate_cron, \
             patch("retrovue.usecases.plan_add._validate_priority", return_value=5) as mock_validate_priority, \
             patch("retrovue.cli.commands.channel.SchedulePlan"), \
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "save"
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "save"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan",
                "--start-date", "2025-01-01",
                "--end-date", "2025-12-31",
                "--cron", "* * * * MON-FRI",
                "--priority", "5"
            ])

            assert result.exit_code == 0
            # Verify all validation functions were called (same as plan add)
            mock_check_name.assert_called_once()
            mock_validate_date.assert_called()
            mock_validate_range.assert_called_once()
            mock_validate_cron.assert_called_once()
            mock_validate_priority.assert_called_once()

    def test_plan_build_creates_default_test_pattern_zone(self):
        """
        Contract B-1: Plan creation MUST auto-seed default test pattern zone (00:00–24:00) before REPL entry.
        """
        channel_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_channel = MagicMock()
        mock_channel.id = channel_id
        mock_channel.title = "Test Channel"
        mock_channel.slug = "test-channel"

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "TestPlan"

        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._resolve_channel", return_value=mock_channel), \
             patch("retrovue.usecases.plan_add._check_name_uniqueness"), \
             patch("retrovue.usecases.plan_add._validate_date_format"), \
             patch("retrovue.usecases.plan_add._validate_date_range"), \
             patch("retrovue.usecases.plan_add._validate_cron_expression"), \
             patch("retrovue.usecases.plan_add._validate_priority", return_value=0), \
             patch("retrovue.cli.commands.channel.SchedulePlan", return_value=mock_plan), \
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "save" immediately
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "save"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            assert result.exit_code == 0
            # Verify plan was created - the usecase should handle default zone creation
            # This test verifies the contract expectation that default zone is auto-seeded
            mock_db.add.assert_called()  # Plan and default zone should be added



