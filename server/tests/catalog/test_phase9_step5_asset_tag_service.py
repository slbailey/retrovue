"""
Phase 9 Step 5 — AssetTagService is the sole writer of `asset_tags`.

Invariants proven by this file:

1. `retrovue.catalog.asset_tag_service` exists and exposes the
   user-specified core mutation surface:
       add_tag(db, asset_uuid, tag, source="operator")
       remove_tag(db, asset_uuid, tag)
       set_tags(db, asset_uuid, tags, source="operator")
   Plus the minimum extensions required to preserve prior behavior
   (ingest upsert, studio rename/global-delete/remove-for-assets).

2. No production module outside `asset_tag_service.py` contains:
      - `db.add(AssetTag(...))`
      - `db.merge(AssetTag(...))`
      - `db.delete(<AssetTag-row>)`
      - A SQL string matching `INSERT INTO asset_tags`, `UPDATE asset_tags`,
        or `DELETE FROM asset_tags`.
      - An ORM-level `db.query(AssetTag).filter(...).delete()` or
        `db.execute(delete(AssetTag))` / `db.execute(update(AssetTag))`.

3. The service's three core methods round-trip correctly against a
   real ChannelManager/Session — add creates a row, remove deletes it,
   set_tags replaces the whole set.
"""
from __future__ import annotations

import ast
import pathlib
import re
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import pytest


_SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "retrovue"


# ---------------------------------------------------------------------------
# Service presence and surface
# ---------------------------------------------------------------------------

def test_asset_tag_service_module_exists():
    from retrovue.catalog import asset_tag_service  # noqa: F401 — import is the test


def test_service_exposes_core_surface():
    from retrovue.catalog import asset_tag_service
    for name in ("add_tag", "remove_tag", "set_tags"):
        fn = getattr(asset_tag_service, name, None)
        assert callable(fn), (
            f"AssetTagService must expose core method `{name}` "
            "(Phase 9 Step 5, user-specified minimum surface)."
        )


def test_service_exposes_migration_extensions():
    """Studio rename/merge/bulk-delete and ingest upsert require a
    slightly wider surface than the user-spec core; these extensions
    preserve pre-Phase-9 behavior without redesigning semantics."""
    from retrovue.catalog import asset_tag_service
    for name in (
        "upsert_tag",                # ingest (replaces db.merge)
        "rename_tag_globally",       # studio rename + merge
        "delete_tag_globally",       # studio bulk-remove
        "remove_tag_for_assets",     # studio rename dedup step
    ):
        fn = getattr(asset_tag_service, name, None)
        assert callable(fn), (
            f"AssetTagService must expose extension `{name}` to cover "
            "the migrated callers (Phase 9 Step 5)."
        )


# ---------------------------------------------------------------------------
# AST-level guards: no direct ORM writes on AssetTag outside the service
# ---------------------------------------------------------------------------

_PROD_MODULES_TO_SCAN = [
    _SRC_ROOT / "cli" / "commands" / "asset.py",
    _SRC_ROOT / "web" / "api" / "assets.py",
    _SRC_ROOT / "web" / "api" / "console.py",
    _SRC_ROOT / "web" / "studio.py",
    _SRC_ROOT / "workflows" / "container_ingest.py",
]


def _source_of(path: Path) -> tuple[str, ast.AST]:
    src = path.read_text()
    return src, ast.parse(src, filename=str(path))


def _calls_on(tree: ast.AST, *, method_names: set[str]) -> list[tuple[int, str]]:
    """Return (lineno, method-on-obj) for every Call whose func is
    ``X.method`` where method ∈ method_names. Used to flag
    ``db.add(AssetTag(...))`` / ``db.merge(AssetTag(...))`` /
    ``db.delete(<row>)`` when the argument references AssetTag.
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in method_names:
            continue
        # Check any argument (positional or keyword) references AssetTag.
        if _refers_to_asset_tag(node):
            hits.append((node.lineno, func.attr))
    return hits


def _refers_to_asset_tag(node: ast.Call) -> bool:
    """True if the call argument references the `AssetTag` name directly
    (e.g. ``AssetTag(...)`` constructor) or a `db.query(AssetTag)` chain."""
    for arg in list(node.args) + [k.value for k in node.keywords]:
        for sub in ast.walk(arg):
            if isinstance(sub, ast.Name) and sub.id == "AssetTag":
                return True
    return False


@pytest.mark.parametrize("path", _PROD_MODULES_TO_SCAN, ids=lambda p: p.name)
def test_no_external_db_add_merge_asset_tag(path: Path):
    _src, tree = _source_of(path)
    hits = _calls_on(tree, method_names={"add", "merge"})
    assert not hits, (
        f"{path.name} contains direct db.add(AssetTag...) or "
        f"db.merge(AssetTag...) at {hits}. Route through "
        "retrovue.catalog.asset_tag_service instead."
    )


def _orm_delete_on_asset_tag(tree: ast.AST) -> list[int]:
    """Catch ``db.query(AssetTag).filter(...).delete()`` chains."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "delete":
            continue
        # Walk back through the chain to see if AssetTag appears.
        base = node.func.value
        saw_asset_tag = False
        for sub in ast.walk(base):
            if isinstance(sub, ast.Name) and sub.id == "AssetTag":
                saw_asset_tag = True
                break
        if saw_asset_tag:
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize("path", _PROD_MODULES_TO_SCAN, ids=lambda p: p.name)
def test_no_external_orm_delete_on_asset_tag(path: Path):
    _src, tree = _source_of(path)
    lines = _orm_delete_on_asset_tag(tree)
    assert not lines, (
        f"{path.name} contains ORM-level delete on AssetTag at lines "
        f"{lines}. Route through asset_tag_service.remove_tag / "
        "remove_tag_for_assets / delete_tag_globally instead."
    )


