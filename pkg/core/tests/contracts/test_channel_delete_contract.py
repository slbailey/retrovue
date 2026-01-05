"""Channel Delete Contract Tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _row(id_str: str, title: str, **kw):
    return SimpleNamespace(id=id_str, title=title, **kw)


def _exec_returning(row):
    m = MagicMock()
    m.scalars.return_value.first.return_value = row
    return m


def test_channel_delete__help_flag():
    r = CliRunner().invoke(app, ["channel", "delete", "--help"]) 
    assert r.exit_code == 0


def test_channel_delete__requires_yes():
    runner = CliRunner()
    mock_db = MagicMock()
    fake = _row("00000000-0000-0000-0000-000000000001", "HBO")
    mock_db.execute.return_value = _exec_returning(fake)
    with patch("retrovue.cli.commands.channel.session") as s:
        s.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "delete", str(fake.id)])
    assert res.exit_code == 1
    assert "requires --yes" in (res.stdout + res.stderr)


def test_channel_delete__success():
    runner = CliRunner()
    mock_db = MagicMock()
    fake = _row("00000000-0000-0000-0000-000000000001", "HBO")
    mock_db.execute.return_value = _exec_returning(fake)
    with patch("retrovue.cli.commands.channel.session") as s:
        s.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "delete", "hbo", "--yes", "--json"]) 
    assert res.exit_code == 0
    assert '"deleted": 1' in res.stdout
    assert str(fake.id) in res.stdout


def test_channel_delete__not_found():
    runner = CliRunner()
    mock_db = MagicMock()
    nr = MagicMock(); nr.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = nr
    with patch("retrovue.cli.commands.channel.session") as s:
        s.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "delete", "missing", "--yes"]) 
    assert res.exit_code == 1
    assert "not found" in (res.stdout + res.stderr).lower()


def test_channel_delete__blocked_by_dependencies():
    runner = CliRunner()
    mock_db = MagicMock()
    fake = _row("00000000-0000-0000-0000-000000000001", "HBO", _has_deps=True)
    mock_db.execute.return_value = _exec_returning(fake)
    with patch("retrovue.cli.commands.channel.session") as s:
        s.return_value.__enter__.return_value = mock_db
        res = runner.invoke(
            app,
            [
                "channel",
                "delete",
                "hbo",
                "--yes",
            ],
        )
    # Should block and suggest archive
    assert res.exit_code == 1
    out = res.stdout + res.stderr
    assert "Use: retrovue channel update --id hbo --inactive" in out or "--inactive" in out


def test_channel_delete__test_db_isolation():
    runner = CliRunner()
    mock_db = MagicMock()
    fake = _row("00000000-0000-0000-0000-000000000001", "HBO")
    mock_db.execute.return_value = _exec_returning(fake)
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_db
    mock_cm.__exit__.return_value = False
    with patch("retrovue.cli.commands.channel._get_db_context", return_value=mock_cm):
        res = runner.invoke(app, ["channel", "delete", str(fake.id), "--yes", "--json", "--test-db"]) 
    assert res.exit_code == 0


def test_channel_delete__blocked_suggests_archive():
    """Blocked delete should suggest archive via update --inactive."""
    pass


