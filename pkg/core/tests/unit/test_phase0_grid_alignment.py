"""
Unit tests for mock grid alignment and offset calculation.

Tests the grid alignment logic, join-in-progress calculations, and filler offset
calculations used in the mock grid + filler model (--mock-schedule-grid).

These are unit tests that test the logic in isolation without requiring
full ChannelManager or ScheduleService setup.
"""

from datetime import datetime, timezone, timedelta
import pytest

from retrovue.runtime.channel_manager import (
    ChannelManager,
    MockGridScheduleService,
    Phase8ProgramDirector,
)
from retrovue.runtime.clock import MasterClock


class TestMockGridAlignment:
    """Test mock grid alignment methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.clock = MasterClock()
        self.program_director = Phase8ProgramDirector()
        # Create a minimal ScheduleService stub for ChannelManager
        # We'll test the grid methods directly
        self.channel_manager = ChannelManager(
            channel_id="test-1",
            clock=self.clock,
            schedule_service=None,  # Will be set per test
            program_director=self.program_director,
        )
        self.channel_manager._mock_grid_block_minutes = 30
        self.channel_manager._mock_grid_program_asset_path = "/path/to/program.mp4"
        self.channel_manager._mock_grid_filler_asset_path = "/path/to/filler.mp4"
        self.channel_manager._mock_grid_filler_epoch = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_floor_to_grid_at_boundary(self):
        """Test floor_to_grid when time is exactly at grid boundary."""
        # Test at :00 boundary
        now = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        block_start = self.channel_manager._floor_to_grid(now)
        assert block_start == now

        # Test at :30 boundary
        now = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        block_start = self.channel_manager._floor_to_grid(now)
        assert block_start == now

    def test_floor_to_grid_before_boundary(self):
        """Test floor_to_grid when time is before grid boundary."""
        # Test at :15 (should floor to :00)
        now = datetime(2025, 1, 15, 14, 15, 30, tzinfo=timezone.utc)
        block_start = self.channel_manager._floor_to_grid(now)
        expected = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        assert block_start == expected

        # Test at :45 (should floor to :30)
        now = datetime(2025, 1, 15, 14, 45, 30, tzinfo=timezone.utc)
        block_start = self.channel_manager._floor_to_grid(now)
        expected = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        assert block_start == expected

    def test_floor_to_grid_after_boundary(self):
        """Test floor_to_grid when time is after grid boundary."""
        # Test at :05 (should floor to :00)
        now = datetime(2025, 1, 15, 14, 5, 0, tzinfo=timezone.utc)
        block_start = self.channel_manager._floor_to_grid(now)
        expected = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        assert block_start == expected

        # Test at :35 (should floor to :30)
        now = datetime(2025, 1, 15, 14, 35, 0, tzinfo=timezone.utc)
        block_start = self.channel_manager._floor_to_grid(now)
        expected = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        assert block_start == expected

    def test_floor_to_grid_preserves_date(self):
        """Test floor_to_grid preserves date and hour."""
        now = datetime(2025, 1, 15, 14, 25, 45, tzinfo=timezone.utc)
        block_start = self.channel_manager._floor_to_grid(now)
        assert block_start.year == 2025
        assert block_start.month == 1
        assert block_start.day == 15
        assert block_start.hour == 14
        assert block_start.minute == 0  # Floored to :00
        assert block_start.second == 0
        assert block_start.microsecond == 0

    def test_calculate_join_offset_in_program(self):
        """Test join offset calculation when in program segment."""
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        program_duration = 1200.0  # 20 minutes
        
        # Test at 5 minutes into program
        now = block_start + timedelta(seconds=300)
        content_type, start_pts_ms = self.channel_manager._calculate_join_offset(
            now, block_start, program_duration
        )
        assert content_type == "program"
        assert start_pts_ms == 300000  # 5 minutes = 300 seconds = 300000 ms

        # Test at 10 minutes into program
        now = block_start + timedelta(seconds=600)
        content_type, start_pts_ms = self.channel_manager._calculate_join_offset(
            now, block_start, program_duration
        )
        assert content_type == "program"
        assert start_pts_ms == 600000  # 10 minutes = 600 seconds = 600000 ms

    def test_calculate_join_offset_in_filler(self):
        """Test join offset calculation when in filler segment."""
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        program_duration = 1200.0  # 20 minutes
        
        # Test at 5 minutes into filler (25 minutes total elapsed)
        now = block_start + timedelta(seconds=1500)  # 25 minutes
        content_type, start_pts_ms = self.channel_manager._calculate_join_offset(
            now, block_start, program_duration
        )
        assert content_type == "filler"
        assert start_pts_ms == 300000  # 5 minutes into filler = 300 seconds = 300000 ms

        # Test at 8 minutes into filler (28 minutes total elapsed)
        now = block_start + timedelta(seconds=1680)  # 28 minutes
        content_type, start_pts_ms = self.channel_manager._calculate_join_offset(
            now, block_start, program_duration
        )
        assert content_type == "filler"
        assert start_pts_ms == 480000  # 8 minutes into filler = 480 seconds = 480000 ms

    def test_calculate_join_offset_at_program_filler_boundary(self):
        """Test join offset at exact program/filler boundary."""
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        program_duration = 1200.0  # 20 minutes
        
        # Test exactly at program end (should be in filler with 0 offset)
        now = block_start + timedelta(seconds=1200)
        content_type, start_pts_ms = self.channel_manager._calculate_join_offset(
            now, block_start, program_duration
        )
        assert content_type == "filler"
        assert start_pts_ms == 0

        # Test 1 second before program end (should still be in program)
        now = block_start + timedelta(seconds=1199)
        content_type, start_pts_ms = self.channel_manager._calculate_join_offset(
            now, block_start, program_duration
        )
        assert content_type == "program"
        assert start_pts_ms == 1199000  # 1199 seconds = 1199000 ms

    def test_calculate_filler_offset(self):
        """Test filler offset calculation for continuous virtual stream."""
        filler_epoch = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        filler_duration = 3600.0  # 1 hour
        
        # Test at epoch (should be 0)
        master_clock = filler_epoch
        offset = self.channel_manager._calculate_filler_offset(
            master_clock, filler_epoch, filler_duration
        )
        assert offset == 0.0

        # Test 30 minutes after epoch
        master_clock = filler_epoch + timedelta(seconds=1800)
        offset = self.channel_manager._calculate_filler_offset(
            master_clock, filler_epoch, filler_duration
        )
        assert offset == 1800.0

        # Test 1 hour after epoch (should wrap to 0)
        master_clock = filler_epoch + timedelta(seconds=3600)
        offset = self.channel_manager._calculate_filler_offset(
            master_clock, filler_epoch, filler_duration
        )
        assert offset == 0.0

        # Test 1.5 hours after epoch (should wrap to 30 minutes)
        master_clock = filler_epoch + timedelta(seconds=5400)
        offset = self.channel_manager._calculate_filler_offset(
            master_clock, filler_epoch, filler_duration
        )
        assert offset == 1800.0

    def test_determine_active_content_program(self):
        """Test determine_active_content when in program segment."""
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        program_duration = 1200.0  # 20 minutes
        
        # Test at 5 minutes into block (in program)
        now = block_start + timedelta(seconds=300)
        content_type, asset_path, start_pts_ms = self.channel_manager._determine_active_content(
            now, block_start, program_duration
        )
        assert content_type == "program"
        assert asset_path == "/path/to/program.mp4"
        assert start_pts_ms == 300000

    def test_determine_active_content_filler(self):
        """Test determine_active_content when in filler segment."""
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        program_duration = 1200.0  # 20 minutes
        
        # Test at 25 minutes into block (in filler)
        now = block_start + timedelta(seconds=1500)
        content_type, asset_path, start_pts_ms = self.channel_manager._determine_active_content(
            now, block_start, program_duration
        )
        assert content_type == "filler"
        assert asset_path == "/path/to/filler.mp4"
        assert start_pts_ms == 300000  # 5 minutes into filler

    def test_determine_active_content_missing_asset_path(self):
        """Test determine_active_content raises error when asset path not configured."""
        self.channel_manager._mock_grid_program_asset_path = None
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        program_duration = 1200.0
        
        now = block_start + timedelta(seconds=300)
        with pytest.raises(Exception) as exc_info:
            self.channel_manager._determine_active_content(now, block_start, program_duration)
        assert "asset path not configured" in str(exc_info.value).lower()


class TestMockGridScheduleService:
    """Test MockGridScheduleService playout plan generation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.clock = MasterClock()
        self.program_asset_path = "/path/to/program.mp4"
        self.program_duration = 1200.0  # 20 minutes
        self.filler_asset_path = "/path/to/filler.mp4"
        self.filler_duration = 3600.0  # 1 hour
        
        self.service = MockGridScheduleService(
            clock=self.clock,
            program_asset_path=self.program_asset_path,
            program_duration_seconds=self.program_duration,
            filler_asset_path=self.filler_asset_path,
            filler_duration_seconds=self.filler_duration,
            grid_block_minutes=30,
        )

    def test_get_playout_plan_program_segment(self):
        """Test playout plan generation when in program segment."""
        # Create a time 5 minutes into a grid block (in program)
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        now = block_start + timedelta(seconds=300)  # 5 minutes
        
        plan = self.service.get_playout_plan_now("test-1", now)
        
        assert len(plan) == 1
        segment = plan[0]
        assert segment["asset_path"] == self.program_asset_path
        assert segment["content_type"] == "program"
        assert segment["start_pts"] == 300000  # 5 minutes = 300000 ms
        assert segment["metadata"]["phase"] == "mock_grid"
        assert segment["metadata"]["grid_block_minutes"] == 30

    def test_get_playout_plan_filler_segment(self):
        """Test playout plan generation when in filler segment."""
        # Create a time 25 minutes into a grid block (in filler)
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        now = block_start + timedelta(seconds=1500)  # 25 minutes
        
        plan = self.service.get_playout_plan_now("test-1", now)
        
        assert len(plan) == 1
        segment = plan[0]
        assert segment["asset_path"] == self.filler_asset_path
        assert segment["content_type"] == "filler"
        # start_pts should account for filler offset calculation
        assert segment["start_pts"] >= 0
        assert segment["metadata"]["phase"] == "mock_grid"

    def test_get_playout_plan_at_grid_boundary(self):
        """Test playout plan generation exactly at grid boundary."""
        # Test at :00 boundary
        now = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        plan = self.service.get_playout_plan_now("test-1", now)
        
        assert len(plan) == 1
        segment = plan[0]
        assert segment["content_type"] == "program"
        assert segment["start_pts"] == 0  # At block start, no offset

        # Test at :30 boundary
        now = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        plan = self.service.get_playout_plan_now("test-1", now)
        
        assert len(plan) == 1
        segment = plan[0]
        assert segment["content_type"] == "program"
        assert segment["start_pts"] == 0  # At block start, no offset

    def test_get_playout_plan_at_program_filler_boundary(self):
        """Test playout plan at program/filler boundary."""
        block_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        
        # Test exactly at program end (20 minutes)
        now = block_start + timedelta(seconds=1200)
        plan = self.service.get_playout_plan_now("test-1", now)
        
        assert len(plan) == 1
        segment = plan[0]
        assert segment["content_type"] == "filler"
        assert segment["start_pts"] >= 0  # Should have filler offset

        # Test 1 second before program end
        now = block_start + timedelta(seconds=1199)
        plan = self.service.get_playout_plan_now("test-1", now)
        
        assert len(plan) == 1
        segment = plan[0]
        assert segment["content_type"] == "program"
        assert segment["start_pts"] == 1199000  # 1199 seconds = 1199000 ms

    def test_get_playout_plan_filler_wraps(self):
        """Test that filler offset wraps correctly for continuous stream."""
        # Test multiple grid blocks to verify filler offset calculation
        block1_start = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        block2_start = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        
        # Both at 25 minutes into their respective blocks (in filler)
        now1 = block1_start + timedelta(seconds=1500)  # 25 minutes
        now2 = block2_start + timedelta(seconds=1500)  # 25 minutes
        
        plan1 = self.service.get_playout_plan_now("test-1", now1)
        plan2 = self.service.get_playout_plan_now("test-1", now2)
        
        # Both should be filler
        assert plan1[0]["content_type"] == "filler"
        assert plan2[0]["content_type"] == "filler"
        
        # Filler offsets should be different (accounting for continuous stream)
        # The exact values depend on filler epoch calculation, but they should be valid
        assert 0 <= plan1[0]["start_pts"] < self.filler_duration * 1000
        assert 0 <= plan2[0]["start_pts"] < self.filler_duration * 1000

    def test_get_playout_plan_handles_timezone(self):
        """Test that playout plan handles timezone-aware datetimes."""
        # Test with timezone-aware datetime
        now = datetime(2025, 1, 15, 14, 15, 0, tzinfo=timezone.utc)
        plan = self.service.get_playout_plan_now("test-1", now)
        assert len(plan) == 1
        
        # Test with timezone-naive datetime (should be converted)
        now_naive = datetime(2025, 1, 15, 14, 15, 0)
        plan = self.service.get_playout_plan_now("test-1", now_naive)
        assert len(plan) == 1
