"""Channel Show Contract Tests.

Coverage: human/json success, not-found, help.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _row(id_str: str, title: str, grid=30, offs=None, hh=6, mm=0, active=True):
    from datetime import time
    if offs is None:
        offs = [0, 30]
    return SimpleNamespace(
        id=id_str,
        title=title,
        grid_block_minutes=grid,
        block_start_offsets_minutes=list(offs),
        programming_day_start=time(hour=hh, minute=mm),
        is_active=active,
        created_at=None,
        updated_at=None,
    )


def _mock_exec_returning(row):
    m = MagicMock()
    m.scalars.return_value.first.return_value = row
    return m


def test_channel_show__help_flag():
    runner = CliRunner()
    res = runner.invoke(app, ["channel", "show", "--help"]) 
    assert res.exit_code == 0


def test_channel_show__success_human():
    runner = CliRunner()
    fake = _row("00000000-0000-0000-0000-000000000001", "HBO")
    mock_db = MagicMock()
    mock_db.execute.return_value = _mock_exec_returning(fake)
    with patch("retrovue.cli.commands.channel.session") as mock_sess:
        mock_sess.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "show", "hbo"]) 
    assert res.exit_code == 0
    assert "HBO" in res.stdout


def test_channel_show__success_json():
    runner = CliRunner()
    fake = _row("00000000-0000-0000-0000-000000000001", "HBO")
    mock_db = MagicMock()
    mock_db.execute.return_value = _mock_exec_returning(fake)
    with patch("retrovue.cli.commands.channel.session") as mock_sess:
        mock_sess.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "show", "hbo", "--json"]) 
    assert res.exit_code == 0
    assert '"status": "ok"' in res.stdout
    assert '"name": "HBO"' in res.stdout


def test_channel_show__not_found():
    runner = CliRunner()
    mock_db = MagicMock()
    nr = MagicMock(); nr.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = nr
    with patch("retrovue.cli.commands.channel.session") as mock_sess:
        mock_sess.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "show", "missing-slug"]) 
    assert res.exit_code == 1
    assert "not found" in res.stdout.lower() or "not found" in res.stderr.lower()


def test_channel_show__test_db_isolation():
    runner = CliRunner()
    fake = _row("00000000-0000-0000-0000-000000000001", "HBO")
    mock_db = MagicMock(); mock_db.execute.return_value = _mock_exec_returning(fake)
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_db
    mock_cm.__exit__.return_value = False
    with patch("retrovue.cli.commands.channel._get_db_context", return_value=mock_cm):
        res = runner.invoke(app, ["channel", "show", "hbo", "--test-db"]) 
    assert res.exit_code == 0


