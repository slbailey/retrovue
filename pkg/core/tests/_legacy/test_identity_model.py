"""
Tests for identity model validation across persisted entities.

These tests validate the dual-key approach: id (INTEGER PK) + uuid (stable external identity)
and ensure cross-domain lineage tracking works correctly.
"""
import uuid
from datetime import UTC

import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from retrovue.domain.entities import Asset  # noqa: E402
from retrovue.infra.db import Base  # noqa: E402
from retrovue.schedule_manager.models import (  # noqa: E402
    BroadcastChannel,
    BroadcastPlaylogEvent,
    BroadcastScheduleDay,
    BroadcastTemplate,
    BroadcastTemplateBlock,
    CatalogAsset,
)


class TestIdentityModel:
    """Test the dual-key identity model across all persisted entities."""
    
    @pytest.fixture
    def db_session(self):
        """Create a test database session."""
        engine = create_engine("postgresql://test:test@localhost:5432/retrovue_test")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
        Base.metadata.drop_all(engine)
    
    def test_asset_has_dual_keys(self, db_session):
        """Test that Asset entity has both id (INTEGER PK) and uuid (UUID unique)."""
        # Create an asset
        asset = Asset(
            uri="file:///test/video.mp4",
            size=1024000,
            duration_ms=30000,
            canonical=True
        )
        db_session.add(asset)
        db_session.commit()
        
        # Verify both keys exist
        assert asset.id is not None  # INTEGER primary key
        assert asset.uuid is not None  # UUID for external identity
        assert isinstance(asset.id, int)
        assert isinstance(asset.uuid, uuid.UUID)
        
        # Verify UUID is unique
        asset2 = Asset(
            uri="file:///test/video2.mp4",
            size=2048000,
            duration_ms=60000,
            canonical=True
        )
        db_session.add(asset2)
        db_session.commit()
        
        assert asset.uuid != asset2.uuid
    
    def test_broadcast_models_have_integer_pk(self, db_session):
        """Test that broadcast models have INTEGER primary keys."""
        # Test BroadcastChannel
        channel = BroadcastChannel(
            name="TestChannel",
            timezone="America/New_York",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360
        )
        db_session.add(channel)
        db_session.commit()
        
        assert channel.id is not None
        assert isinstance(channel.id, int)
        
        # Test CatalogAsset
        catalog_asset = CatalogAsset(
            title="Test Asset",
            duration_ms=30000,
            file_path="/path/to/asset.mp4",
            canonical=True
        )
        db_session.add(catalog_asset)
        db_session.commit()
        
        assert catalog_asset.id is not None
        assert isinstance(catalog_asset.id, int)
    
    def test_foreign_keys_use_integer_references(self, db_session):
        """Test that foreign key relationships use INTEGER references."""
        # Create a channel
        channel = BroadcastChannel(
            name="TestChannel",
            timezone="America/New_York",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360
        )
        db_session.add(channel)
        db_session.commit()
        
        # Create a template
        template = BroadcastTemplate(
            name="TestTemplate",
            description="Test template"
        )
        db_session.add(template)
        db_session.commit()
        
        # Create a schedule day (foreign key to channel and template)
        schedule_day = BroadcastScheduleDay(
            channel_id=channel.id,  # INTEGER reference
            template_id=template.id,  # INTEGER reference
            schedule_date="2024-01-01"
        )
        db_session.add(schedule_day)
        db_session.commit()
        
        # Verify the foreign key relationships work
        assert schedule_day.channel_id == channel.id
        assert schedule_day.template_id == template.id
        assert schedule_day.channel.id == channel.id
        assert schedule_day.template.id == template.id
    
    def test_catalog_asset_source_reference(self, db_session):
        """Test that CatalogAsset can reference source ingest asset via INTEGER FK."""
        # Create a source asset
        source_asset = Asset(
            uri="file:///test/source.mp4",
            size=1024000,
            duration_ms=30000,
            canonical=True
        )
        db_session.add(source_asset)
        db_session.commit()
        
        # Create a catalog asset that references the source
        catalog_asset = CatalogAsset(
            title="Test Catalog Asset",
            duration_ms=30000,
            file_path="/path/to/catalog/asset.mp4",
            canonical=True,
            source_ingest_asset_id=source_asset.id  # INTEGER FK reference
        )
        db_session.add(catalog_asset)
        db_session.commit()
        
        # Verify the reference
        assert catalog_asset.source_ingest_asset_id == source_asset.id
    
    def test_playlog_event_relationships(self, db_session):
        """Test that BroadcastPlaylogEvent uses INTEGER foreign keys."""
        # Create required entities
        channel = BroadcastChannel(
            name="TestChannel",
            timezone="America/New_York",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360
        )
        db_session.add(channel)
        
        catalog_asset = CatalogAsset(
            title="Test Asset",
            duration_ms=30000,
            file_path="/path/to/asset.mp4",
            canonical=True
        )
        db_session.add(catalog_asset)
        db_session.commit()
        
        # Create a playlog event
        from datetime import datetime
        playlog_event = BroadcastPlaylogEvent(
            channel_id=channel.id,  # INTEGER FK
            asset_id=catalog_asset.id,  # INTEGER FK
            start_utc=datetime.now(UTC),
            end_utc=datetime.now(UTC),
            broadcast_day="2024-01-01"
        )
        db_session.add(playlog_event)
        db_session.commit()
        
        # Verify relationships
        assert playlog_event.channel_id == channel.id
        assert playlog_event.asset_id == catalog_asset.id
        assert playlog_event.channel.id == channel.id
        assert playlog_event.asset.id == catalog_asset.id


