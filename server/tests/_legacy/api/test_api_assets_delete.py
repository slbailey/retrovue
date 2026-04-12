"""
Tests for API asset delete and restore endpoints.

This module tests the REST API endpoints for asset deletion and restoration,
including proper HTTP status codes, error handling, and response formats.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from retrovue.domain.entities import Asset


class TestAPIAssetDelete:
    """Test API asset delete endpoints."""

    def test_delete_asset_soft_delete_success(self, client: TestClient, db_session):
        """Test successful soft delete via API."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        # Soft delete the asset
        response = client.delete(f"/api/v1/assets/{asset.uuid}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "soft_delete"
        assert data["uuid"] == str(asset.uuid)
        assert data["status"] == "ok"
        assert data["referenced"] is False

    def test_delete_asset_hard_delete_success(self, client: TestClient, db_session):
        """Test successful hard delete via API."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        # Hard delete the asset
        response = client.delete(f"/api/v1/assets/{asset.uuid}?hard=true")
        
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "hard_delete"
        assert data["uuid"] == str(asset.uuid)
        assert data["status"] == "ok"
        assert data["referenced"] is False

    def test_delete_asset_dry_run(self, client: TestClient, db_session):
        """Test dry run mode via API."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        # Dry run delete
        response = client.delete(f"/api/v1/assets/{asset.uuid}?dry_run=true")
        
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "soft_delete"
        assert data["uuid"] == str(asset.uuid)
        assert "status" not in data  # No status in dry run

    def test_delete_asset_hard_delete_with_references_conflict(self, client: TestClient, db_session):
        """Test hard delete with references returns 409 conflict."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        # Mock the reference check to return True
        with pytest.Mock() as mock_ref:
            mock_ref.return_value = True
            
            # Hard delete without force
            response = client.delete(f"/api/v1/assets/{asset.uuid}?hard=true")
            
            assert response.status_code == 409
            data = response.json()
            assert "referenced by episodes" in data["detail"]

    def test_delete_asset_hard_delete_with_force(self, client: TestClient, db_session):
        """Test hard delete with force succeeds."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        # Hard delete with force
        response = client.delete(f"/api/v1/assets/{asset.uuid}?hard=true&force=true")
        
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "hard_delete"
        assert data["status"] == "ok"

    def test_delete_asset_not_found(self, client: TestClient, db_session):
        """Test deleting a non-existent asset returns 404."""
        fake_uuid = uuid4()
        
        response = client.delete(f"/api/v1/assets/{fake_uuid}")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]

    def test_delete_asset_already_soft_deleted(self, client: TestClient, db_session):
        """Test deleting an already soft-deleted asset returns 409."""
        # Create test asset that is already soft deleted
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=True
        )
        db_session.add(asset)
        db_session.flush()
        
        # Try to soft delete again
        response = client.delete(f"/api/v1/assets/{asset.uuid}")
        
        assert response.status_code == 409
        data = response.json()
        assert "already soft-deleted" in data["detail"]


class TestAPIAssetRestore:
    """Test API asset restore endpoints."""

    def test_restore_asset_success(self, client: TestClient, db_session):
        """Test successful asset restore via API."""
        # Create test asset that is soft deleted
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=True
        )
        db_session.add(asset)
        db_session.flush()
        
        # Restore the asset
        response = client.post(f"/api/v1/assets/{asset.uuid}/restore")
        
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "restore"
        assert data["uuid"] == str(asset.uuid)
        assert data["status"] == "ok"

    def test_restore_asset_not_found(self, client: TestClient, db_session):
        """Test restoring a non-existent asset returns 404."""
        fake_uuid = uuid4()
        
        response = client.post(f"/api/v1/assets/{fake_uuid}/restore")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]

    def test_restore_asset_not_deleted(self, client: TestClient, db_session):
        """Test restoring an asset that is not soft-deleted returns 409."""
        # Create test asset that is not deleted
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=False
        )
        db_session.add(asset)
        db_session.flush()
        
        # Try to restore
        response = client.post(f"/api/v1/assets/{asset.uuid}/restore")
        
        assert response.status_code == 409
        data = response.json()
        assert "not soft-deleted" in data["detail"]

    def test_restore_asset_invalid_uuid(self, client: TestClient, db_session):
        """Test restoring an asset with invalid UUID format."""
        response = client.post("/api/v1/assets/invalid-uuid/restore")
        
        assert response.status_code == 422  # Validation error
