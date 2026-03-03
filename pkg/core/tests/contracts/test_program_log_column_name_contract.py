"""
Contract Test — INV-PROGRAM-LOG-COLUMN-NAME-001

Asserts that ProgramLogDay uses `program_log_json` as its JSONB storage column,
and that the retired name `compiled_json` no longer exists.

See: docs/contracts/invariants/core/INV-PROGRAM-LOG-COLUMN-NAME-001.md
"""

from __future__ import annotations

from retrovue.domain.entities import ProgramLogDay


def test_program_log_json_column_exists() -> None:
    """INV-PROGRAM-LOG-COLUMN-NAME-001: canonical column name is program_log_json."""
    col_names = {c.name for c in ProgramLogDay.__table__.columns}
    assert "program_log_json" in col_names, (
        f"Expected 'program_log_json' in ProgramLogDay columns, got: {sorted(col_names)}"
    )


def test_compiled_json_column_does_not_exist() -> None:
    """INV-PROGRAM-LOG-COLUMN-NAME-001: retired name compiled_json must not exist."""
    col_names = {c.name for c in ProgramLogDay.__table__.columns}
    assert "compiled_json" not in col_names, (
        "Retired column name 'compiled_json' still present in ProgramLogDay"
    )