class TestCrossDomainLineage:
    """Test cross-domain lineage tracking using shared UUID values."""
    
    @pytest.fixture
    def db_session(self):
        """Create a test database session."""
        engine = create_engine("postgresql://test:test@localhost:5432/retrovue_test")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
        Base.metadata.drop_all(engine)
    
    def test_asset_uuid_stability(self, db_session):
        """Test that Asset UUID remains stable across operations."""
        # Create an asset
        asset = Asset(
            uri="file:///test/video.mp4",
            size=1024000,
            duration_ms=30000,
            canonical=True
        )
        db_session.add(asset)
        db_session.commit()
        
        original_uuid = asset.uuid
        
        # Update the asset
        asset.canonical = False
        db_session.commit()
        
        # UUID should remain the same
        assert asset.uuid == original_uuid
        
        # Refresh from database
        db_session.refresh(asset)
        assert asset.uuid == original_uuid
    
    def test_cross_domain_correlation(self, db_session):
        """Test that we can correlate assets across domains using UUID."""
        # Create a source asset in Library Domain
        source_asset = Asset(
            uri="file:///test/source.mp4",
            size=1024000,
            duration_ms=30000,
            canonical=True
        )
        db_session.add(source_asset)
        db_session.commit()
        
        # Create a catalog asset that references the source
        catalog_asset = CatalogAsset(
            title="Test Catalog Asset",
            duration_ms=30000,
            file_path="/path/to/catalog/asset.mp4",
            canonical=True,
            source_ingest_asset_id=source_asset.id
        )
        db_session.add(catalog_asset)
        db_session.commit()
        
        # Verify we can correlate using the source_ingest_asset_id
        assert catalog_asset.source_ingest_asset_id == source_asset.id
        
        # Verify we can find the source asset
        found_source = db_session.query(Asset).filter(
            Asset.id == catalog_asset.source_ingest_asset_id
        ).first()
        
        assert found_source is not None
        assert found_source.id == source_asset.id
        assert found_source.uuid == source_asset.uuid
    
    def test_compliance_reporting_correlation(self, db_session):
        """Test that we can correlate content for compliance reporting."""
        # Create entities for a complete playout scenario
        channel = BroadcastChannel(
            name="TestChannel",
            timezone="America/New_York",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360
        )
        db_session.add(channel)
        
        source_asset = Asset(
            uri="file:///test/source.mp4",
            size=1024000,
            duration_ms=30000,
            canonical=True
        )
        db_session.add(source_asset)
        
        catalog_asset = CatalogAsset(
            title="Test Catalog Asset",
            duration_ms=30000,
            file_path="/path/to/catalog/asset.mp4",
            canonical=True,
            source_ingest_asset_id=source_asset.id
        )
        db_session.add(catalog_asset)
        db_session.commit()
        
        # Create a playlog event
        from datetime import datetime
        playlog_event = BroadcastPlaylogEvent(
            channel_id=channel.id,
            asset_id=catalog_asset.id,
            start_utc=datetime.now(UTC),
            end_utc=datetime.now(UTC),
            broadcast_day="2024-01-01"
        )
        db_session.add(playlog_event)
        db_session.commit()
        
        # Test compliance reporting query
        # Find what was played and trace back to source
        played_asset = db_session.query(CatalogAsset).filter(
            CatalogAsset.id == playlog_event.asset_id
        ).first()
        
        source_asset_from_catalog = db_session.query(Asset).filter(
            Asset.id == played_asset.source_ingest_asset_id
        ).first()
        
        # Verify the correlation chain
        assert played_asset.id == catalog_asset.id
        assert source_asset_from_catalog.id == source_asset.id
        assert source_asset_from_catalog.uuid == source_asset.uuid