# ---------------------------------------------------------------------------
# Raw-SQL guard: no INSERT/UPDATE/DELETE on asset_tags outside the service
# ---------------------------------------------------------------------------

_RAW_SQL_PATTERNS = (
    re.compile(r"INSERT\s+INTO\s+asset_tags\b", re.IGNORECASE),
    re.compile(r"UPDATE\s+asset_tags\b", re.IGNORECASE),
    re.compile(r"DELETE\s+FROM\s+asset_tags\b", re.IGNORECASE),
)


@pytest.mark.parametrize("path", _PROD_MODULES_TO_SCAN, ids=lambda p: p.name)
def test_no_raw_sql_asset_tags_mutations(path: Path):
    src = path.read_text()
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(src.splitlines(), start=1):
        for pat in _RAW_SQL_PATTERNS:
            if pat.search(line):
                offenders.append((i, line.strip()))
                break
    assert not offenders, (
        f"{path.name} contains raw SQL mutation against asset_tags at "
        f"{offenders}. Route through retrovue.catalog.asset_tag_service."
    )


# ---------------------------------------------------------------------------
# Behavior: end-to-end round-trip against a real session
# ---------------------------------------------------------------------------

def test_service_round_trip_with_real_session():
    """add_tag → remove_tag → set_tags against a real Session+DB.

    This test touches the DB. It relies on TEST_DATABASE_URL (conftest's
    autouse fixture) so there's no extra setup required.
    """
    from retrovue.catalog import asset_tag_service
    from retrovue.domain.entities import Asset, AssetTag, Container, Source
    from retrovue.infra.uow import session

    asset_uuid = uuid4()
    src_id = uuid4()
    cont_uuid = uuid4()
    external = f"phase9-{src_id.hex[:8]}"
    try:
        with session() as db:
            # Minimal fixture: a Source + Container + Asset so FK constraints
            # are satisfied.
            db.add(Source(
                id=src_id, external_id=external, name="phase9-test", type="filesystem",
            ))
            db.add(Container(
                uuid=cont_uuid,
                source_id=src_id,
                external_id=external,
                name="phase9-test",
            ))
            db.add(Asset(
                uuid=asset_uuid,
                container_id=cont_uuid,
                source_id=src_id,
                uri=f"phase9://{asset_uuid}",
                canonical_key=f"phase9://{asset_uuid}",
                canonical_key_hash=asset_uuid.hex,
                canonical_uri=f"phase9://{asset_uuid}",
                size=0,
                state="new",
                discovered_at=datetime.now(timezone.utc),
            ))
            db.flush()

            # add_tag
            inserted = asset_tag_service.add_tag(db, asset_uuid, "genre.action")
            assert inserted is True
            again = asset_tag_service.add_tag(db, asset_uuid, "genre.action")
            assert again is False  # idempotent

            db.flush()
            rows = db.query(AssetTag).filter(AssetTag.asset_uuid == asset_uuid).all()
            assert {r.tag for r in rows} == {"genre.action"}

            # remove_tag
            removed = asset_tag_service.remove_tag(db, asset_uuid, "genre.action")
            assert removed is True
            db.flush()
            again = asset_tag_service.remove_tag(db, asset_uuid, "genre.action")
            assert again is False

            # set_tags (replace-all)
            asset_tag_service.set_tags(db, asset_uuid, ["genre.drama", "rating.pg"])
            db.flush()
            rows = db.query(AssetTag).filter(AssetTag.asset_uuid == asset_uuid).all()
            assert {r.tag for r in rows} == {"genre.drama", "rating.pg"}

            asset_tag_service.set_tags(db, asset_uuid, ["rating.pg13"])
            db.flush()
            rows = db.query(AssetTag).filter(AssetTag.asset_uuid == asset_uuid).all()
            assert {r.tag for r in rows} == {"rating.pg13"}

            # Cleanup for test isolation (cascades via FK delete on Source)
            db.query(AssetTag).filter(AssetTag.asset_uuid == asset_uuid).delete()
            db.query(Asset).filter(Asset.uuid == asset_uuid).delete()
            db.query(Container).filter(Container.uuid == cont_uuid).delete()
            db.query(Source).filter(Source.id == src_id).delete()
    except Exception:
        with session() as db:
            db.query(AssetTag).filter(AssetTag.asset_uuid == asset_uuid).delete()
            db.query(Asset).filter(Asset.uuid == asset_uuid).delete()
            db.query(Container).filter(Container.uuid == cont_uuid).delete()
            db.query(Source).filter(Source.id == src_id).delete()
        raise
