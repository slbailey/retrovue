"""Channel Add Contract Tests

Behavioral tests for ChannelAddContract.md.
"""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _mock_channel_result():
    return {
        "id": 7,
        "name": "RetroToons",
        "grid_size_minutes": 30,
        "grid_offset_minutes": 0,
        "broadcast_day_start": "06:00",
        "is_active": True,
        "version": 1,
        "created_at": "2025-01-01T12:00:00Z",
        "updated_at": None,
    }


class TestChannelAddContract:
    def setup_method(self):
        self.runner = CliRunner()

    def test_channel_add_missing_name_exits_one(self):
        result = self.runner.invoke(
            app,
            [
                "channel",
                "add",
                "--grid-size-minutes",
                "30",
            ],
        )
        assert result.exit_code == 1
        assert "Error: --name is required" in result.stderr

    def test_channel_add_success_human(self):
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.channel_add.add_channel"
        ) as mock_uc:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_uc.return_value = _mock_channel_result()

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "add",
                    "--name",
                    "RetroToons",
                    "--grid-size-minutes",
                    "30",
                    "--broadcast-day-start",
                    "06:00",
                ],
            )
            assert result.exit_code == 0
            assert "Channel created:" in result.stdout
            assert "ID:" in result.stdout
            assert "RetroToons" in result.stdout

    def test_channel_add_success_json(self):
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.channel_add.add_channel"
        ) as mock_uc:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_uc.return_value = _mock_channel_result()

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "add",
                    "--name",
                    "RetroToons",
                    "--grid-size-minutes",
                    "30",
                    "--json",
                ],
            )
            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert payload["status"] == "ok"
            for k in [
                "id",
                "name",
                "grid_size_minutes",
                "grid_offset_minutes",
                "broadcast_day_start",
                "is_active",
                "version",
            ]:
                assert k in payload["channel"], f"missing key {k}"

    def test_channel_add_grid_size_validation_error(self):
        # When usecase raises validation errors, CLI should exit 1 with error message
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.channel_add.add_channel"
        ) as mock_uc:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_uc.side_effect = ValueError("grid-size-minutes must be one of 15, 30, 60")

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "add",
                    "--name",
                    "RetroToons",
                    "--grid-size-minutes",
                    "13",
                    "--grid-offset-minutes",
                    "0",
                ],
            )
            assert result.exit_code == 1
            assert "grid-size-minutes" in result.stderr

    def test_channel_add_help_flag_exits_zero(self):
        result = self.runner.invoke(app, ["channel", "add", "--help"])
        assert result.exit_code == 0
        assert "--name" in result.stdout

    def test_channel_add_duplicate_name_fails(self):
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.channel_add.add_channel"
        ) as mock_uc:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_uc.side_effect = ValueError("Channel name already exists.")

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "add",
                    "--name",
                    "RetroToons",
                    "--grid-size-minutes",
                    "30",
                    "--grid-offset-minutes",
                    "0",
                ],
            )
            assert result.exit_code == 1
            assert "Channel name already exists" in result.stderr

    def test_channel_add_test_db_support(self):
        with patch("retrovue.cli.commands.channel.session") as mock_session, patch(
            "retrovue.usecases.channel_add.add_channel"
        ) as mock_uc:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_uc.return_value = _mock_channel_result()

            result = self.runner.invoke(
                app,
                [
                    "channel",
                    "add",
                    "--name",
                    "RetroToons",
                    "--grid-size-minutes",
                    "30",
                    "--grid-offset-minutes",
                    "0",
                    "--test-db",
                    "--json",
                ],
            )
            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert payload["status"] == "ok"



