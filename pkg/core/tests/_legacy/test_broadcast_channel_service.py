"""
Unit tests for BroadcastChannelService.

Tests the service layer business logic, validation, and database operations
for BroadcastChannel CRUD operations.
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from retrovue.schedule_manager.broadcast_channel_service import (  # noqa: E402
    BroadcastChannelService,  # noqa: E402
)
from retrovue.schedule_manager.models import BroadcastChannel  # noqa: E402


class TestBroadcastChannelService:
    """Test cases for BroadcastChannelService."""
    
    def test_list_channels_empty(self, db_session: Session):
        """Test listing channels when none exist."""
        # Clear existing data first
        db_session.execute(text("DELETE FROM broadcast_channel"))
        db_session.commit()
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            result = BroadcastChannelService.list_channels()
            
            assert result == []
    
    def test_list_channels_with_data(self, db_session: Session):
        """Test listing channels with existing data."""
        # Create test channels
        channel1 = BroadcastChannel(
            name="RetroToons",
            timezone="America/New_York",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        channel2 = BroadcastChannel(
            name="ClassicMovies",
            timezone="America/Los_Angeles",
            grid_size_minutes=60,
            grid_offset_minutes=15,
            rollover_minutes=420,
            is_active=False
        )
        
        db_session.add(channel1)
        db_session.add(channel2)
        db_session.commit()
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            result = BroadcastChannelService.list_channels()
            
            assert len(result) == 2
            assert all("id" in channel for channel in result)
            assert all("name" in channel for channel in result)
            assert all("timezone" in channel for channel in result)
            assert all("is_active" in channel for channel in result)
            assert all("created_at" in channel for channel in result)
    
    def test_get_channel_exists(self, db_session: Session):
        """Test getting an existing channel."""
        channel = BroadcastChannel(
            name="TestChannel",
            timezone="UTC",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        db_session.add(channel)
        db_session.commit()
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            result = BroadcastChannelService.get_channel(channel.id)
            
            assert result is not None
            assert result["id"] == channel.id
            assert result["name"] == "TestChannel"
            assert result["timezone"] == "UTC"
            assert result["is_active"] is True
    
    def test_get_channel_not_exists(self, db_session: Session):
        """Test getting a non-existent channel."""
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            result = BroadcastChannelService.get_channel(999)
            
            assert result is None
    
    def test_create_channel_success(self, db_session: Session):
        """Test creating a valid channel."""
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            result = BroadcastChannelService.create_channel(
                name="NewChannel",
                timezone="America/Chicago",
                grid_size_minutes=45,
                grid_offset_minutes=10,
                rollover_minutes=300,
                is_active=True
            )
            
            assert result["name"] == "NewChannel"
            assert result["timezone"] == "America/Chicago"
            assert result["grid_size_minutes"] == 45
            assert result["grid_offset_minutes"] == 10
            assert result["rollover_minutes"] == 300
            assert result["is_active"] is True
            assert "id" in result
            assert "created_at" in result
    
    def test_create_channel_validation_errors(self, db_session: Session):
        """Test channel creation with various validation errors."""
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            # Test empty name
            with pytest.raises(ValueError, match="Channel name is required"):
                BroadcastChannelService.create_channel(
                    name="",
                    timezone="UTC",
                    grid_size_minutes=30,
                    grid_offset_minutes=0,
                    rollover_minutes=360
                )
            
            # Test empty timezone
            with pytest.raises(ValueError, match="Timezone is required"):
                BroadcastChannelService.create_channel(
                    name="TestChannel",
                    timezone="",
                    grid_size_minutes=30,
                    grid_offset_minutes=0,
                    rollover_minutes=360
                )
            
            # Test negative grid_size_minutes
            with pytest.raises(ValueError, match="grid_size_minutes must be non-negative"):
                BroadcastChannelService.create_channel(
                    name="TestChannel",
                    timezone="UTC",
                    grid_size_minutes=-1,
                    grid_offset_minutes=0,
                    rollover_minutes=360
                )
            
            # Test negative grid_offset_minutes
            with pytest.raises(ValueError, match="grid_offset_minutes must be non-negative"):
                BroadcastChannelService.create_channel(
                    name="TestChannel",
                    timezone="UTC",
                    grid_size_minutes=30,
                    grid_offset_minutes=-1,
                    rollover_minutes=360
                )
            
            # Test negative rollover_minutes
            with pytest.raises(ValueError, match="rollover_minutes must be non-negative"):
                BroadcastChannelService.create_channel(
                    name="TestChannel",
                    timezone="UTC",
                    grid_size_minutes=30,
                    grid_offset_minutes=0,
                    rollover_minutes=-1
                )
            
            # Test invalid is_active type
            with pytest.raises(ValueError, match="is_active must be a boolean"):
                BroadcastChannelService.create_channel(
                    name="TestChannel",
                    timezone="UTC",
                    grid_size_minutes=30,
                    grid_offset_minutes=0,
                    rollover_minutes=360,
                    is_active="true"  # Should be boolean
                )
    
    def test_create_channel_duplicate_name(self, db_session: Session):
        """Test creating a channel with a duplicate name."""
        # Create existing channel
        existing_channel = BroadcastChannel(
            name="ExistingChannel",
            timezone="UTC",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        db_session.add(existing_channel)
        db_session.commit()
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            # Mock IntegrityError for duplicate name
            with patch.object(db_session, 'commit', side_effect=IntegrityError("", "", "")):
                with pytest.raises(ValueError, match="Channel with name 'ExistingChannel' already exists"):
                    BroadcastChannelService.create_channel(
                        name="ExistingChannel",
                        timezone="UTC",
                        grid_size_minutes=30,
                        grid_offset_minutes=0,
                        rollover_minutes=360
                    )
    
    def test_update_channel_success(self, db_session: Session):
        """Test updating a channel successfully."""
        # Create test channel
        channel = BroadcastChannel(
            name="OriginalName",
            timezone="UTC",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        db_session.add(channel)
        db_session.commit()
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            result = BroadcastChannelService.update_channel(
                channel.id,
                name="UpdatedName",
                timezone="America/New_York",
                is_active=False
            )
            
            assert result["name"] == "UpdatedName"
            assert result["timezone"] == "America/New_York"
            assert result["is_active"] is False
            # Other fields should remain unchanged
            assert result["grid_size_minutes"] == 30
            assert result["grid_offset_minutes"] == 0
            assert result["rollover_minutes"] == 360
    
    def test_update_channel_not_found(self, db_session: Session):
        """Test updating a non-existent channel."""
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            with pytest.raises(ValueError, match="Channel with ID 999 not found"):
                BroadcastChannelService.update_channel(999, name="NewName")
    
    def test_update_channel_validation_errors(self, db_session: Session):
        """Test update validation errors."""
        # Clear existing data first
        db_session.execute(text("DELETE FROM broadcast_channel"))
        db_session.commit()
        
        channel = BroadcastChannel(
            name="TestChannel",
            timezone="UTC",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        db_session.add(channel)
        db_session.commit()
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            # Test empty name
            with pytest.raises(ValueError, match="Channel name cannot be empty"):
                BroadcastChannelService.update_channel(channel.id, name="")
            
            # Test empty timezone
            with pytest.raises(ValueError, match="Timezone cannot be empty"):
                BroadcastChannelService.update_channel(channel.id, timezone="")
            
            # Test negative grid_size_minutes
            with pytest.raises(ValueError, match="grid_size_minutes must be non-negative"):
                BroadcastChannelService.update_channel(channel.id, grid_size_minutes=-1)
            
            # Test invalid is_active type
            with pytest.raises(ValueError, match="is_active must be a boolean"):
                BroadcastChannelService.update_channel(channel.id, is_active="true")
    
    def test_update_channel_duplicate_name(self, db_session: Session):
        """Test updating a channel to a duplicate name."""
        # Clear existing data first
        db_session.execute(text("DELETE FROM broadcast_channel"))
        db_session.commit()
        
        # Create two channels
        channel1 = BroadcastChannel(
            name="Channel1",
            timezone="UTC",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        channel2 = BroadcastChannel(
            name="Channel2",
            timezone="UTC",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        db_session.add(channel1)
        db_session.add(channel2)
        db_session.commit()
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            # Mock IntegrityError for duplicate name
            with patch.object(db_session, 'commit', side_effect=IntegrityError("", "", "")):
                with pytest.raises(ValueError, match="Channel with name 'Channel2' already exists"):
                    BroadcastChannelService.update_channel(channel2.id, name="Channel1")
    
    def test_delete_channel_success(self, db_session: Session):
        """Test deleting a channel successfully."""
        channel = BroadcastChannel(
            name="ToDelete",
            timezone="UTC",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        db_session.add(channel)
        db_session.commit()
        channel_id = channel.id
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            # Should not raise an exception
            BroadcastChannelService.delete_channel(channel_id)
            
            # Verify channel is deleted
            deleted_channel = db_session.get(BroadcastChannel, channel_id)
            assert deleted_channel is None
    
    def test_delete_channel_not_found(self, db_session: Session):
        """Test deleting a non-existent channel."""
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            with pytest.raises(ValueError, match="Channel with ID 999 not found"):
                BroadcastChannelService.delete_channel(999)
    
    def test_create_channel_name_whitespace_handling(self, db_session: Session):
        """Test that channel names are properly trimmed of whitespace."""
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            result = BroadcastChannelService.create_channel(
                name="  TrimmedName  ",
                timezone="  UTC  ",
                grid_size_minutes=30,
                grid_offset_minutes=0,
                rollover_minutes=360
            )
            
            assert result["name"] == "TrimmedName"
            assert result["timezone"] == "UTC"
    
    def test_update_channel_partial_fields(self, db_session: Session):
        """Test updating only specific fields leaves others unchanged."""
        channel = BroadcastChannel(
            name="OriginalName",
            timezone="UTC",
            grid_size_minutes=30,
            grid_offset_minutes=0,
            rollover_minutes=360,
            is_active=True
        )
        db_session.add(channel)
        db_session.commit()
        
        with patch('retrovue.schedule_manager.broadcast_channel_service.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            mock_session.return_value.__exit__.return_value = None
            
            # Update only name
            result = BroadcastChannelService.update_channel(channel.id, name="NewName")
            
            assert result["name"] == "NewName"
            assert result["timezone"] == "UTC"  # Unchanged
            assert result["grid_size_minutes"] == 30  # Unchanged
            assert result["grid_offset_minutes"] == 0  # Unchanged
            assert result["rollover_minutes"] == 360  # Unchanged
            assert result["is_active"] is True  # Unchanged
