"""restructure_template_blocks_to_standalone_with_instances

Revision ID: 8b243580f05e
Revises: 4f6d64aeabce
Create Date: 2025-11-05 14:41:31.595996

Restructure template blocks to be standalone reusable entities.
- Blocks become standalone with name and rule_json
- Templates reference blocks via junction table (instances) with template-specific timing
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8b243580f05e"
down_revision: Union[str, Sequence[str], None] = "4f6d64aeabce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Restructure template blocks to standalone with instances junction table."""
    # Step 1: Create new standalone blocks table (temp name during migration)
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

    # Step 2: Create instances junction table
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
        sa.Column("start_time", sa.Text(), nullable=False),  # HH:MM format
        sa.Column("end_time", sa.Text(), nullable=False),  # HH:MM format
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
        # Note: FK will be updated when we rename schedule_template_blocks_new to schedule_template_blocks
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["schedule_template_blocks_new.id"],
            ondelete="RESTRICT",
            name="fk_template_block_instances_block_id",
        ),
    )

    # Create indexes for instances
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

    # Step 3: Migrate data from old structure to new
    # Extract unique blocks by rule_json and create standalone blocks
    # For each unique rule_json, create a block with auto-generated name
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
        """
    )

    # Step 5: Drop old table and indexes (only if table exists and has been migrated)
    # Check if old table exists before dropping
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "schedule_template_blocks" in inspector.get_table_names():
        op.drop_index("ix_schedule_template_blocks_start_time", table_name="schedule_template_blocks")
        op.drop_index(
            "ix_schedule_template_blocks_template_id", table_name="schedule_template_blocks"
        )
        op.drop_table("schedule_template_blocks")

    # Step 6: Rename new table to final name
    op.rename_table("schedule_template_blocks_new", "schedule_template_blocks")

    # Step 7: Update foreign key constraint to reference renamed table
    # PostgreSQL automatically updates FK constraints when tables are renamed, so this should work
    # But we'll verify by checking constraint exists and recreating if needed
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    fk_constraints = inspector.get_foreign_keys("schedule_template_block_instances")
    needs_update = any(
        fk["name"] == "fk_template_block_instances_block_id"
        and fk.get("referred_table") != "schedule_template_blocks"
        for fk in fk_constraints
    )
    if needs_update:
        op.drop_constraint(
            "fk_template_block_instances_block_id",
            "schedule_template_block_instances",
            type_="foreignkey",
        )
        op.create_foreign_key(
            "fk_template_block_instances_block_id",
            "schedule_template_block_instances",
            "schedule_template_blocks",
            ["block_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    """Revert to old structure (blocks belong to templates)."""
    # Step 1: Rename current standalone blocks table to temp name
    op.rename_table("schedule_template_blocks", "schedule_template_blocks_standalone")
    op.drop_index("ix_schedule_template_blocks_name", table_name="schedule_template_blocks_standalone")

    # Step 2: Create old-style blocks table (with template_id)
    op.create_table(
        "schedule_template_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("start_time", sa.Text(), nullable=False),
        sa.Column("end_time", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["schedule_templates.id"],
            ondelete="CASCADE",
            name="fk_schedule_template_blocks_template_id",
        ),
    )

    op.create_index(
        "ix_schedule_template_blocks_template_id",
        "schedule_template_blocks",
        ["template_id"],
    )
    op.create_index(
        "ix_schedule_template_blocks_start_time",
        "schedule_template_blocks",
        ["start_time"],
    )

    # Step 3: Migrate data back: create blocks for each instance
    op.execute(
        """
        INSERT INTO schedule_template_blocks (
            id, template_id, start_time, end_time, rule_json, created_at, updated_at
        )
        SELECT
            gen_random_uuid() as id,
            stbi.template_id,
            stbi.start_time,
            stbi.end_time,
            stbs.rule_json,
            stbi.created_at,
            stbi.updated_at
        FROM schedule_template_block_instances stbi
        JOIN schedule_template_blocks_standalone stbs ON stbi.block_id = stbs.id
        """
    )

    # Step 4: Drop instances table
    op.drop_index(
        "ix_schedule_template_block_instances_start_time",
        table_name="schedule_template_block_instances",
    )
    op.drop_index(
        "ix_schedule_template_block_instances_block_id",
        table_name="schedule_template_block_instances",
    )
    op.drop_index(
        "ix_schedule_template_block_instances_template_id",
        table_name="schedule_template_block_instances",
    )
    op.drop_table("schedule_template_block_instances")

    # Step 5: Drop standalone blocks table
    op.drop_table("schedule_template_blocks_standalone")
