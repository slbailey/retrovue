from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20250115_rename_block_assignments_to_programs"
down_revision: str | None = "20251102_asset_meta"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Rename table from schedule_plan_block_assignments to programs
    op.rename_table("schedule_plan_block_assignments", "programs")

    # Rename foreign key constraints if they exist
    # Note: PostgreSQL automatically renames constraints when tables are renamed,
    # but we may need to update constraint names explicitly
    # Check and rename foreign key constraint names if needed
    op.execute(
        """
        DO $$
        BEGIN
            -- Rename foreign key constraints if they exist
            IF EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname LIKE '%schedule_plan_block_assignments%'
            ) THEN
                ALTER TABLE programs 
                RENAME CONSTRAINT schedule_plan_block_assignments_channel_id_fkey 
                TO programs_channel_id_fkey;
            END IF;
            
            IF EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname LIKE '%schedule_plan_block_assignments%'
            ) THEN
                ALTER TABLE programs 
                RENAME CONSTRAINT schedule_plan_block_assignments_plan_id_fkey 
                TO programs_plan_id_fkey;
            END IF;
            
            IF EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname LIKE '%schedule_plan_block_assignments%'
            ) THEN
                ALTER TABLE programs 
                RENAME CONSTRAINT schedule_plan_block_assignments_label_id_fkey 
                TO programs_label_id_fkey;
            END IF;
        END $$;
        """
    )

    # Rename indexes
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_schedule_plan_block_assignments_channel_id') THEN
                ALTER INDEX ix_schedule_plan_block_assignments_channel_id RENAME TO ix_programs_channel_id;
            END IF;
            
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_schedule_plan_block_assignments_plan_id') THEN
                ALTER INDEX ix_schedule_plan_block_assignments_plan_id RENAME TO ix_programs_plan_id;
            END IF;
            
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_schedule_plan_block_assignments_start_time') THEN
                ALTER INDEX ix_schedule_plan_block_assignments_start_time RENAME TO ix_programs_start_time;
            END IF;
            
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_schedule_plan_block_assignments_label_id') THEN
                ALTER INDEX ix_schedule_plan_block_assignments_label_id RENAME TO ix_programs_label_id;
            END IF;
        END $$;
        """
    )

    # Rename column if content_reference exists and needs to be renamed to content_ref
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'programs' AND column_name = 'content_reference'
            ) THEN
                ALTER TABLE programs RENAME COLUMN content_reference TO content_ref;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Rename column back if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'programs' AND column_name = 'content_ref'
            ) THEN
                ALTER TABLE programs RENAME COLUMN content_ref TO content_reference;
            END IF;
        END $$;
        """
    )

    # Rename indexes back
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_programs_channel_id') THEN
                ALTER INDEX ix_programs_channel_id RENAME TO ix_schedule_plan_block_assignments_channel_id;
            END IF;
            
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_programs_plan_id') THEN
                ALTER INDEX ix_programs_plan_id RENAME TO ix_schedule_plan_block_assignments_plan_id;
            END IF;
            
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_programs_start_time') THEN
                ALTER INDEX ix_programs_start_time RENAME TO ix_schedule_plan_block_assignments_start_time;
            END IF;
            
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_programs_label_id') THEN
                ALTER INDEX ix_programs_label_id RENAME TO ix_schedule_plan_block_assignments_label_id;
            END IF;
        END $$;
        """
    )

    # Rename foreign key constraints back
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname LIKE '%programs%'
            ) THEN
                ALTER TABLE programs 
                RENAME CONSTRAINT programs_channel_id_fkey 
                TO schedule_plan_block_assignments_channel_id_fkey;
            END IF;
            
            IF EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname LIKE '%programs%'
            ) THEN
                ALTER TABLE programs 
                RENAME CONSTRAINT programs_plan_id_fkey 
                TO schedule_plan_block_assignments_plan_id_fkey;
            END IF;
            
            IF EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname LIKE '%programs%'
            ) THEN
                ALTER TABLE programs 
                RENAME CONSTRAINT programs_label_id_fkey 
                TO schedule_plan_block_assignments_label_id_fkey;
            END IF;
        END $$;
        """
    )

    # Rename table back
    op.rename_table("programs", "schedule_plan_block_assignments")

