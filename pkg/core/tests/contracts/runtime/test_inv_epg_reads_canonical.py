"""
Contract tests for INV-EPG-READS-CANONICAL-SCHEDULE-001.

EPG data MUST be derived from the canonical compiled schedule — the same
DB-cached CompiledProgramLog that playout uses. EPG endpoints MUST NOT
call compile_schedule() directly.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from retrovue.runtime.dsl_schedule_service import DslScheduleService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SRC_ROOT = Path(__file__).parents[3] / "src" / "retrovue"
UTC = timezone.utc


def _find_compile_schedule_calls(filepath: Path) -> list[str]:
    """AST-walk a file to find compile_schedule() calls."""
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Match: compile_schedule(...)
            if isinstance(func, ast.Name) and func.id == "compile_schedule":
                violations.append(
                    f"{filepath.name}:{node.lineno} — compile_schedule() call"
                )
            # Match: module.compile_schedule(...)
            elif isinstance(func, ast.Attribute) and func.attr == "compile_schedule":
                violations.append(
                    f"{filepath.name}:{node.lineno} — compile_schedule() call"
                )
    return violations


def _make_program_blocks(
    start: datetime,
    count: int = 3,
    slot_sec: int = 3600,
) -> list[dict]:
    """Generate synthetic program_blocks for testing."""
    blocks = []
    cursor = start
    for i in range(count):
        blocks.append({
            "title": f"Movie {i+1}",
            "asset_id": f"asset.movie_{i+1}",
            "start_at": cursor.isoformat(),
            "slot_duration_sec": slot_sec,
            "episode_duration_sec": slot_sec - 300,
        })
        cursor += timedelta(seconds=slot_sec)
    return blocks


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvEpgReadsCanonical001:
    """INV-EPG-READS-CANONICAL-SCHEDULE-001 contract tests."""

    def test_epg_module_does_not_import_compile_schedule(self):
        """The /api/epg handler in program_director.py MUST NOT call
        compile_schedule(). Verified via AST inspection."""
        pd_path = SRC_ROOT / "runtime" / "program_director.py"
        source = pd_path.read_text()
        tree = ast.parse(source, filename=str(pd_path))

        # Find the get_epg_all function body — look for the /api/epg endpoint
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_epg_all":
                # Walk only this function's body
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Name) and func.id == "compile_schedule":
                            violations.append(
                                f"program_director.py:{child.lineno} — "
                                f"compile_schedule() in get_epg_all"
                            )
                        elif isinstance(func, ast.Attribute) and func.attr == "compile_schedule":
                            violations.append(
                                f"program_director.py:{child.lineno} — "
                                f"compile_schedule() in get_epg_all"
                            )

        assert violations == [], (
            f"EPG handler calls compile_schedule() directly:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_get_canonical_epg_returns_cached_blocks(self):
        """Mock CompiledProgramLog query. get_canonical_epg returns cached
        program_blocks without calling compile_schedule()."""
        window_start = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)

        # Create synthetic program blocks covering the full window
        blocks = _make_program_blocks(window_start, count=24, slot_sec=3600)

        # Build a mock CompiledProgramLog row
        mock_row = MagicMock()
        mock_row.compiled_json = {"program_blocks": blocks}
        mock_row.range_start = window_start
        mock_row.range_end = window_end

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.all.return_value = [mock_row]

            result = DslScheduleService.get_canonical_epg(
                "showtime-cinema", window_start, window_end
            )

        assert result is not None
        assert len(result) == 24
        assert result[0]["title"] == "Movie 1"

    def test_get_canonical_epg_returns_none_when_not_cached(self):
        """Mock empty DB. get_canonical_epg() returns None."""
        window_start = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.all.return_value = []

            result = DslScheduleService.get_canonical_epg(
                "showtime-cinema", window_start, window_end
            )

        assert result is None

    def test_get_canonical_epg_includes_carry_in_block(self):
        """DB has day N-1 row with a block starting 04:00 ending 08:00 that
        carries into day N window. Range overlap query returns this block
        alongside day N blocks."""
        # Day N window: 06:00 Mar 1 to 06:00 Mar 2
        window_start = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)

        # Day N-1 row has a carry-in block from 04:00 to 08:00 Mar 1
        # (starts before window, ends 2h into window)
        carry_in_block = {
            "title": "Late Night Movie",
            "asset_id": "asset.late_movie",
            "start_at": datetime(2026, 3, 1, 4, 0, tzinfo=UTC).isoformat(),
            "slot_duration_sec": 14400,  # 4h → ends 08:00 Mar 1
            "episode_duration_sec": 13000,
        }

        # Day N row has blocks covering 08:00 Mar 1 through 06:00 Mar 2 (22h)
        day_n_blocks = _make_program_blocks(
            datetime(2026, 3, 1, 8, 0, tzinfo=UTC), count=22, slot_sec=3600
        )

        mock_row_prev = MagicMock()
        mock_row_prev.compiled_json = {"program_blocks": [carry_in_block]}
        mock_row_prev.range_start = datetime(2026, 2, 28, 6, 0, tzinfo=UTC)
        mock_row_prev.range_end = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)

        mock_row_curr = MagicMock()
        mock_row_curr.compiled_json = {"program_blocks": day_n_blocks}
        mock_row_curr.range_start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        mock_row_curr.range_end = window_end

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.all.return_value = [
                mock_row_prev, mock_row_curr
            ]

            result = DslScheduleService.get_canonical_epg(
                "showtime-cinema", window_start, window_end
            )

        # The carry-in block should be included since it overlaps the window
        assert result is not None
        carry_in_found = any(b["title"] == "Late Night Movie" for b in result)
        assert carry_in_found, "Carry-in block from previous day not included"
