"""Migrate asset_tags from legacy CATEGORY:value to canonical namespace.value form.

INV-TAG-CANONICAL-FORM-001: All persisted tags MUST be in namespace.value form.
tag_canonical_form.md section C defines the migration semantics.

Legacy colon-prefixed tags (TAG:hbo, NETWORK:cbs) are converted to canonical
form (tag.hbo, network.cbs). Plain tags without any prefix are given the
default 'tag' namespace (hbo -> tag.hbo).

Migration is idempotent: already-canonical tags are not modified.
Duplicates created by migration are collapsed (C-4).

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2026-04-09
"""
from alembic import op

revision = "h1i2j3k4l5m6"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None

# Legacy prefix -> canonical namespace
_PREFIX_MAP = {
    "TAG": "tag",
    "NETWORK": "network",
    "GENRE": "genre",
    "RATING": "rating",
}


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Migrate colon-prefixed tags to canonical dot form
    for legacy_prefix, ns in _PREFIX_MAP.items():
        # Find tags with this legacy prefix pattern (case-insensitive)
        pattern = f"{legacy_prefix}:%"
        rows = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT asset_uuid, tag FROM asset_tags WHERE tag LIKE :pattern"
            ),
            {"pattern": pattern},
        ).fetchall()

        for asset_uuid, tag in rows:
            value = tag.split(":", 1)[1]
            canonical = f"{ns}.{value.strip().lower()}"

            # Check if the canonical form already exists for this asset
            exists = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT 1 FROM asset_tags WHERE asset_uuid = :uuid AND tag = :tag"
                ),
                {"uuid": asset_uuid, "tag": canonical},
            ).fetchone()

            if exists:
                # C-4: Duplicate — delete the legacy form
                conn.execute(
                    __import__("sqlalchemy").text(
                        "DELETE FROM asset_tags WHERE asset_uuid = :uuid AND tag = :old_tag"
                    ),
                    {"uuid": asset_uuid, "old_tag": tag},
                )
            else:
                # Convert legacy to canonical
                conn.execute(
                    __import__("sqlalchemy").text(
                        "UPDATE asset_tags SET tag = :new_tag WHERE asset_uuid = :uuid AND tag = :old_tag"
                    ),
                    {"new_tag": canonical, "uuid": asset_uuid, "old_tag": tag},
                )

    # Step 2: Migrate plain tags (no colon, no dot with known namespace) to tag.{value}
    # Find tags that have no colon and no dot (or dot but not a known namespace)
    all_remaining = conn.execute(
        __import__("sqlalchemy").text(
            "SELECT asset_uuid, tag FROM asset_tags WHERE tag NOT LIKE '%:%' AND tag NOT LIKE '%.%'"
        )
    ).fetchall()

    for asset_uuid, tag in all_remaining:
        canonical = f"tag.{tag.strip().lower()}"

        exists = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT 1 FROM asset_tags WHERE asset_uuid = :uuid AND tag = :tag"
            ),
            {"uuid": asset_uuid, "tag": canonical},
        ).fetchone()

        if exists:
            conn.execute(
                __import__("sqlalchemy").text(
                    "DELETE FROM asset_tags WHERE asset_uuid = :uuid AND tag = :old_tag"
                ),
                {"uuid": asset_uuid, "old_tag": tag},
            )
        else:
            conn.execute(
                __import__("sqlalchemy").text(
                    "UPDATE asset_tags SET tag = :new_tag WHERE asset_uuid = :uuid AND tag = :old_tag"
                ),
                {"new_tag": canonical, "uuid": asset_uuid, "old_tag": tag},
            )


def downgrade() -> None:
    conn = op.get_bind()
    import sqlalchemy as sa

    # Reverse: canonical namespace.value -> legacy CATEGORY:value
    ns_to_prefix = {v: k for k, v in _PREFIX_MAP.items()}

    all_canonical = conn.execute(
        sa.text("SELECT asset_uuid, tag FROM asset_tags WHERE tag LIKE '%.%'")
    ).fetchall()

    for asset_uuid, tag in all_canonical:
        if "." in tag:
            ns, value = tag.split(".", 1)
            prefix = ns_to_prefix.get(ns)
            if prefix:
                legacy = f"{prefix}:{value}"
                exists = conn.execute(
                    sa.text(
                        "SELECT 1 FROM asset_tags WHERE asset_uuid = :uuid AND tag = :tag"
                    ),
                    {"uuid": asset_uuid, "tag": legacy},
                ).fetchone()

                if not exists:
                    conn.execute(
                        sa.text(
                            "UPDATE asset_tags SET tag = :new_tag WHERE asset_uuid = :uuid AND tag = :old_tag"
                        ),
                        {"new_tag": legacy, "uuid": asset_uuid, "old_tag": tag},
                    )
