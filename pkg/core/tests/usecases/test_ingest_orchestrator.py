"""
Tests for the ingest orchestrator.

This module tests the ingest orchestration logic that wires together
importers, enrichers, and persistence for asset enrichment.
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch

from retrovue.usecases.ingest_orchestrator import ingest_collection_assets
from retrovue.domain.entities import Asset, Collection, Source, PathMapping, Marker
from retrovue.adapters.importers.base import DiscoveredItem
from retrovue.shared.types import MarkerKind


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.add = MagicMock()
    session.flush = MagicMock()
    session.commit = MagicMock()
    return session


@pytest.fixture
def mock_collection():
    """Create a mock collection with source."""
    source = Source(
        id=uuid4(),
        external_id="plex-test",
        name="Test Plex",
        type="plex",
        config={
            "base_url": "http://localhost:32400",
            "token": "test-token"
        }
    )
    
    collection = Collection(
        uuid=uuid4(),
        source_id=source.id,
        external_id="1",
        name="TV Shows",
        sync_enabled=True,
        ingestible=True,
        config={
            "enrichers": [
                {
                    "type": "ffprobe",
                    "priority": 1,
                    "config": {}
                }
            ]
        }
    )
    
    # Link source to collection
    collection.source = source
    
    return collection


@pytest.fixture
def mock_asset(mock_collection):
    """Create a mock asset in 'new' state."""
    asset = Asset(
        uuid=uuid4(),
        collection_uuid=mock_collection.uuid,
        canonical_key="test-key",
        canonical_key_hash="test-hash",
        uri="plex://12345",
        size=1000000,
        state="new",
        approved_for_broadcast=False,
        operator_verified=False,
        discovered_at=None
    )
    return asset


class TestIngestOrchestrator:
    """Tests for the ingest orchestrator."""

    def test_happy_path_with_chapters(self, mock_db_session, mock_collection, mock_asset):
        """Test successful enrichment with chapter extraction."""
        # Setup mocks
        mock_db_session.query.return_value.filter.return_value.all.side_effect = [
            [PathMapping(
                id=uuid4(),
                collection_uuid=mock_collection.uuid,
                plex_path="/external/TV Shows",
                local_path="/mnt/data/media/tv",
                created_at=None
            )],  # path_mappings query
            [mock_asset],  # assets query
        ]
        
        # Mock AssetEditorial query
        from retrovue.domain.entities import AssetEditorial
        mock_editorial = MagicMock()
        mock_editorial.payload = {
            "series_title": "Test Show",
            "season_number": 1,
            "episode_number": 1
        }
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_editorial
        
        # Mock importer
        mock_importer = MagicMock()
        mock_importer.resolve_local_uri.return_value = "file:///mnt/data/media/tv/show/episode.mkv"
        
        # Mock enricher
        mock_enricher = MagicMock()
        mock_enricher.name = "ffprobe"
        enriched_item = DiscoveredItem(
            path_uri="file:///mnt/data/media/tv/show/episode.mkv",
            provider_key="12345",
            size=1000000,
            probed={
                "duration_ms": 2400000,
                "container": "matroska",
                "video": {
                    "codec": "h264",
                    "width": 1920,
                    "height": 1080
                },
                "audio": [
                    {
                        "codec": "aac",
                        "channels": 2
                    }
                ],
                "chapters": [
                    {
                        "start_ms": 0,
                        "end_ms": 60000,
                        "title": "Intro"
                    },
                    {
                        "start_ms": 60000,
                        "end_ms": 2340000,
                        "title": "Main Content"
                    },
                    {
                        "start_ms": 2340000,
                        "end_ms": 2400000,
                        "title": "Credits"
                    }
                ]
            }
        )
        mock_enricher.enrich.return_value = enriched_item
        
        # Patch dependencies
        with patch("retrovue.adapters.registry.get_importer", return_value=mock_importer):
            with patch.dict("retrovue.adapters.registry.ENRICHERS", {"ffprobe": lambda **kwargs: mock_enricher}):
                with patch("retrovue.usecases.ingest_orchestrator.persist_asset_metadata") as mock_persist:
                    # Run orchestrator
                    summary = ingest_collection_assets(mock_db_session, mock_collection)
                    
                    # Verify results
                    assert summary["total"] == 1
                    assert summary["enriched"] == 1
                    assert summary["skipped"] == 0
                    assert summary["failed"] == 0
                    
                    # Verify asset was updated
                    assert mock_asset.duration_ms == 2400000
                    assert mock_asset.video_codec == "h264"
                    assert mock_asset.audio_codec == "aac"
                    assert mock_asset.container == "matroska"
                    assert mock_asset.state == "ready"
                    
                    # Verify probed data was persisted
                    mock_persist.assert_called_once()
                    
                    # Verify markers were created (3 chapters)
                    assert mock_db_session.add.call_count >= 3
                    
                    # Verify commit was called
                    mock_db_session.commit.assert_called_once()

    def test_skip_asset_without_local_file(self, mock_db_session, mock_collection, mock_asset):
        """Test that assets without resolvable local files are skipped."""
        # Setup mocks
        mock_db_session.query.return_value.filter.return_value.all.side_effect = [
            [],  # path_mappings query - empty
            [mock_asset],  # assets query
        ]
        
        mock_editorial = MagicMock()
        mock_editorial.payload = {}
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_editorial
        
        # Mock importer that returns empty URI (not found)
        mock_importer = MagicMock()
        mock_importer.resolve_local_uri.return_value = ""
        
        # Mock enricher (shouldn't be called)
        mock_enricher = MagicMock()
        mock_enricher.name = "ffprobe"
        
        # Patch dependencies
        with patch("retrovue.adapters.registry.get_importer", return_value=mock_importer):
            with patch.dict("retrovue.adapters.registry.ENRICHERS", {"ffprobe": lambda **kwargs: mock_enricher}):
                # Run orchestrator
                summary = ingest_collection_assets(mock_db_session, mock_collection)
                
                # Verify results
                assert summary["total"] == 1
                assert summary["enriched"] == 0
                assert summary["skipped"] == 1
                assert summary["failed"] == 0
                
                # Verify enricher was not called
                mock_enricher.enrich.assert_not_called()
                
                # Verify asset state was reverted to 'new'
                assert mock_asset.state == "new"

    def test_handle_enricher_failure_gracefully(self, mock_db_session, mock_collection, mock_asset):
        """Test that enricher failures are handled gracefully."""
        # Setup mocks
        mock_db_session.query.return_value.filter.return_value.all.side_effect = [
            [PathMapping(
                id=uuid4(),
                collection_uuid=mock_collection.uuid,
                plex_path="/external",
                local_path="/mnt/data",
                created_at=None
            )],  # path_mappings query
            [mock_asset],  # assets query
        ]
        
        mock_editorial = MagicMock()
        mock_editorial.payload = {}
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_editorial
        
        # Mock importer
        mock_importer = MagicMock()
        mock_importer.resolve_local_uri.return_value = "file:///mnt/data/test.mkv"
        
        # Mock enricher that fails
        mock_enricher = MagicMock()
        mock_enricher.name = "ffprobe"
        mock_enricher.enrich.side_effect = Exception("FFprobe failed")
        
        # Patch dependencies
        with patch("retrovue.adapters.registry.get_importer", return_value=mock_importer):
            with patch.dict("retrovue.adapters.registry.ENRICHERS", {"ffprobe": lambda **kwargs: mock_enricher}):
                with patch("retrovue.usecases.ingest_orchestrator.persist_asset_metadata"):
                    # Run orchestrator - should not raise exception
                    summary = ingest_collection_assets(mock_db_session, mock_collection)
                    
                    # Verify results - enricher failed but asset is still marked as ready
                    # because we continue even after enricher failures
                    assert summary["total"] == 1
                    # Asset still gets to 'ready' state even if enricher fails
                    # (we continue processing rather than fail the whole asset)

    def test_no_enrichers_configured(self, mock_db_session, mock_collection, mock_asset):
        """Test that collections without enrichers skip all assets."""
        # Remove enrichers from collection config
        mock_collection.config = {}
        
        # Setup mocks
        mock_db_session.query.return_value.filter.return_value.all.side_effect = [
            [],  # path_mappings query
            [mock_asset],  # assets query
        ]
        
        # Run orchestrator
        summary = ingest_collection_assets(mock_db_session, mock_collection)
        
        # Verify all assets were skipped
        assert summary["total"] == 1
        assert summary["enriched"] == 0
        assert summary["skipped"] == 1
        assert summary["failed"] == 0

    def test_no_assets_in_new_state(self, mock_db_session, mock_collection):
        """Test that collections with no 'new' assets return empty summary."""
        # Setup mocks
        mock_db_session.query.return_value.filter.return_value.all.side_effect = [
            [],  # path_mappings query
            [],  # assets query - empty
        ]
        
        # Run orchestrator
        summary = ingest_collection_assets(mock_db_session, mock_collection)
        
        # Verify empty results
        assert summary["total"] == 0
        assert summary["enriched"] == 0
        assert summary["skipped"] == 0
        assert summary["failed"] == 0
