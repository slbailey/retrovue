"""
Tests for compliance reporting and cross-domain correlation.

These tests validate that the identity model supports compliance reporting
and as-run log generation through UUID-based correlation.
"""
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from retrovue.domain.entities import Asset  # noqa: E402
from retrovue.infra.db import Base  # noqa: E402
from retrovue.schedule_manager.models import (  # noqa: E402
    BroadcastChannel,
    BroadcastPlaylogEvent,
    CatalogAsset,
)


class TestComplianceReporting:
    """Test compliance reporting capabilities with current identity model."""
    
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
    
    def test_ingest_to_catalog_correlation(self, db_session):
        """Test correlation between ingest assets and catalog assets."""
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
        
        # Test correlation query
        correlation_query = text("""
            SELECT 
                a.id as source_id,
                a.uuid as source_uuid,
                ca.id as catalog_id,
                ca.title as catalog_title
            FROM assets a
            JOIN catalog_asset ca ON a.id = ca.source_ingest_asset_id
            WHERE a.id = :source_id
        """)
        
        result = db_session.execute(correlation_query, {"source_id": source_asset.id}).fetchone()
        
        assert result is not None
        assert result.source_id == source_asset.id
        assert result.catalog_id == catalog_asset.id
        assert result.source_uuid == source_asset.uuid
    
    def test_playout_to_source_correlation(self, db_session):
        """Test correlation from playout events back to source assets."""
        # Create entities for complete playout scenario
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
        start_time = datetime.now(UTC)
        end_time = datetime.now(UTC)
        
        playlog_event = BroadcastPlaylogEvent(
            channel_id=channel.id,
            asset_id=catalog_asset.id,
            start_utc=start_time,
            end_utc=end_time,
            broadcast_day="2024-01-01"
        )
        db_session.add(playlog_event)
        db_session.commit()
        
        # Test compliance reporting query
        compliance_query = text("""
            SELECT 
                p.id as playlog_id,
                p.start_utc,
                p.end_utc,
                p.broadcast_day,
                c.name as channel_name,
                ca.title as catalog_title,
                a.uuid as source_uuid,
                a.uri as source_uri
            FROM broadcast_playlog_event p
            JOIN broadcast_channel c ON p.channel_id = c.id
            JOIN catalog_asset ca ON p.asset_id = ca.id
            JOIN assets a ON ca.source_ingest_asset_id = a.id
            WHERE p.id = :playlog_id
        """)
        
        result = db_session.execute(compliance_query, {"playlog_id": playlog_event.id}).fetchone()
        
        assert result is not None
        assert result.playlog_id == playlog_event.id
        assert result.channel_name == channel.name
        assert result.catalog_title == catalog_asset.title
        assert result.source_uuid == source_asset.uuid
        assert result.source_uri == source_asset.uri
    
    def test_broadcast_day_compliance_report(self, db_session):
        """Test generating a compliance report for a specific broadcast day."""
        # Create test data
        channel = BroadcastChannel(
            name="TestChannel",
            timezone="America/New_York",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360
        )
        db_session.add(channel)
        
        # Create multiple assets and playlog events
        assets_data = [
            ("source1.mp4", "Asset 1", 30000),
            ("source2.mp4", "Asset 2", 60000),
            ("source3.mp4", "Asset 3", 45000)
        ]
        
        for uri, title, duration in assets_data:
            source_asset = Asset(
                uri=f"file:///test/{uri}",
                size=1024000,
                duration_ms=duration,
                canonical=True
            )
            db_session.add(source_asset)
            
            catalog_asset = CatalogAsset(
                title=title,
                duration_ms=duration,
                file_path=f"/path/to/catalog/{uri}",
                canonical=True,
                source_ingest_asset_id=source_asset.id
            )
            db_session.add(catalog_asset)
        
        db_session.commit()
        
        # Create playlog events for the broadcast day
        base_time = datetime(2024, 1, 1, 6, 0, 0, tzinfo=UTC)
        catalog_assets = db_session.query(CatalogAsset).all()
        
        for i, catalog_asset in enumerate(catalog_assets):
            start_time = base_time.replace(hour=6 + i)
            end_time = start_time.replace(minute=start_time.minute + (catalog_asset.duration_ms // 1000 // 60))
            
            playlog_event = BroadcastPlaylogEvent(
                channel_id=channel.id,
                asset_id=catalog_asset.id,
                start_utc=start_time,
                end_utc=end_time,
                broadcast_day="2024-01-01"
            )
            db_session.add(playlog_event)
        
        db_session.commit()
        
        # Generate compliance report for the broadcast day
        compliance_report_query = text("""
            SELECT 
                p.start_utc,
                p.end_utc,
                c.name as channel_name,
                ca.title as catalog_title,
                a.uuid as source_uuid,
                a.uri as source_uri,
                a.hash_sha256 as source_hash
            FROM broadcast_playlog_event p
            JOIN broadcast_channel c ON p.channel_id = c.id
            JOIN catalog_asset ca ON p.asset_id = ca.id
            JOIN assets a ON ca.source_ingest_asset_id = a.id
            WHERE p.broadcast_day = :broadcast_day
            ORDER BY p.start_utc
        """)
        
        results = db_session.execute(compliance_report_query, {"broadcast_day": "2024-01-01"}).fetchall()
        
        # Verify the compliance report
        assert len(results) == 3
        
        for _i, result in enumerate(results):
            assert result.channel_name == "TestChannel"
            assert result.source_uuid is not None
            assert result.source_uri is not None
    
    def test_cross_domain_lineage_tracking(self, db_session):
        """Test tracking content lineage across domains."""
        # Create a source asset
        source_asset = Asset(
            uri="file:///test/source.mp4",
            size=1024000,
            duration_ms=30000,
            canonical=True
        )
        db_session.add(source_asset)
        db_session.commit()
        
        # Create a catalog asset
        catalog_asset = CatalogAsset(
            title="Test Catalog Asset",
            duration_ms=30000,
            file_path="/path/to/catalog/asset.mp4",
            canonical=True,
            source_ingest_asset_id=source_asset.id
        )
        db_session.add(catalog_asset)
        db_session.commit()
        
        # Test lineage tracking query
        lineage_query = text("""
            SELECT 
                a.id as source_id,
                a.uuid as source_uuid,
                a.uri as source_uri,
                a.canonical as source_canonical,
                ca.id as catalog_id,
                ca.title as catalog_title,
                ca.canonical as catalog_canonical
            FROM assets a
            LEFT JOIN catalog_asset ca ON a.id = ca.source_ingest_asset_id
            WHERE a.id = :source_id
        """)
        
        result = db_session.execute(lineage_query, {"source_id": source_asset.id}).fetchone()
        
        assert result is not None
        assert result.source_id == source_asset.id
        assert result.source_uuid == source_asset.uuid
        assert result.catalog_id == catalog_asset.id
        assert result.catalog_title == catalog_asset.title
        
        # Verify lineage chain
        assert result.source_canonical
        assert result.catalog_canonical


class TestMissingUUIDCorrelation:
    """Test what happens when UUID columns are missing from broadcast models."""
    
    def test_cannot_correlate_broadcast_models_without_uuid(self):
        """Test that we cannot correlate broadcast models without UUID columns."""
        # This test documents the limitation of the current model
        # Without UUID columns in broadcast models, we cannot:
        # 1. Correlate broadcast events with external systems
        # 2. Track stable identity across environments
        # 3. Generate comprehensive compliance reports
        
        # Example of what we CANNOT do without UUID columns:
        # SELECT p.uuid, c.uuid, ca.uuid 
        # FROM broadcast_playlog_event p
        # JOIN broadcast_channel c ON p.channel_id = c.id
        # JOIN catalog_asset ca ON p.asset_id = ca.id
        # WHERE p.uuid = :external_system_id
        
        # This query would fail because broadcast models don't have UUID columns
        
        pass  # This is a documentation test
    
    def test_required_uuid_columns_for_compliance(self):
        """Test that UUID columns are required for full compliance reporting."""
        # For complete compliance reporting, we need UUID columns in:
        # 1. BroadcastChannel - for channel identity correlation
        # 2. CatalogAsset - for content identity correlation  
        # 3. BroadcastPlaylogEvent - for playout event correlation
        
        # Example compliance report with UUID columns:
        # SELECT 
        #     p.uuid as playlog_uuid,
        #     c.uuid as channel_uuid,
        #     ca.uuid as catalog_uuid,
        #     a.uuid as source_uuid
        # FROM broadcast_playlog_event p
        # JOIN broadcast_channel c ON p.channel_id = c.id
        # JOIN catalog_asset ca ON p.asset_id = ca.id
        # JOIN assets a ON ca.source_ingest_asset_id = a.id
        
        pass  # This is a documentation test