class TestIdentityModelCompliance:
    """Test that the identity model follows the documented rules."""
    
    def test_no_uuid_primary_keys_in_broadcast_domain(self):
        """Test that broadcast domain models do not use UUID primary keys."""
        # Check that all broadcast models use INTEGER primary keys
        broadcast_models = [
            BroadcastChannel,
            BroadcastTemplate,
            BroadcastTemplateBlock,
            BroadcastScheduleDay,
            CatalogAsset,
            BroadcastPlaylogEvent
        ]
        
        for model in broadcast_models:
            # Get the primary key column
            pk_columns = [col for col in model.__table__.columns if col.primary_key]
            assert len(pk_columns) == 1, f"{model.__name__} should have exactly one primary key"
            
            pk_column = pk_columns[0]
            assert pk_column.type.python_type is int, f"{model.__name__} primary key should be INTEGER, not {pk_column.type}"
    
    def test_asset_has_correct_dual_key_structure(self):
        """Test that Asset entity has the correct dual-key structure."""
        # Check that Asset has both id and uuid columns
        asset_columns = {col.name: col for col in Asset.__table__.columns}
        
        # Should have id column (INTEGER PK)
        assert 'id' in asset_columns
        assert asset_columns['id'].primary_key
        assert asset_columns['id'].type.python_type is int
        
        # Should have uuid column (UUID, unique)
        assert 'uuid' in asset_columns
        assert not asset_columns['uuid'].primary_key
        assert asset_columns['uuid'].unique
        # Note: UUID type checking would require more complex inspection
    
    def test_foreign_key_consistency(self):
        """Test that all foreign keys reference INTEGER columns."""
        # Check BroadcastScheduleDay foreign keys
        schedule_day_columns = {col.name: col for col in BroadcastScheduleDay.__table__.columns}
        
        # channel_id should be INTEGER FK
        assert 'channel_id' in schedule_day_columns
        assert schedule_day_columns['channel_id'].type.python_type is int
        
        # template_id should be INTEGER FK
        assert 'template_id' in schedule_day_columns
        assert schedule_day_columns['template_id'].type.python_type is int
        
        # Check BroadcastPlaylogEvent foreign keys
        playlog_columns = {col.name: col for col in BroadcastPlaylogEvent.__table__.columns}
        
        # channel_id should be INTEGER FK
        assert 'channel_id' in playlog_columns
        assert playlog_columns['channel_id'].type.python_type is int
        
        # asset_id should be INTEGER FK
        assert 'asset_id' in playlog_columns
        assert playlog_columns['asset_id'].type.python_type is int
