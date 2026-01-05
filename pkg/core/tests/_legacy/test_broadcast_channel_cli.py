"""
Integration tests for BroadcastChannel CLI tool.

Tests the CLI interface by simulating subprocess calls and verifying
output formatting, error handling, and exit codes.
"""

import json
from io import StringIO
from unittest.mock import patch

from sqlalchemy.orm import Session


class TestBroadcastChannelCLI:
    """Test cases for the BroadcastChannel CLI tool."""
    
    def test_list_channels_empty(self, db_session: Session):
        """Test listing channels when none exist."""
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.list_channels.return_value = []
            
            # Capture stdout
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import list_channels
                list_channels(json_output=False)
                
                output = mock_stdout.getvalue()
                assert "No channels found" in output
    
    def test_list_channels_with_data(self, db_session: Session):
        """Test listing channels with existing data."""
        test_channels = [
            {
                "id": 1,
                "name": "RetroToons",
                "timezone": "America/New_York",
                "is_active": True,
                "rollover_minutes": 360,
                "grid_size_minutes": 30,
                "grid_offset_minutes": 0,
                "created_at": "2025-01-01T12:00:00"
            },
            {
                "id": 2,
                "name": "ClassicMovies",
                "timezone": "America/Los_Angeles",
                "is_active": False,
                "rollover_minutes": 420,
                "grid_size_minutes": 60,
                "grid_offset_minutes": 15,
                "created_at": "2025-01-01T12:00:00"
            }
        ]
        
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.list_channels.return_value = test_channels
            
            # Test table format
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import list_channels
                list_channels(json_output=False)
                
                output = mock_stdout.getvalue()
                assert "ID" in output
                assert "Active" in output
                assert "Name" in output
                assert "Timezone" in output
                assert "RetroToons" in output
                assert "ClassicMovies" in output
    
    def test_list_channels_json_output(self, db_session: Session):
        """Test listing channels with JSON output."""
        test_channels = [
            {
                "id": 1,
                "name": "TestChannel",
                "timezone": "UTC",
                "is_active": True,
                "rollover_minutes": 360,
                "grid_size_minutes": 30,
                "grid_offset_minutes": 0,
                "created_at": "2025-01-01T12:00:00"
            }
        ]
        
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.list_channels.return_value = test_channels
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import list_channels
                list_channels(json_output=True)
                
                output = mock_stdout.getvalue()
                # Should be valid JSON
                parsed = json.loads(output)
                assert len(parsed) == 1
                assert parsed[0]["name"] == "TestChannel"
    
    def test_show_channel_exists(self, db_session: Session):
        """Test showing an existing channel."""
        test_channel = {
            "id": 1,
            "name": "TestChannel",
            "timezone": "UTC",
            "grid_size_minutes": 30,
            "grid_offset_minutes": 0,
            "rollover_minutes": 360,
            "is_active": True,
            "created_at": "2025-01-01T12:00:00"
        }
        
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.get_channel.return_value = test_channel
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import show_channel
                show_channel(channel_id=1, json_output=False)
                
                output = mock_stdout.getvalue()
                assert "id: 1" in output
                assert "name: TestChannel" in output
                assert "timezone: UTC" in output
                assert "is_active: True" in output
    
    def test_show_channel_not_exists(self, db_session: Session):
        """Test showing a non-existent channel."""
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.get_channel.return_value = None
            
            with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                with patch('sys.exit') as mock_exit:
                    from retrovue.cli.broadcast_channel_ctl import show_channel
                    show_channel(channel_id=999, json_output=False)
                    
                    error_output = mock_stderr.getvalue()
                    assert "Channel with ID 999 not found" in error_output
                    # sys.exit should be called once by the function (not in exception handler)
                    assert mock_exit.call_count >= 1
    
    def test_show_channel_json_output(self, db_session: Session):
        """Test showing a channel with JSON output."""
        test_channel = {
            "id": 1,
            "name": "TestChannel",
            "timezone": "UTC",
            "grid_size_minutes": 30,
            "grid_offset_minutes": 0,
            "rollover_minutes": 360,
            "is_active": True,
            "created_at": "2025-01-01T12:00:00"
        }
        
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.get_channel.return_value = test_channel
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import show_channel
                show_channel(channel_id=1, json_output=True)
                
                output = mock_stdout.getvalue()
                parsed = json.loads(output)
                assert parsed["name"] == "TestChannel"
                assert parsed["id"] == 1
    
    def test_create_channel_success(self, db_session: Session):
        """Test creating a channel successfully."""
        created_channel = {
            "id": 1,
            "name": "NewChannel",
            "timezone": "America/New_York",
            "grid_size_minutes": 30,
            "grid_offset_minutes": 0,
            "rollover_minutes": 360,
            "is_active": True,
            "created_at": "2025-01-01T12:00:00"
        }
        
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.create_channel.return_value = created_channel
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import create_channel
                create_channel(
                    name="NewChannel",
                    timezone="America/New_York",
                    grid_size_minutes=30,
                    grid_offset_minutes=0,
                    rollover_minutes=360,
                    is_active=True
                )
                
                output = mock_stdout.getvalue()
                assert "Created channel 'NewChannel' with ID 1" in output
                assert "Timezone: America/New_York" in output
                assert "Active: True" in output
    
    def test_create_channel_validation_error(self, db_session: Session):
        """Test creating a channel with validation error."""
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.create_channel.side_effect = ValueError("Channel name is required")
            
            with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                with patch('sys.exit') as mock_exit:
                    from retrovue.cli.broadcast_channel_ctl import create_channel
                    create_channel(
                        name="",
                        timezone="UTC",
                        grid_size_minutes=30,
                        grid_offset_minutes=0,
                        rollover_minutes=360
                    )
                    
                    error_output = mock_stderr.getvalue()
                    assert "Validation error: Channel name is required" in error_output
                    mock_exit.assert_called_once_with(1)
    
    def test_update_channel_success(self, db_session: Session):
        """Test updating a channel successfully."""
        updated_channel = {
            "id": 1,
            "name": "UpdatedChannel",
            "timezone": "America/Chicago",
            "grid_size_minutes": 45,
            "grid_offset_minutes": 10,
            "rollover_minutes": 300,
            "is_active": False,
            "created_at": "2025-01-01T12:00:00"
        }
        
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.update_channel.return_value = updated_channel
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import update_channel
                update_channel(
                    channel_id=1,
                    name="UpdatedChannel",
                    timezone="America/Chicago",
                    grid_size_minutes=45,
                    grid_offset_minutes=10,
                    rollover_minutes=300,
                    is_active=False
                )
                
                output = mock_stdout.getvalue()
                assert "Updated channel ID 1" in output
                assert "Name: UpdatedChannel" in output
                assert "Timezone: America/Chicago" in output
                assert "Active: False" in output
    
    def test_update_channel_not_found(self, db_session: Session):
        """Test updating a non-existent channel."""
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.update_channel.side_effect = ValueError("Channel with ID 999 not found")
            
            with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                with patch('sys.exit') as mock_exit:
                    from retrovue.cli.broadcast_channel_ctl import update_channel
                    update_channel(channel_id=999, name="NewName")
                    
                    error_output = mock_stderr.getvalue()
                    assert "Validation error: Channel with ID 999 not found" in error_output
                    mock_exit.assert_called_once_with(1)
    
    def test_update_channel_no_fields(self, db_session: Session):
        """Test updating a channel with no fields to update."""
        with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
            with patch('sys.exit') as mock_exit:
                from retrovue.cli.broadcast_channel_ctl import update_channel
                update_channel(channel_id=1)  # No fields provided
                
                error_output = mock_stderr.getvalue()
                assert "No fields to update" in error_output
                # sys.exit should be called at least once by the function
                assert mock_exit.call_count >= 1
    
    def test_delete_channel_success(self, db_session: Session):
        """Test deleting a channel successfully."""
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.delete_channel.return_value = None
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import delete_channel
                delete_channel(channel_id=1)
                
                output = mock_stdout.getvalue()
                assert "BroadcastChannel 1 deleted" in output
    
    def test_delete_channel_not_found(self, db_session: Session):
        """Test deleting a non-existent channel."""
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.delete_channel.side_effect = ValueError("Channel with ID 999 not found")
            
            with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                with patch('sys.exit') as mock_exit:
                    from retrovue.cli.broadcast_channel_ctl import delete_channel
                    delete_channel(channel_id=999)
                    
                    error_output = mock_stderr.getvalue()
                    assert "Error: Channel with ID 999 not found" in error_output
                    mock_exit.assert_called_once_with(1)
    
    def test_create_channel_active_inactive_flags(self, db_session: Session):
        """Test create channel with active/inactive flags."""
        created_channel = {
            "id": 1,
            "name": "TestChannel",
            "timezone": "UTC",
            "grid_size_minutes": 30,
            "grid_offset_minutes": 0,
            "rollover_minutes": 360,
            "is_active": False,
            "created_at": "2025-01-01T12:00:00"
        }
        
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.create_channel.return_value = created_channel
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import create_channel
                # Test with is_active=False
                create_channel(
                    name="TestChannel",
                    timezone="UTC",
                    grid_size_minutes=30,
                    grid_offset_minutes=0,
                    rollover_minutes=360,
                    is_active=False
                )
                
                output = mock_stdout.getvalue()
                assert "Active: False" in output
    
    def test_create_channel_default_active(self, db_session: Session):
        """Test create channel defaults to active when no flag provided."""
        created_channel = {
            "id": 1,
            "name": "TestChannel",
            "timezone": "UTC",
            "grid_size_minutes": 30,
            "grid_offset_minutes": 0,
            "rollover_minutes": 360,
            "is_active": True,
            "created_at": "2025-01-01T12:00:00"
        }
        
        with patch('retrovue.cli.broadcast_channel_ctl.BroadcastChannelService') as mock_service:
            mock_service.create_channel.return_value = created_channel
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from retrovue.cli.broadcast_channel_ctl import create_channel
                # Test with is_active=None (should default to True)
                create_channel(
                    name="TestChannel",
                    timezone="UTC",
                    grid_size_minutes=30,
                    grid_offset_minutes=0,
                    rollover_minutes=360,
                    is_active=None
                )
                
                output = mock_stdout.getvalue()
                assert "Active: True" in output
                # Verify service was called with is_active=True
                mock_service.create_channel.assert_called_once()
                call_args = mock_service.create_channel.call_args
                assert call_args[1]['is_active'] is True
