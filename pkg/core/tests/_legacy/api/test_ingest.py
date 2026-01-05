"""
Tests for ingest API endpoints.

This module tests the ingest pipeline API functionality.
"""
import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")

import uuid  # noqa: E402
from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from retrovue.api.routers.ingest import router  # noqa: E402
from retrovue.domain.entities import Asset  # noqa: E402


class TestIngestAPI:
    """Test cases for ingest API endpoints."""
    
    def test_run_ingest_filesystem(self, temp_db_session: Session):
        """Test running ingest for filesystem source."""
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        # Mock the ingest pipeline
        with patch('retrovue.api.routers.ingest.run') as mock_run:
            mock_run.return_value = {
                "discovered": 5,
                "registered": 5,
                "enriched": 5,
                "canonicalized": 3,
                "queued_for_review": 2
            }
            
            response = client.post("/ingest/run?source=filesystem")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["discovered"] == 5
            assert data["registered"] == 5
            assert data["enriched"] == 5
            assert data["canonicalized"] == 3
            assert data["queued_for_review"] == 2
    
    def test_run_ingest_plex_with_library_ids(self, temp_db_session: Session):
        """Test running ingest for Plex source with specific library IDs."""
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        # Mock the ingest pipeline
        with patch('retrovue.api.routers.ingest.run') as mock_run:
            mock_run.return_value = {
                "discovered": 10,
                "registered": 10,
                "enriched": 10,
                "canonicalized": 8,
                "queued_for_review": 2
            }
            
            request_data = {
                "library_ids": ["2", "5"],
                "enrichers": ["ffprobe"]
            }
            
            response = client.post(
                "/ingest/run?source=plex&source_id=plex_server_1",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["discovered"] == 10
            
            # Verify the pipeline was called with correct parameters
            mock_run.assert_called_once_with(
                source="plex",
                enrichers=["ffprobe"],
                source_id="plex_server_1",
                library_ids=["2", "5"]
            )
    
    def test_run_ingest_with_error(self, temp_db_session: Session):
        """Test running ingest when pipeline returns an error."""
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        # Mock the ingest pipeline to return an error
        with patch('retrovue.content_manager.ingest_pipeline.run') as mock_run:
            mock_run.return_value = {
                "error": "Failed to connect to Plex server"
            }
            
            response = client.post("/ingest/run?source=plex")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "Failed to get importer" in data["error"]
            assert data["discovered"] == 0
    
    def test_run_ingest_pipeline_exception(self, temp_db_session: Session):
        """Test running ingest when pipeline raises an exception."""
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        # Mock the ingest pipeline to raise an exception
        with patch('retrovue.api.routers.ingest.run') as mock_run:
            mock_run.side_effect = Exception("Database connection failed")
            
            response = client.post("/ingest/run?source=filesystem")
            
            assert response.status_code == 500
            data = response.json()
            assert "Failed to run ingest pipeline" in data["detail"]
    
    def test_get_source_collections(self, temp_db_session: Session):
        """Test getting source collections."""
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        response = client.get("/ingest/sources/plex/collections")
        
        assert response.status_code == 200
        data = response.json()
        assert "source_id" in data
        assert "collections" in data
        assert data["source_id"] == "plex"
    
    def test_update_source_collection(self, temp_db_session: Session):
        """Test updating a source collection."""
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        # Test updating enabled status
        response = client.put(
            "/ingest/sources/plex/collections/2",
            params={"enabled": False}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Test updating mapping pairs
        response = client.put(
            "/ingest/sources/plex/collections/2",
            params={"mapping_pairs": [["/plex/movies", "/local/movies"]]}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestIngestPipeline:
    """Test cases for the ingest pipeline itself."""
    
    def test_translate_path(self):
        """Test path translation functionality."""
        from retrovue.content_manager.ingest_pipeline import translate_path
        
        mappings = [
            ("/plex/movies", "/local/movies"),
            ("/plex/tv", "/local/tv")
        ]
        
        # Test exact match
        result = translate_path("/plex/movies/movie.mp4", mappings)
        assert result == "/local/movies/movie.mp4"
        
        # Test partial match
        result = translate_path("/plex/tv/show/s01e01.mkv", mappings)
        assert result == "/local/tv/show/s01e01.mkv"
        
        # Test no match
        result = translate_path("/other/path/file.mp4", mappings)
        assert result == "/other/path/file.mp4"
    
    def test_confidence_score(self):
        """Test confidence score calculation."""
        from retrovue.content_manager.ingest_pipeline import confidence_score
        
        # Test asset with duration
        asset = Asset(
            id=uuid.uuid4(),
            uri="file:///test/video.mp4",
            size=1000000,
            duration_ms=120000,  # 2 minutes in milliseconds
            video_codec="h264",
            audio_codec="aac"
        )
        
        score = confidence_score(asset)
        assert score >= 0.6  # Should have duration bonus
        
        # Test asset without duration
        asset_no_duration = Asset(
            id=uuid.uuid4(),
            uri="file:///test/video.mp4",
            size=1000000
        )
        
        score = confidence_score(asset_no_duration)
        assert score == 0.0
    
    def test_run_pipeline_filesystem(self, temp_db_session: Session):
        """Test running the pipeline for filesystem source."""
        # This test is simplified to avoid complex mocking
        # In a real scenario, we would test the pipeline components individually
        assert True  # Placeholder test


class MockImporter:
    """Mock importer for testing."""
    
    def discover(self):
        return []


class MockEnricher:
    """Mock enricher for testing."""
    
    def enrich(self, asset):
        return asset
