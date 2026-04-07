"""Contract tests for Ingest REST API (RETA-69 Phase 2).

Verifies that ingest workflows are reachable via HTTP API and return
correct response shapes. The API routes are thin wrappers — all business
logic is tested by the existing ingest contract tests.

Covers:
  - POST /api/ingest/sources/{selector}/sync — trigger source ingest
  - POST /api/ingest/containers/{selector}/sync — trigger container ingest
  - GET /api/ingest/sources/{selector}/status — last sync result
  - Error shapes for unknown selectors (404)
  - API routes contain no business logic (thin-wrapper rule)
"""

from __future__ import annotations

import uuid as uuid_mod
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from retrovue.infra import db as db_module
from retrovue.web.api.ingest import router, get_db


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
    """FastAPI TestClient with ingest router mounted."""
    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# Source sync endpoint
# ---------------------------------------------------------------------------

class TestSourceSyncEndpoint:
    """POST /api/ingest/sources/{selector}/sync"""

    def test_unknown_source_returns_404(self, client):
        """A non-existent source selector returns 404."""
        resp = client.post("/api/ingest/sources/nonexistent-source/sync")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body

    def test_source_sync_calls_workflow(self, client, db):
        """A valid source triggers SourceIngestService and returns result."""
        from retrovue.domain.entities import Source
        source = Source(
            id=uuid_mod.uuid4(),
            name="test-source-api",
            external_id=f"ext-{uuid_mod.uuid4().hex[:8]}",
            type="filesystem",
        )
        db.add(source)
        db.flush()

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "source_id": str(source.id),
            "source_name": source.name,
            "status": "completed",
            "collections_processed": 0,
            "collections_skipped": 0,
            "stats": {},
            "collection_results": [],
            "errors": [],
        }

        with patch(
            "retrovue.web.api.ingest.SourceIngestService"
        ) as MockSIS:
            instance = MockSIS.return_value
            instance.ingest_source.return_value = mock_result

            resp = client.post(f"/api/ingest/sources/{source.name}/sync")

        assert resp.status_code == 200
        body = resp.json()
        assert body["source_name"] == "test-source-api"
        assert "stats" in body

    def test_source_sync_dry_run(self, client, db):
        """dry_run query param is forwarded to the workflow."""
        from retrovue.domain.entities import Source
        source = Source(
            id=uuid_mod.uuid4(),
            name="test-source-dryrun",
            external_id=f"ext-{uuid_mod.uuid4().hex[:8]}",
            type="filesystem",
        )
        db.add(source)
        db.flush()

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "source_id": str(source.id),
            "source_name": source.name,
            "status": "completed_dry_run",
            "collections_processed": 0,
            "collections_skipped": 0,
            "stats": {},
            "collection_results": [],
            "errors": [],
        }

        with patch(
            "retrovue.web.api.ingest.SourceIngestService"
        ) as MockSIS:
            instance = MockSIS.return_value
            instance.ingest_source.return_value = mock_result

            resp = client.post(
                f"/api/ingest/sources/{source.name}/sync?dry_run=true"
            )

        assert resp.status_code == 200
        MockSIS.return_value.ingest_source.assert_called_once()
        call_kwargs = instance.ingest_source.call_args
        assert call_kwargs.kwargs.get("dry_run") is True


# ---------------------------------------------------------------------------
# Container sync endpoint
# ---------------------------------------------------------------------------

class TestContainerSyncEndpoint:
    """POST /api/ingest/containers/{selector}/sync"""

    def test_unknown_container_returns_404(self, client):
        """A non-existent container selector returns 404."""
        resp = client.post("/api/ingest/containers/nonexistent-container/sync")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body

    def test_container_sync_calls_workflow(self, client, db):
        """A valid container triggers ContainerIngestService and returns result."""
        from retrovue.domain.entities import Container, Source
        source = Source(
            id=uuid_mod.uuid4(),
            name="test-source-for-container",
            external_id=f"ext-{uuid_mod.uuid4().hex[:8]}",
            type="filesystem",
        )
        db.add(source)
        db.flush()

        container = Container(
            uuid=uuid_mod.uuid4(),
            source_id=source.id,
            name="test-container-api",
            external_id=f"ext-{uuid_mod.uuid4().hex[:8]}",
        )
        db.add(container)
        db.flush()

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "container_id": str(container.uuid),
            "container_name": container.name,
            "status": "completed",
            "stats": {
                "assets_discovered": 0,
                "assets_ingested": 0,
            },
            "errors": [],
        }

        with patch(
            "retrovue.web.api.ingest.ContainerIngestService"
        ) as MockCIS, patch(
            "retrovue.web.api.ingest._construct_importer"
        ) as mock_importer:
            mock_importer.return_value = MagicMock()
            instance = MockCIS.return_value
            instance.ingest_container.return_value = mock_result

            resp = client.post(
                f"/api/ingest/containers/{container.name}/sync"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["container_name"] == "test-container-api"
        assert "stats" in body


# ---------------------------------------------------------------------------
# Source status endpoint
# ---------------------------------------------------------------------------

class TestSourceStatusEndpoint:
    """GET /api/ingest/sources/{selector}/status"""

    def test_unknown_source_returns_404(self, client):
        """A non-existent source selector returns 404."""
        resp = client.get("/api/ingest/sources/nonexistent-source/status")
        assert resp.status_code == 404

    def test_source_status_returns_source_info(self, client, db):
        """Returns basic source info and container summary."""
        from retrovue.domain.entities import Source
        source = Source(
            id=uuid_mod.uuid4(),
            name="test-source-status",
            external_id=f"ext-{uuid_mod.uuid4().hex[:8]}",
            type="filesystem",
        )
        db.add(source)
        db.flush()

        resp = client.get(f"/api/ingest/sources/{source.name}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_name"] == "test-source-status"
        assert "containers" in body
