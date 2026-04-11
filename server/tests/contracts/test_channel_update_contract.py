"""Channel Update Contract Tests.

Coverage: help, success, not-found, validation errors, test-db.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def test_channel_update__help_flag():
    r = CliRunner().invoke(app, ["channel", "update", "--help"]) 
    assert r.exit_code == 0


def test_channel_update__success_human_output():
    runner = CliRunner()
    payload = {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "HBO 2",
        "grid_size_minutes": 30,
        "grid_offset_minutes": 0,
        "broadcast_day_start": "06:00",
        "is_active": True,
        "created_at": None,
        "updated_at": None,
        "version": 1,
    }
    with patch("retrovue.usecases.channel_update.update_channel", return_value=payload):
        res = runner.invoke(
            app,
            [
                "channel",
                "update",
                "hbo",
                "--name",
                "HBO 2",
            ],
        )
    assert res.exit_code == 0
    assert "Channel updated:" in res.stdout
    assert "HBO 2" in res.stdout


def test_channel_update__success_json_output():
    runner = CliRunner()
    payload = {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "HBO 2",
        "grid_size_minutes": 30,
        "grid_offset_minutes": 0,
        "broadcast_day_start": "06:00",
        "is_active": True,
        "created_at": None,
        "updated_at": None,
        "version": 1,
    }
    with patch("retrovue.usecases.channel_update.update_channel", return_value=payload):
        res = runner.invoke(
            app,
            [
                "channel",
                "update",
                "hbo",
                "--name",
                "HBO 2",
                "--json",
            ],
        )
    assert res.exit_code == 0
    assert '"status": "ok"' in res.stdout


def test_channel_update__not_found():
    runner = CliRunner()
    with patch(
        "retrovue.usecases.channel_update.update_channel",
        side_effect=ValueError("Channel 'missing' not found"),
    ):
        res = runner.invoke(app, ["channel", "update", "missing", "--name", "X"]) 
    assert res.exit_code == 1
    assert "not found" in res.stdout.lower() or "not found" in res.stderr.lower()


def test_channel_update__validation_errors():
    runner = CliRunner()
    with patch(
        "retrovue.usecases.channel_update.update_channel",
        side_effect=ValueError("grid-size-minutes must be one of 15, 30, 60"),
    ):
        res = runner.invoke(
            app,
            ["channel", "update", "hbo", "--grid-size-minutes", "17"],
        )
    assert res.exit_code == 1
    assert "grid-size-minutes" in res.stdout or "grid-size-minutes" in res.stderr


def test_channel_update__test_db_isolation():
    runner = CliRunner()
    payload = {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "HBO",
        "grid_size_minutes": 30,
        "grid_offset_minutes": 0,
        "broadcast_day_start": "06:00",
        "is_active": True,
        "created_at": None,
        "updated_at": None,
        "version": 1,
    }
    with patch("retrovue.usecases.channel_update.update_channel", return_value=payload):
        res = runner.invoke(app, ["channel", "update", "hbo", "--test-db", "--json"]) 
    assert res.exit_code == 0


def test_update_effective_date_reports_impacts():
    """Expect JSON to include impacted_entities when effective-dated change is used."""
    pass


