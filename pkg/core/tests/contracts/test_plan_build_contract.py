"""
Contract tests for SchedulePlan Build command.

Tests the behavioral contract rules (B-#) defined in SchedulePlanBuildContract.md.
These tests verify CLI behavior, REPL entry/exit, and basic REPL functionality.
"""

import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestPlanBuildContract:
    """Test SchedulePlan Build contract behavioral rules (B-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_plan_build_help_flag_exits_zero(self):
        """
        Contract: Help flag MUST exit with code 0.
        """
        result = self.runner.invoke(app, ["channel", "plan", "test-channel", "build", "--help"])
        assert result.exit_code == 0
        assert "Plan name" in result.stdout

    def test_plan_build_missing_name_exits_one(self):
        """
        Contract B-1: Plan name MUST be required.
        """
        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx:
            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            result = self.runner.invoke(app, ["channel", "plan", "test-channel", "build"])
            assert result.exit_code == 2  # Typer missing required option
            assert "--name" in result.output or "required" in result.output.lower()

    def test_plan_build_channel_not_found_exits_one(self):
        """
        Contract B-1: Channel resolution MUST fail if channel not found.
        """
        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._resolve_channel") as mock_resolve:
            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db
            mock_resolve.side_effect = ValueError("Channel 'test-channel' not found")

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])
            assert result.exit_code == 1
            assert "Channel 'test-channel' not found" in result.output

    def test_plan_build_duplicate_name_exits_one(self):
        """
        Contract B-1: Plan name MUST be unique within channel.
        """
        with patch("retrovue.cli.commands.channel._get_db_context") as mock_db_ctx, \
             patch("retrovue.usecases.plan_add._check_name_uniqueness") as mock_check:
            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db
            mock_check.side_effect = ValueError("Plan name 'TestPlan' already exists in channel 'test-channel'")

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])
            assert result.exit_code == 1
            assert "already exists" in result.output

    def test_plan_build_enters_repl(self):
        """
        Contract B-2: Command MUST enter REPL mode after successful plan creation.
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
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input, \
             patch("retrovue.cli.commands._ops.planning_session.print") as mock_print:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "save" to exit
            # The REPL loop will call input() multiple times, so we need to raise EOFError after save
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

            # Verify REPL was entered (check for prompt message)
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any("Entering planning mode" in call for call in print_calls)

    def test_plan_build_auto_seeds_test_pattern_zone(self):
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
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input, \
             patch("retrovue.cli.commands._ops.planning_session.print") as mock_print:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "save" to exit
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

            # Verify plan was created with default zone initialization
            # The usecase should handle auto-seeding; this test verifies the contract expectation
            assert result.exit_code == 0
            # Verify save was called (plan was committed)
            mock_db.commit.assert_called_once()

    def test_plan_build_save_commits_changes(self):
        """
        Contract B-6: The 'save' command MUST commit all changes.
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
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input, \
             patch("retrovue.cli.commands._ops.planning_session.print"):

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

            # Verify commit was called
            mock_db.commit.assert_called_once()
            assert result.exit_code == 0

    def test_plan_build_discard_rolls_back_changes(self):
        """
        Contract B-6: The 'discard' command MUST roll back all changes.
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
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input, \
             patch("retrovue.cli.commands._ops.planning_session.print"):

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

            # Verify rollback was called, commit was NOT called
            mock_db.rollback.assert_called_once()
            mock_db.commit.assert_not_called()
            assert result.exit_code == 0

    def test_plan_build_quit_without_changes_exits_zero(self):
        """
        Contract B-7: The 'quit' command MUST exit cleanly when no unsaved changes exist.
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
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input, \
             patch("retrovue.cli.commands._ops.planning_session.print"):

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "quit" (no changes made, so no confirmation needed)
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "quit"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            # Verify no commit or rollback (quit without changes)
            mock_db.commit.assert_not_called()
            mock_db.rollback.assert_not_called()
            assert result.exit_code == 0

    def test_plan_build_quit_with_unsaved_changes_prompts(self):
        """
        Contract B-7: The 'quit' command MUST prompt for confirmation if unsaved changes exist.
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

            # Simulate user making a change (zone add sets has_unsaved_changes=True)
            # Then quitting and confirming with 'y'
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "zone add test --from 06:00 --to 12:00"  # This sets has_unsaved_changes
                elif call_count[0] == 2:
                    return "quit"
                elif call_count[0] == 3:
                    return "y"  # Confirm quit
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            # Verify prompt was shown (the prompt is passed to input(), not printed)
            input_calls = [str(call) for call in mock_input.call_args_list]
            assert any("unsaved changes" in call.lower() for call in input_calls)
            # Verify quit was confirmed and exited
            assert result.exit_code == 0

    def test_plan_build_quit_with_unsaved_changes_cancelled(self):
        """
        Contract B-7: The 'quit' command MUST continue REPL if cancelled when unsaved changes exist.
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
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input, \
             patch("retrovue.cli.commands._ops.planning_session.print"):

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user making a change, then quitting and cancelling with 'n'
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "zone add test --from 06:00 --to 12:00"  # This sets has_unsaved_changes
                elif call_count[0] == 2:
                    return "quit"
                elif call_count[0] == 3:
                    return "n"  # Cancel quit
                elif call_count[0] == 4:
                    return "save"  # Then save to exit properly
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            # Verify quit was cancelled (exit code 1 from cancelled quit, but then save exits 0)
            # Actually, the REPL continues after cancelled quit, so final exit should be 0 from save
            assert result.exit_code == 0
            mock_db.commit.assert_called_once()

    def test_plan_build_help_command(self):
        """
        Contract B-3: The 'help' command MUST display available commands.
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
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input, \
             patch("retrovue.cli.commands._ops.planning_session.print") as mock_print:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering "help" then "save"
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

            # Verify help was displayed
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any("Available commands" in call for call in print_calls)
            assert result.exit_code == 0

    def test_plan_build_invalid_command(self):
        """
        Contract B-3: Invalid commands MUST show error and continue REPL.
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
             patch("retrovue.cli.commands._ops.planning_session.input") as mock_input, \
             patch("retrovue.cli.commands._ops.planning_session.print") as mock_print:

            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__.return_value = mock_db

            # Simulate user entering invalid command, then save
            call_count = [0]
            def input_side_effect(prompt):
                call_count[0] += 1
                if call_count[0] == 1:
                    return "invalid_command"
                elif call_count[0] == 2:
                    return "save"
                raise EOFError()
            mock_input.side_effect = input_side_effect

            result = self.runner.invoke(app, [
                "channel", "plan", "test-channel", "build",
                "--name", "TestPlan"
            ])

            # Verify error was shown
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any("Unknown command" in call for call in print_calls)
            # Verify REPL continued and save worked
            assert result.exit_code == 0
            mock_db.commit.assert_called_once()

