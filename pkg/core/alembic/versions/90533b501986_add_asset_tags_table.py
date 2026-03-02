"""add asset_tags table

Revision ID: 90533b501986
Revises: 28f102750e77
Create Date: 2026-03-02 00:00:00.000000

Schema for INV-ASSET-TAG-PERSISTENCE-001 and AssetTaggingContract.md D-1/D-2.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "90533b501986"
down_revision = "28f102750e77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_tags",
        sa.Column("asset_uuid", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag", sa.String(255), nullable=False),
        sa.Column("source", sa.String(50), nullable=False, server_default="operator"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["asset_uuid"],
            ["assets.uuid"],
            ondelete="CASCADE",
            name="fk_asset_tags_asset_uuid",
        ),
        sa.PrimaryKeyConstraint("asset_uuid", "tag", name="pk_asset_tags"),
    )
    op.create_index("ix_asset_tags_asset_uuid", "asset_tags", ["asset_uuid"])
    op.create_index("ix_asset_tags_tag", "asset_tags", ["tag"])


def downgrade() -> None:
    op.drop_index("ix_asset_tags_tag", table_name="asset_tags")
    op.drop_index("ix_asset_tags_asset_uuid", table_name="asset_tags")
    op.drop_table("asset_tags")
