"""Rename compiled_json -> program_log_json on program_log_days

Revision ID: 20260303_col_rename
Revises: 20260303_rename
Create Date: 2026-03-03 14:00:00.000000

Pure column rename. No type change, no data rewrite, no index changes.
See: docs/contracts/invariants/core/INV-PROGRAM-LOG-COLUMN-NAME-001.md
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260303_col_rename"
down_revision: Union[str, Sequence[str], None] = "20260303_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "program_log_days",
        "compiled_json",
        new_column_name="program_log_json",
    )


def downgrade() -> None:
    op.alter_column(
        "program_log_days",
        "program_log_json",
        new_column_name="compiled_json",
    )
