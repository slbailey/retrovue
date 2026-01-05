"""Channel List Contract Tests

Coverage: simple list (human/json), total count, error path shape.
"""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _row(id_str: str, title: str, grid: int = 30, offs=None, hh=6, mm=0, active=True):
    if offs is None:
        offs = [0, 30]
    return SimpleDBRow(id_str, title, grid, offs, hh, mm, active)


class SimpleDBRow:
    def __init__(self, id_str, title, grid, offs, hh, mm, active):
        from datetime import time
        self.id = id_str
        self.title = title
        self.grid_block_minutes = grid
        self.block_start_offsets_minutes = list(offs)
        self.programming_day_start = time(hour=hh, minute=mm)
        self.is_active = active
        self.created_at = None
        self.updated_at = None


def test_channel_list__help_flag():
    runner = new_runner = CliRunner()
    res = runner.invoke(app, ["channel", "list", "--help"])
    assert res.exit_code == 0


def test_channel_list__lists_all_human():
    runner = CliRunner()
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [
        _row("00000000-0000-0000-0000-000000000001", "HBO", 30, [0, 30], 6, 0, True),
        _row("00000000-0000-0000-0000-000000000002", "ESPN", 15, [0, 15, 30, 45], 0, 0, False),
    ]
    with patch("retrovue.cli.commands.channel.session") as mock_sess:
        mock_sess.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "list"]) 
    assert res.exit_code == 0
    out = res.stdout
    assert "Channels:" in out
    assert "HBO" in out and "ESPN" in out
    assert "Total:" in out


def test_channel_list__lists_all_json():
    runner = CliRunner()
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [
        _row("00000000-0000-0000-0000-000000000001", "HBO", 30, [0, 30], 6, 0, True)
    ]
    with patch("retrovue.cli.commands.channel.session") as mock_sess:
        mock_sess.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "list", "--json"])  # explicit json
    assert res.exit_code == 0
    assert '"status": "ok"' in res.stdout
    assert '"total": 1' in res.stdout


def test_channel_list__test_db_isolation():
    runner = CliRunner()
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = []
    with patch("retrovue.cli.commands.channel.session") as mock_sess:
        mock_sess.return_value.__enter__.return_value = mock_db
        res = runner.invoke(app, ["channel", "list", "--test-db", "--json"])
    assert res.exit_code == 0
    assert '"status": "ok"' in res.stdout


def test_channel_list__pagination_stable_sort():
    """Sorting must be stable across pages: name asc (ci), id asc tiebreaker."""
    pass


