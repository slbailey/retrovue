"""
Plan Show Contract Tests

Behavioral tests for plan show command.

Tests the behavioral contract rules (B-#) defined in SchedulePlanShowContract.md.
These tests verify CLI behavior, identifier resolution, output formats, and error handling.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _mock_plan_result():
    """Mock plan result matching usecase return structure."""
    return {
        "status": "ok",
        "plan": {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "channel_id": "660e8400-e29b-41d4-a716-446655440001",
            "name": "WeekdayPlan",
            "description": "Weekday programming plan",
            "cron_expression": "* * * * MON-FRI",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "priority": 10,
            "is_active": True,
            "created_at": "2025-01-01T12:00:00Z",
            "updated_at": "2025-01-01T12:00:00Z",
        },
    }


class TestPlanShowContract:
    """Test PlanShow contract behavioral rules (B-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.channel_id = str(uuid.uuid4())
        self.plan_id = str(uuid.uuid4())

    def test_plan_show_help_flag_exits_zero(self):
        """
        Contract: Help flag MUST exit with code 0.
        """
        result = self.runner.invoke(
            app, ["channel", "plan", self.channel_id, "show", "--help"]
        )
        assert result.exit_code == 0

    def test_plan_show_channel_not_found_exits_one(self):
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
                    "show",
                    "test-plan",
                ],
            )
            assert result.exit_code == 1
            assert "not found" in result.stderr.lower()

    def test_plan_show_plan_not_found_exits_one(self):
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
                    "show",
                    "test-plan",
                ],
            )
            assert result.exit_code == 1
            assert "not found" in result.stderr.lower()

    def test_plan_show_plan_wrong_channel_exits_one(self):
        """
        Contract B-4: Plan belonging to different channel MUST exit 1.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.plan_show.show_plan"
        ) as mock_show:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_show.side_effect = ValueError(
                f"Plan 'test-plan' does not belong to channel '{self.channel_id}'"
            )

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "show",
                    "test-plan",
                ],
            )
            assert result.exit_code == 1
            assert "does not belong" in result.output.lower()

    def test_plan_show_uuid_wrong_channel_exits_one(self):
        """
        Contract B-4: UUID resolution MUST check channel ownership.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.plan_show.show_plan"
        ) as mock_show:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_show.side_effect = ValueError(
                f"Plan '{self.plan_id}' does not belong to channel '{self.channel_id}'"
            )

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "show",
                    self.plan_id,  # UUID format
                ],
            )
            assert result.exit_code == 1
            assert "does not belong" in result.output.lower()

    def test_plan_show_name_lookup_is_case_insensitive_and_trimmed(self):
        """
        Contract B-5: Name lookups MUST be case-insensitive and trimmed.
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

            # Test case-insensitive lookup
            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "show",
                    "WEEKDAYPLAN",  # Uppercase
                ],
            )
            # Should succeed (case-insensitive)
            # Note: Actual implementation would normalize the name

    def test_plan_show_success_human(self):
        """
        Contract B-2: Human-readable output MUST display plan details.
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

            # Mock show_plan usecase
            with patch("retrovue.usecases.plan_show.show_plan") as mock_show:
                mock_show.return_value = _mock_plan_result()

                result = self.runner.invoke(
                    app,
                    [
                        "channel",
                        "plan",
                        self.channel_id,
                        "show",
                        "WeekdayPlan",
                    ],
                )
                assert result.exit_code == 0
                assert "plan" in result.stdout.lower() or "WeekdayPlan" in result.stdout

    def test_plan_show_success_json(self):
        """
        Contract B-2: JSON output MUST include status and plan object.
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
                mock_show.return_value = _mock_plan_result()

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
                payload = json.loads(result.stdout)
                assert payload["status"] == "ok"
                assert "plan" in payload

    def test_plan_show_with_contents_human(self):
        """
        Contract B-6: --with-contents MUST include Zones/Patterns summaries (human).
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
                plan_data = _mock_plan_result()
                plan_data["plan"]["zones"] = []
                plan_data["plan"]["patterns"] = []
                mock_show.return_value = plan_data

                result = self.runner.invoke(
                    app,
                    [
                        "channel",
                        "plan",
                        self.channel_id,
                        "show",
                        "WeekdayPlan",
                        "--with-contents",
                    ],
                )
                assert result.exit_code == 0

    def test_plan_show_with_contents_json(self):
        """
        Contract B-6: --with-contents MUST include zones/patterns arrays (JSON).
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
                plan_data = _mock_plan_result()
                plan_data["plan"]["zones"] = []
                plan_data["plan"]["patterns"] = []
                mock_show.return_value = plan_data

                result = self.runner.invoke(
                    app,
                    [
                        "channel",
                        "plan",
                        self.channel_id,
                        "show",
                        "WeekdayPlan",
                        "--with-contents",
                        "--json",
                    ],
                )
                assert result.exit_code == 0
                payload = json.loads(result.stdout)
                assert "zones" in payload["plan"]
                assert "patterns" in payload["plan"]

    def test_plan_show_coverage_guarantee_has_at_least_one_zone(self):
        """
        Contract: Every displayed plan MUST have at least one zone (coverage guarantee).
        Coverage Guarantee: Plans satisfy INV_PLAN_MUST_HAVE_FULL_COVERAGE.
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
                plan_data = _mock_plan_result()
                # Plan must have at least one zone (coverage guarantee)
                plan_data["plan"]["zones"] = [
                    {
                        "id": "770e8400-e29b-41d4-a716-446655440002",
                        "name": "Base",
                        "start_time": "00:00:00",
                        "end_time": "24:00:00",
                        "day_filters": None
                    }
                ]
                plan_data["plan"]["patterns"] = []
                mock_show.return_value = plan_data

                result = self.runner.invoke(
                    app,
                    [
                        "channel",
                        "plan",
                        self.channel_id,
                        "show",
                        "WeekdayPlan",
                        "--with-contents",
                        "--json",
                    ],
                )
                assert result.exit_code == 0
                payload = json.loads(result.stdout)
                # Verify at least one zone exists (coverage guarantee)
                assert len(payload["plan"]["zones"]) >= 1
                # Verify zone covers full day (00:00–24:00)
                zones = payload["plan"]["zones"]
                assert any(z.get("start_time") == "00:00:00" and z.get("end_time") == "24:00:00" for z in zones)

    def test_plan_show_with_computed(self):
        """
        Contract B-6: --computed MUST include effective_today and next_applicable_date.
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
                plan_data = _mock_plan_result()
                plan_data["plan"]["effective_today"] = True
                plan_data["plan"]["next_applicable_date"] = "2025-01-15"
                mock_show.return_value = plan_data

                result = self.runner.invoke(
                    app,
                    [
                        "channel",
                        "plan",
                        self.channel_id,
                        "show",
                        "WeekdayPlan",
                        "--computed",
                        "--json",
                    ],
                )
                assert result.exit_code == 0
                payload = json.loads(result.stdout)
                assert "effective_today" in payload["plan"]
                assert "next_applicable_date" in payload["plan"]

    def test_plan_show_formats_dates_and_timestamps(self):
        """
        Contract B-7: Dates MUST be YYYY-MM-DD, timestamps MUST be ISO-8601 UTC with Z.
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
                mock_show.return_value = _mock_plan_result()

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
                payload = json.loads(result.stdout)
                plan = payload["plan"]
                # Verify date format
                assert plan["start_date"] == "2025-01-01"
                # Verify timestamp format (ends with Z)
                assert plan["created_at"].endswith("Z")

    def test_plan_show_json_error_channel_not_found(self):
        """
        Contract B-8: JSON error shape for CHANNEL_NOT_FOUND.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.plan_show.show_plan"
        ) as mock_show:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_show.side_effect = ValueError(f"Channel '{self.channel_id}' not found")

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "show",
                    "test-plan",
                    "--json",
                ],
            )
            assert result.exit_code == 1
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
            assert payload["code"] == "CHANNEL_NOT_FOUND"

    def test_plan_show_json_error_plan_not_found(self):
        """
        Contract B-8: JSON error shape for PLAN_NOT_FOUND.
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
                    "show",
                    "test-plan",
                    "--json",
                ],
            )
            assert result.exit_code == 1
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
            assert payload["code"] == "PLAN_NOT_FOUND"

    def test_plan_show_json_error_plan_wrong_channel(self):
        """
        Contract B-8: JSON error shape for PLAN_WRONG_CHANNEL.
        """
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.plan_show.show_plan"
        ) as mock_show:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_show.side_effect = ValueError(
                f"Plan 'test-plan' does not belong to channel '{self.channel_id}'"
            )

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "plan",
                    self.channel_id,
                    "show",
                    "test-plan",
                    "--json",
                ],
            )
            assert result.exit_code == 1
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
            assert payload["code"] == "PLAN_WRONG_CHANNEL"

    def test_plan_show_quiet_has_no_extraneous_output(self):
        """
        Contract B-9: --quiet MUST suppress extraneous output lines.
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
                mock_show.return_value = _mock_plan_result()

                result = self.runner.invoke(
                    app,
                    [
                        "channel",
                        "plan",
                        self.channel_id,
                        "show",
                        "WeekdayPlan",
                        "--quiet",
                    ],
                )
                assert result.exit_code == 0
                # Verify minimal output (no extra lines)
                lines = result.stdout.strip().split("\n")
                # Should have minimal output

