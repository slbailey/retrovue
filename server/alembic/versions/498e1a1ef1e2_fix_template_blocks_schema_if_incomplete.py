"""fix_template_blocks_schema_if_incomplete

Revision ID: 498e1a1ef1e2
Revises: 8b243580f05e
Create Date: 2025-11-05 15:30:00.000000

Fix-up migration: If schedule_template_blocks still has old structure (template_id, start_time, end_time),
complete the transformation to new structure (name, rule_json only).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "498e1a1ef1e2"
down_revision: Union[str, Sequence[str], None] = "8b243580f05e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Complete the transformation if the old structure still exists."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if table exists
    if "schedule_template_blocks" not in inspector.get_table_names():
        # Table doesn't exist - nothing to fix
        return

    # Use direct SQL query to check columns - be explicit about schema
    # Check in the current schema explicitly
    result = connection.execute(
        sa.text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'schedule_template_blocks' 
            AND table_schema = current_schema()
            ORDER BY column_name
        """)
    )
    column_names = {row[0] for row in result}

    # Check if it has old structure (template_id, start_time, end_time)
    has_template_id = "template_id" in column_names
    
    print(f"Columns found: {sorted(column_names)}")
    print(f"Has template_id (old structure marker): {has_template_id}")
    
    # CRITICAL: If template_id exists, we MUST transform
    # This is the definitive check - template_id means old structure
    needs_transformation = has_template_id
    
    if needs_transformation:
        # Table has old structure - complete the transformation
        print("Detected old structure - completing transformation...")

        # Step 1: Create new standalone blocks table
        op.create_table(
            "schedule_template_blocks_new",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("name", sa.Text(), nullable=False, unique=True),
            sa.Column("rule_json", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_schedule_template_blocks_name", "schedule_template_blocks_new", ["name"])

        # Step 2: Migrate data from old to new (extract unique blocks by rule_json)
        op.execute(
            """
            INSERT INTO schedule_template_blocks_new (id, name, rule_json, created_at, updated_at)
            SELECT DISTINCT ON (rule_json)
                gen_random_uuid() as id,
                'Block-' || substr(md5(rule_json::text), 1, 8) as name,
                rule_json,
                MIN(created_at) as created_at,
                MAX(updated_at) as updated_at
            FROM schedule_template_blocks
            GROUP BY rule_json
            """
        )

        # Step 3: Check if instances table exists, create if not
        if "schedule_template_block_instances" not in inspector.get_table_names():
            op.create_table(
                "schedule_template_block_instances",
                sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
                sa.Column(
                    "template_id",
                    postgresql.UUID(as_uuid=True),
                    nullable=False,
                ),
                sa.Column(
                    "block_id",
                    postgresql.UUID(as_uuid=True),
                    nullable=False,
                ),
                sa.Column("start_time", sa.Text(), nullable=False),
                sa.Column("end_time", sa.Text(), nullable=False),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                ),
                sa.ForeignKeyConstraint(
                    ["template_id"],
                    ["schedule_templates.id"],
                    ondelete="CASCADE",
                    name="fk_template_block_instances_template_id",
                ),
                sa.ForeignKeyConstraint(
                    ["block_id"],
                    ["schedule_template_blocks_new.id"],
                    ondelete="RESTRICT",
                    name="fk_template_block_instances_block_id",
                ),
            )

            op.create_index(
                "ix_schedule_template_block_instances_template_id",
                "schedule_template_block_instances",
                ["template_id"],
            )
            op.create_index(
                "ix_schedule_template_block_instances_block_id",
                "schedule_template_block_instances",
                ["block_id"],
            )
            op.create_index(
                "ix_schedule_template_block_instances_start_time",
                "schedule_template_block_instances",
                ["start_time"],
            )

        # Step 4: Create instances linking templates to blocks
        op.execute(
            """
            INSERT INTO schedule_template_block_instances (
                id, template_id, block_id, start_time, end_time, created_at, updated_at
            )
            SELECT
                gen_random_uuid() as id,
                stb.template_id,
                stbn.id as block_id,
                stb.start_time,
                stb.end_time,
                stb.created_at,
                stb.updated_at
            FROM schedule_template_blocks stb
            JOIN schedule_template_blocks_new stbn ON stb.rule_json = stbn.rule_json
            ON CONFLICT DO NOTHING
            """
        )

        # Step 5: Drop old table and indexes
        try:
            op.drop_index("ix_schedule_template_blocks_start_time", table_name="schedule_template_blocks")
        except Exception:
            pass  # Index might not exist
        try:
            op.drop_index("ix_schedule_template_blocks_template_id", table_name="schedule_template_blocks")
        except Exception:
            pass  # Index might not exist
        op.drop_table("schedule_template_blocks")

        # Step 6: Rename new table to final name
        op.rename_table("schedule_template_blocks_new", "schedule_template_blocks")

        # Step 7: Update foreign key constraint
        try:
            op.drop_constraint(
                "fk_template_block_instances_block_id",
                "schedule_template_block_instances",
                type_="foreignkey",
            )
        except Exception:
            pass  # Constraint might not exist or already correct
        op.create_foreign_key(
            "fk_template_block_instances_block_id",
            "schedule_template_block_instances",
            "schedule_template_blocks",
            ["block_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        print("Transformation completed successfully!")
    else:
        # Table already has new structure - nothing to do
        print("Table already has new structure - no changes needed")


def downgrade() -> None:
    """This is a fix-up migration - downgrade is a no-op."""
    pass
