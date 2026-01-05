"""
Tests for identity models to ensure ORM ↔ Alembic ↔ service contract coherence.

These tests validate that:
- Integer PK spine is real and auto-incrementing
- UUID fields exist and are unique
- Foreign keys reference integer PKs
- Delete cascades work correctly
- All models can be created and queried through the ORM
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from retrovue.domain.entities import Asset, Marker, ReviewQueue


class TestAssetIdentity:
    """Test Asset model identity and relationships."""
    
    def test_asset_creation_with_autoincrement_id(self, clean_db: Session, sample_asset_data):
        """Test that Asset gets an autoincrement integer id."""
        # Create an Asset
        asset = Asset(**sample_asset_data)
        clean_db.add(asset)
        clean_db.commit()
        
        # Assert it got an autoincrement integer id
        assert asset.id is not None
        assert isinstance(asset.id, int)
        assert asset.id > 0
        
        # Verify it's persisted
        retrieved = clean_db.execute(select(Asset).where(Asset.id == asset.id)).scalar_one()
        assert retrieved.id == asset.id
    
    def test_asset_creation_with_uuid(self, clean_db: Session, sample_asset_data):
        """Test that Asset gets a non-null UUID."""
        # Create an Asset
        asset = Asset(**sample_asset_data)
        clean_db.add(asset)
        clean_db.commit()
        
        # Assert it got a non-null uuid
        assert asset.uuid is not None
        assert isinstance(asset.uuid, uuid.UUID)
        
        # Verify it's persisted
        retrieved = clean_db.execute(select(Asset).where(Asset.id == asset.id)).scalar_one()
        assert retrieved.uuid == asset.uuid
    
    def test_asset_uuid_uniqueness(self, clean_db: Session, sample_asset_data):
        """Test that Asset UUIDs are unique."""
        # Create first Asset
        asset1 = Asset(**sample_asset_data)
        clean_db.add(asset1)
        clean_db.commit()
        
        # Create second Asset with different URI
        asset2_data = sample_asset_data.copy()
        asset2_data["uri"] = "file:///test/path/sample2.mp4"
        asset2 = Asset(**asset2_data)
        clean_db.add(asset2)
        clean_db.commit()
        
        # Assert UUIDs are different
        assert asset1.uuid != asset2.uuid
        
        # Verify both are persisted with different UUIDs
        retrieved1 = clean_db.execute(select(Asset).where(Asset.id == asset1.id)).scalar_one()
        retrieved2 = clean_db.execute(select(Asset).where(Asset.id == asset2.id)).scalar_one()
        assert retrieved1.uuid != retrieved2.uuid
    
    def test_asset_uuid_is_real_uuid(self, clean_db: Session, sample_asset_data):
        """Test that Asset UUID is a real UUID format."""
        asset = Asset(**sample_asset_data)
        clean_db.add(asset)
        clean_db.commit()
        
        # Assert it's a valid UUID
        assert isinstance(asset.uuid, uuid.UUID)
        
        # Test that it can be converted to string and back
        uuid_str = str(asset.uuid)
        parsed_uuid = uuid.UUID(uuid_str)
        assert parsed_uuid == asset.uuid



class TestCascadeBehavior:
    """Test cascade behavior for delete operations."""
    
    def test_asset_cascade_deletes_markers_and_review_queue(self, clean_db: Session, sample_asset_data):
        """Test that deleting an Asset cascades to delete Markers and ReviewQueue rows."""
        # Create an Asset
        asset = Asset(**sample_asset_data)
        clean_db.add(asset)
        clean_db.commit()
        
        # Create a Marker attached to the Asset
        marker = Marker(
            asset_id=asset.id,
            kind="chapter",
            start_ms=0,
            end_ms=1000,
            payload={"name": "Chapter 1"}
        )
        clean_db.add(marker)
        
        # Create a ReviewQueue row attached to the Asset
        review_queue = ReviewQueue(
            asset_id=asset.id,
            reason="Quality check needed",
            confidence=0.8,
            status="pending"
        )
        clean_db.add(review_queue)
        clean_db.commit()
        
        # Verify they exist
        assert clean_db.execute(select(Marker).where(Marker.asset_id == asset.id)).scalar_one_or_none() is not None
        assert clean_db.execute(select(ReviewQueue).where(ReviewQueue.asset_id == asset.id)).scalar_one_or_none() is not None
        
        # Delete the Asset
        clean_db.delete(asset)
        clean_db.commit()
        
        # Assert the Marker and ReviewQueue rows are gone (CASCADE works)
        assert clean_db.execute(select(Marker).where(Marker.asset_id == asset.id)).scalar_one_or_none() is None
        assert clean_db.execute(select(ReviewQueue).where(ReviewQueue.asset_id == asset.id)).scalar_one_or_none() is None
    
    # Note: Title/Season/Episode cascade tests removed - these tables have been dropped
    # Series/episode data is stored in asset_editorial.payload instead

