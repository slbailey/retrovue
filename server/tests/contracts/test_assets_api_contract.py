"""Contract tests for domain-named asset/tag REST API (RETA-209).

Verifies that the new /api/assets and /api/tags endpoints return correct
response shapes and enforce domain rules. These replace the deprecated
/api/console/* namespace.

Invariant: INV-API-NO-BUSINESS-LOGIC-001

Covers:
  - GET  /api/assets — list assets with tags
  - PATCH /api/assets/{id} — update asset metadata
  - POST /api/assets/{id}/tags — add tags to asset
  - DELETE /api/assets/{id}/tags/{tag} — remove tag from asset
  - GET  /api/tags — list all distinct tags
  - 404 for unknown asset UUIDs
  - Tags are normalized (INV-ASSET-TAG-PERSISTENCE-001)
"""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from retrovue.domain.entities import Asset, AssetTag, Container, Source
from retrovue.infra import db as db_module
from retrovue.runtime.clock import SystemClock
from retrovue.web.api.assets import router, get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Get a test DB session via the conftest-patched SessionLocal."""
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db):
    """FastAPI TestClient with assets router mounted."""
    app = FastAPI()
    app.state.clock = SystemClock()
    app.include_router(router)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@pytest.fixture()
def sample_asset(db):
    """Create a source, container, and asset for testing."""
    source = Source(
        id=uuid_mod.uuid4(),
        name="test-assets-source",
        external_id=f"ext-{uuid_mod.uuid4().hex[:8]}",
        type="filesystem",
    )
    db.add(source)
    db.flush()

    container = Container(
        uuid=uuid_mod.uuid4(),
        source_id=source.id,
        name="test-assets-container",
        external_id=f"ext-{uuid_mod.uuid4().hex[:8]}",
    )
    db.add(container)
    db.flush()

    asset = Asset(
        uuid=uuid_mod.uuid4(),
        container_id=container.uuid,
        source_id=source.id,
        canonical_key="test/assets/asset.mp4",
        canonical_key_hash="abc123assets",
        uri="/media/test/assets/asset.mp4",
        size=1024000,
        state="ready",
        approved_for_broadcast=True,
        duration_ms=60000,
        discovered_at=datetime.now(timezone.utc),
    )
    db.add(asset)
    db.flush()
    return asset


# ---------------------------------------------------------------------------
# GET /api/assets
# ---------------------------------------------------------------------------

class TestListAssets:
    """GET /api/assets"""

    def test_returns_list_shape(self, client, sample_asset):
        """Response contains assets array and count."""
        resp = client.get("/api/assets")
        assert resp.status_code == 200
        body = resp.json()
        assert "assets" in body
        assert "count" in body
        assert isinstance(body["assets"], list)
        assert body["count"] >= 1

    def test_asset_includes_tags(self, client, sample_asset, db):
        """Each asset in the list includes its tags array."""
        tag = AssetTag(
            asset_uuid=sample_asset.uuid, tag="tag.retro", source="operator"
        )
        db.add(tag)
        db.flush()

        resp = client.get("/api/assets")
        assert resp.status_code == 200
        assets = resp.json()["assets"]
        match = [a for a in assets if a["uuid"] == str(sample_asset.uuid)]
        assert len(match) == 1
        assert "tags" in match[0]
        assert "tag.retro" in match[0]["tags"]

    def test_pagination_returns_total_and_page_fields(self, client, sample_asset):
        """Paginated response includes total, page, page_size fields."""
        resp = client.get("/api/assets?page=1&page_size=50")
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert body["page"] == 1
        assert body["page_size"] == 50
        assert body["total"] >= 1


# ---------------------------------------------------------------------------
# PATCH /api/assets/{id}
# ---------------------------------------------------------------------------

class TestPatchAsset:
    """PATCH /api/assets/{id}"""

    def test_unknown_asset_returns_404(self, client):
        """Non-existent UUID returns 404."""
        fake_id = str(uuid_mod.uuid4())
        resp = client.patch(
            f"/api/assets/{fake_id}",
            json={"approved_for_broadcast": True},
        )
        assert resp.status_code == 404

    def test_update_approval_status(self, client, sample_asset):
        """PATCH approved_for_broadcast updates the asset."""
        resp = client.patch(
            f"/api/assets/{sample_asset.uuid}",
            json={"approved_for_broadcast": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["approved_for_broadcast"] is False


# ---------------------------------------------------------------------------
# POST /api/assets/{id}/tags
# ---------------------------------------------------------------------------

class TestAddTags:
    """POST /api/assets/{id}/tags"""

    def test_unknown_asset_returns_404(self, client):
        """Non-existent UUID returns 404."""
        fake_id = str(uuid_mod.uuid4())
        resp = client.post(
            f"/api/assets/{fake_id}/tags",
            json={"tags": ["test"]},
        )
        assert resp.status_code == 404

    def test_add_tags_returns_updated_list(self, client, sample_asset):
        """Adding tags returns the full tag list for the asset."""
        resp = client.post(
            f"/api/assets/{sample_asset.uuid}/tags",
            json={"tags": ["classic", "80s"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "tags" in body
        assert set(body["tags"]) >= {"tag.classic", "tag.80s"}

    def test_tags_are_normalized(self, client, sample_asset):
        """INV-ASSET-TAG-PERSISTENCE-001: tags are lowercased and trimmed."""
        resp = client.post(
            f"/api/assets/{sample_asset.uuid}/tags",
            json={"tags": ["  Retro  TV  ", "CLASSIC"]},
        )
        assert resp.status_code == 200
        tags = resp.json()["tags"]
        assert "tag.retro tv" in tags
        assert "tag.classic" in tags
        assert "  Retro  TV  " not in tags
        assert "CLASSIC" not in tags


# ---------------------------------------------------------------------------
# DELETE /api/assets/{id}/tags/{tag}
# ---------------------------------------------------------------------------

class TestRemoveTag:
    """DELETE /api/assets/{id}/tags/{tag}"""

    def test_unknown_asset_returns_404(self, client):
        """Non-existent UUID returns 404."""
        fake_id = str(uuid_mod.uuid4())
        resp = client.delete(f"/api/assets/{fake_id}/tags/tag.retro")
        assert resp.status_code == 404

    def test_remove_existing_tag(self, client, sample_asset, db):
        """Removing an existing tag deletes it and returns updated list."""
        db.add(AssetTag(
            asset_uuid=sample_asset.uuid, tag="tag.retro", source="operator"
        ))
        db.add(AssetTag(
            asset_uuid=sample_asset.uuid, tag="tag.classic", source="operator"
        ))
        db.flush()

        resp = client.delete(
            f"/api/assets/{sample_asset.uuid}/tags/tag.retro"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "tag.retro" not in body["tags"]
        assert "tag.classic" in body["tags"]

    def test_remove_nonexistent_tag_is_noop(self, client, sample_asset):
        """Removing a tag that doesn't exist returns 200 (idempotent)."""
        resp = client.delete(
            f"/api/assets/{sample_asset.uuid}/tags/tag.nonexistent"
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/tags
# ---------------------------------------------------------------------------

class TestListTags:
    """GET /api/tags"""

    def test_returns_list_shape(self, client):
        """Response contains tags array."""
        resp = client.get("/api/tags")
        assert resp.status_code == 200
        body = resp.json()
        assert "tags" in body
        assert isinstance(body["tags"], list)

    def test_returns_distinct_tags(self, client, sample_asset, db):
        """Tags list contains distinct values from asset_tags table."""
        for tag_name in ["tag.retro", "tag.classic", "tag.80s"]:
            db.add(AssetTag(
                asset_uuid=sample_asset.uuid, tag=tag_name, source="operator"
            ))
        db.flush()

        resp = client.get("/api/tags")
        tags = resp.json()["tags"]
        assert "tag.retro" in tags
        assert "tag.classic" in tags
        assert "tag.80s" in tags
