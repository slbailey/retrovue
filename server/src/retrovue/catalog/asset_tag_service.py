"""AssetTagService — single writer for the ``asset_tags`` table.

Phase 9 Step 5: every mutation of ``asset_tags`` (INSERT / UPDATE /
DELETE, whether via ORM or raw SQL) must go through this module.
Callers are the CLI, the REST API (``/api/assets`` + deprecated
``/api/console``), the ingest workflow (``container_ingest``), and the
studio UI.

Direct writes outside this module are forbidden and enforced by the
Phase 9 Step 5 regression guard (``test_phase9_step5_asset_tag_service``).

The service exposes the user-spec core surface —
``add_tag`` / ``remove_tag`` / ``set_tags`` — plus a small set of
migration extensions that preserve pre-Phase-9 behavior for the studio
(rename, global delete, bulk delete for a selection) and for ingest
(upsert). Every extension corresponds to an existing write path whose
behavior must be preserved bit-for-bit.
"""
from __future__ import annotations

from typing import Iterable
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from ..domain.entities import AssetTag
from ..domain.tag_normalization import canonicalize_tag, normalize_tag_set


def _coerce_uuid(asset_uuid) -> UUID:
    if isinstance(asset_uuid, UUID):
        return asset_uuid
    return UUID(str(asset_uuid))


# ---------------------------------------------------------------------------
# Core surface (user-specified)
# ---------------------------------------------------------------------------

def add_tag(
    db: Session,
    asset_uuid,
    tag: str,
    *,
    source: str = "operator",
) -> bool:
    """Add a single tag to an asset. Idempotent.

    Tag is canonicalized before lookup/insert. Returns True if a new
    row was inserted; False if the tag already existed (or canonicalized
    to empty).

    Handles back-to-back calls in the same session: with ``autoflush``
    off (Retrovue's default), a pending-but-unflushed insert is invisible
    to a regular ``db.query``. We therefore also check ``db.new`` for a
    matching pending AssetTag before querying the DB, so repeated calls
    within one transaction remain idempotent.
    """
    canonical = canonicalize_tag(tag)
    if not canonical:
        return False
    aid = _coerce_uuid(asset_uuid)
    for pending in list(db.new):
        if (
            isinstance(pending, AssetTag)
            and pending.asset_uuid == aid
            and pending.tag == canonical
        ):
            return False
    existing = (
        db.query(AssetTag)
        .filter(AssetTag.asset_uuid == aid, AssetTag.tag == canonical)
        .first()
    )
    if existing is not None:
        return False
    db.add(AssetTag(asset_uuid=aid, tag=canonical, source=source))
    return True


def remove_tag(db: Session, asset_uuid, tag: str) -> bool:
    """Remove a single tag from an asset. Idempotent.

    The tag argument is matched LITERALLY against the stored form, not
    canonicalized first. This preserves the pre-Phase-9 REST API
    semantic (``DELETE /api/assets/{uuid}/tags/{tag}``) where callers
    deleted by the exact stored form. Studio's bulk-remove flow passes
    canonical forms.

    Returns True if a row was deleted; False if no matching row existed.
    """
    aid = _coerce_uuid(asset_uuid)
    existing = (
        db.query(AssetTag)
        .filter(AssetTag.asset_uuid == aid, AssetTag.tag == tag)
        .first()
    )
    if existing is None:
        return False
    db.delete(existing)
    return True


def set_tags(
    db: Session,
    asset_uuid,
    tags: Iterable[str],
    *,
    source: str = "operator",
) -> None:
    """Replace the entire tag set for an asset.

    Canonicalizes and normalizes the input. Semantics match the
    pre-Phase-9 CLI ``retrovue asset tags set`` flow: delete all
    existing rows for the asset, then insert one row per canonical
    tag with the given source.
    """
    aid = _coerce_uuid(asset_uuid)
    db.query(AssetTag).filter(AssetTag.asset_uuid == aid).delete(
        synchronize_session=False
    )
    for tag_val in normalize_tag_set(tags):
        canonical = canonicalize_tag(tag_val)
        if not canonical:
            continue
        db.add(AssetTag(asset_uuid=aid, tag=canonical, source=source))


# ---------------------------------------------------------------------------
# Migration extensions (required to preserve pre-Phase-9 behavior)
# ---------------------------------------------------------------------------

def upsert_tag(
    db: Session,
    asset_uuid,
    tag: str,
    *,
    source: str = "ingest",
) -> None:
    """Upsert a single tag.

    Migration extension for ``container_ingest.py`` which previously
    used ``db.merge(AssetTag(...))`` at ingest time. Preserves the
    idempotent-insert semantic without raising on conflict.
    """
    canonical = canonicalize_tag(tag)
    if not canonical:
        return
    aid = _coerce_uuid(asset_uuid)
    db.merge(AssetTag(asset_uuid=aid, tag=canonical, source=source))


def rename_tag_globally(db: Session, old_tag: str, new_tag: str) -> int:
    """Rename every occurrence of ``old_tag`` to ``new_tag`` across all
    assets. Returns the number of rows updated.

    Does **not** handle dedup (assets that already have both old and
    new). Callers that need dedup should invoke ``remove_tag_for_assets``
    first — matching the pre-Phase-9 ``_execute_tag_rename`` flow in
    ``web/studio.py``.
    """
    result = db.execute(
        sa_update(AssetTag).where(AssetTag.tag == old_tag).values(tag=new_tag)
    )
    return result.rowcount or 0


def delete_tag_globally(db: Session, tag: str) -> int:
    """Delete every row with this exact tag across all assets. Returns
    the number of rows deleted.

    Migration extension for the studio "remove tag everywhere" flow.
    """
    result = db.execute(sa_delete(AssetTag).where(AssetTag.tag == tag))
    return result.rowcount or 0


def remove_tag_for_assets(
    db: Session,
    tag: str,
    asset_uuids: Iterable,
) -> int:
    """Delete rows with this tag for a specific set of assets. Returns
    the number of rows deleted.

    Migration extension for the studio rename/merge dedup step: assets
    that already have the target tag need the old tag row removed
    before the global rename runs.
    """
    uuids = [_coerce_uuid(a) for a in asset_uuids]
    if not uuids:
        return 0
    result = db.execute(
        sa_delete(AssetTag).where(
            AssetTag.tag == tag,
            AssetTag.asset_uuid.in_(uuids),
        )
    )
    return result.rowcount or 0
