"""
Integration test fixtures — seeds minimal catalog data so pool resolution works.

After RETA-227 restructured the test database, integration tests that use
real DslScheduleService + CatalogAssetResolver need assets in the DB.
This conftest creates a Source → Container → Assets (with AssetEditorial)
so that pools filtering by ``type: episode`` resolve correctly.
"""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session, sessionmaker

from retrovue.domain.entities import Asset, AssetEditorial, Container, Source
from retrovue.infra.db import get_engine


# Deterministic UUIDs so repeated runs are idempotent
_SOURCE_UUID = uuid_mod.UUID("00000000-0000-0000-0000-fface0000000")
_CONTAINER_UUID = uuid_mod.UUID("00000000-0000-0000-0001-fface0000000")

# 100 episodes at 30 min each — enough for 48 slots across multiple days.
_NUM_EPISODES = 100
_EPISODE_DURATION_MS = 30 * 60 * 1000  # 30 minutes


def _asset_uuid(index: int) -> uuid_mod.UUID:
    """Deterministic UUID for test asset N."""
    return uuid_mod.UUID(f"00000000-0000-0000-1000-{index:012d}")


def _seed(db: Session) -> None:
    """Insert Source, Container, 100 Assets, and 100 AssetEditorial rows."""
    source = Source(
        id=_SOURCE_UUID,
        external_id="integration-test-source",
        name="Integration Test Source",
        type="filesystem",
    )
    db.add(source)
    db.flush()

    container = Container(
        uuid=_CONTAINER_UUID,
        source_id=_SOURCE_UUID,
        external_id="integration-test-container",
        name="Integration Test Episodes",
    )
    db.add(container)
    db.flush()

    now = datetime.now(timezone.utc)
    for i in range(_NUM_EPISODES):
        asset = Asset(
            uuid=_asset_uuid(i),
            container_id=_CONTAINER_UUID,
            source_id=_SOURCE_UUID,
            canonical_key=f"test/integration/episode_{i:03d}.mp4",
            canonical_key_hash=f"integ_{i:03d}",
            uri=f"test://integration/episode_{i:03d}.mp4",
            size=500_000_000,
            state="ready",
            approved_for_broadcast=True,
            duration_ms=_EPISODE_DURATION_MS,
            discovered_at=now,
        )
        db.add(asset)

        editorial = AssetEditorial(
            asset_uuid=_asset_uuid(i),
            payload={
                "title": f"Test Episode {i + 1}",
                "type": "episode",
                "series_title": "Integration Test Show",
                "season_number": 1,
                "episode_number": i + 1,
            },
        )
        db.add(editorial)


def _purge(db: Session) -> None:
    """Delete all integration test seed data."""
    db.query(AssetEditorial).filter(
        AssetEditorial.asset_uuid.in_(
            db.query(Asset.uuid).filter(Asset.source_id == _SOURCE_UUID)
        )
    ).delete(synchronize_session=False)
    db.query(Asset).filter(Asset.source_id == _SOURCE_UUID).delete(
        synchronize_session=False
    )
    db.query(Container).filter(Container.source_id == _SOURCE_UUID).delete(
        synchronize_session=False
    )
    db.query(Source).filter(Source.id == _SOURCE_UUID).delete(
        synchronize_session=False
    )


@pytest.fixture(autouse=True, scope="session")
def _seed_integration_assets():
    """Seed test assets once per test session for integration tests.

    Creates Source, Container, and 100 episode assets with editorial
    metadata so that CatalogAssetResolver pool queries return results.

    Builds its own engine/session directly from TEST_DATABASE_URL to
    avoid dependency on the function-scoped _force_test_db monkeypatch.

    Idempotent — checks for ready assets from the integration source.
    If the source exists but assets are missing/wrong, purges and reseeds.
    """
    engine = get_engine(for_test=True)
    TestSession = sessionmaker(bind=engine)
    db: Session = TestSession()

    try:
        ready_count = (
            db.query(Asset)
            .filter(Asset.source_id == _SOURCE_UUID, Asset.state == "ready")
            .count()
        )
        if ready_count >= _NUM_EPISODES:
            return

        # Stale or missing data — purge and reseed
        _purge(db)
        db.flush()
        _seed(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
