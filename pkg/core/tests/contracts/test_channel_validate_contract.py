"""Channel Validate Contract Tests.

Coverage: help, all-ok, violations JSON, strict mode, test-db.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _row(id_str: str, title: str, grid=30, offsets=None, hh=6, mm=0):
    from datetime import time
    if offsets is None:
        offsets = [0, 30]
    return SimpleNamespace(
        id=id_str,
        title=title,
        slug=title.lower().replace(" ", "-"),
        grid_block_minutes=grid,
        block_start_offsets_minutes=list(offsets),
        programming_day_start=time(hour=hh, minute=mm),
        is_active=True,
        created_at=None,
        updated_at=None,
    )


def test_channel_validate__help_flag():
    r = CliRunner().invoke(app, ["channel", "validate", "--help"]) 
    assert r.exit_code == 0


def test_channel_validate__all_ok_human():
    runner = CliRunner()
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [
        _row("00000000-0000-0000-0000-000000000001", "HBO", 30, [0, 30], 6, 0)
    ]
    with patch("retrovue.cli.commands.channel.session") as s:
        s.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "validate"]) 
    assert res.exit_code == 0
    assert "Violations:" in res.stdout


def test_channel_validate__json_reports_violations():
    runner = CliRunner()
    # Misaligned anchor vs offset → CHN-006
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [
        _row("00000000-0000-0000-0000-000000000001", "HBO", 30, [0, 30], 6, 5)
    ]
    with patch("retrovue.cli.commands.channel.session") as s:
        s.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "validate", "--json"]) 
    assert res.exit_code == 2
    assert '"code": "CHN-006"' in res.stdout


def test_channel_validate__strict_mode_fails_on_lints():
    runner = CliRunner()
    # grid=60 with non-zero offsets → CHN-014 warning; strict should fail with code 2
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [
        _row("00000000-0000-0000-0000-000000000001", "HBO", 60, [30], 6, 0)
    ]
    with patch("retrovue.cli.commands.channel.session") as s:
        s.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "validate", "--strict"]) 
    assert res.exit_code == 2


def test_channel_validate__test_db_isolation():
    runner = CliRunner()
    mock_db = MagicMock(); mock_db.query.return_value.all.return_value = []
    with patch("retrovue.cli.commands.channel.session") as s:
        s.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "validate", "--test-db", "--json"]) 
    assert res.exit_code in (0, 1, 2)  # shape check only
    assert '"status"' in res.stdout


