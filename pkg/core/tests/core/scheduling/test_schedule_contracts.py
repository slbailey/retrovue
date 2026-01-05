"""
Unit tests for scheduling domain contracts.

Tests validation functions for:
- SchedulePlanInvariantsContract
- ProgramContract
- ScheduleDayContract
- PlaylogEventContract
"""

from datetime import datetime, time, timezone

import pytest

from retrovue.core.scheduling.contracts import (
    validate_block_assignment,
    validate_playlog_event,
    validate_schedule_day,
    validate_schedule_plan,
)
from retrovue.core.scheduling.exceptions import (
    BlockAssignmentValidationError,
    PlaylogEventValidationError,
    ScheduleDayValidationError,
    SchedulePlanValidationError,
)


# Mock objects for testing
class MockSchedulePlan:
    """Mock SchedulePlan for testing."""

    def __init__(self, id=None, name="TestPlan", channel_id=None, channel=None, block_assignments=None, programs=None, labels=None):
        self.id = id
        self.name = name
        self.channel_id = channel_id
        self.channel = channel  # Channel relationship (may be loaded)
        # Support both old and new attribute names for backward compatibility
        self.block_assignments = block_assignments or []
        self.programs = programs or block_assignments or []
        self.labels = labels or []


class MockBlockAssignment:
    """Mock Program for testing."""

    def __init__(
        self,
        id=None,
        start_time="00:00",
        duration=30,
        content_type="asset",
        content_ref=None,
        content_reference=None,
        label_id=None,
    ):
        self.id = id
        self.start_time = start_time
        self.duration = duration
        self.content_type = content_type
        # Support both old and new attribute names for backward compatibility
        # Use explicit values if provided, otherwise fall back to the other or default
        # This allows tests to explicitly set None to test validation
        if content_ref is not None:
            self.content_ref = content_ref
            self.content_reference = content_reference if content_reference is not None else content_ref
        elif content_reference is not None:
            self.content_ref = content_reference
            self.content_reference = content_reference
        else:
            # Both are None - check if we should preserve None or use default
            # If content_reference was explicitly passed as None (for testing), preserve it
            # Otherwise use default for backward compatibility
            # We can't distinguish "not passed" from "passed as None" in Python,
            # so we'll preserve None when both are None to allow validation tests
            self.content_ref = None
            self.content_reference = None
        self.label_id = label_id


class MockScheduleDay:
    """Mock BroadcastScheduleDay for testing."""

    def __init__(self, id=None, channel_id=None, schedule_date="2025-01-01", playlog_events=None):
        self.id = id
        self.channel_id = channel_id
        self.schedule_date = schedule_date
        self.playlog_events = playlog_events or []


class MockPlaylogEvent:
    """Mock BroadcastPlaylogEvent for testing."""

    def __init__(
        self,
        uuid=None,
        channel_id=None,
        asset_uuid=None,
        start_utc=None,
        end_utc=None,
        schedule_day_id=None,
        broadcast_day="2025-01-01",
    ):
        self.uuid = uuid
        self.id = uuid  # Some models use id instead of uuid
        self.channel_id = channel_id
        self.asset_uuid = asset_uuid
        self.start_utc = start_utc
        self.end_utc = end_utc
        self.schedule_day_id = schedule_day_id
        self.broadcast_day = broadcast_day


class MockChannel:
    """Mock Channel for testing."""

    def __init__(self, id=None, programming_day_start=time(6, 0), grid_block_minutes=None, block_start_offsets_minutes=None):
        self.id = id
        self.programming_day_start = programming_day_start
        self.grid_block_minutes = grid_block_minutes
        self.block_start_offsets_minutes = block_start_offsets_minutes


class TestSchedulePlanInvariantsContract:
    """Tests for SchedulePlanInvariantsContract validation."""

    def test_valid_sequential_plan(self):
        """Valid sequential plan should pass validation."""
        assignments = [
            MockBlockAssignment(id="1", start_time="00:00", duration=30),
            MockBlockAssignment(id="2", start_time="00:30", duration=30),
            MockBlockAssignment(id="3", start_time="01:00", duration=60),
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments)

        # Should not raise
        validate_schedule_plan(plan)

    def test_overlapping_blocks_should_fail(self):
        """Overlapping blocks should fail validation."""
        assignments = [
            MockBlockAssignment(id="1", start_time="00:00", duration=60),  # 00:00-01:00
            MockBlockAssignment(id="2", start_time="00:30", duration=60),  # 00:30-01:30 (overlaps!)
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments)

        with pytest.raises(SchedulePlanValidationError) as exc_info:
            validate_schedule_plan(plan)

        assert "overlap" in str(exc_info.value).lower()
        assert len(exc_info.value.violations) > 0

    def test_touching_blocks_should_pass(self):
        """Blocks that touch at boundaries should pass."""
        assignments = [
            MockBlockAssignment(id="1", start_time="00:00", duration=30),  # 00:00-00:30
            MockBlockAssignment(id="2", start_time="00:30", duration=30),  # 00:30-01:00 (touches)
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments)

        # Should not raise
        validate_schedule_plan(plan)

    def test_gaps_between_blocks_should_pass(self):
        """Gaps between blocks should pass validation."""
        assignments = [
            MockBlockAssignment(id="1", start_time="00:00", duration=30),  # 00:00-00:30
            MockBlockAssignment(id="2", start_time="01:00", duration=30),  # 01:00-01:30 (gap)
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments)

        # Should not raise
        validate_schedule_plan(plan)

    def test_total_duration_exceeds_24_hours_should_fail(self):
        """Total duration exceeding 24 hours should fail."""
        # Create assignments that total more than 24 hours
        assignments = [
            MockBlockAssignment(id="1", start_time="00:00", duration=12 * 60),  # 12 hours
            MockBlockAssignment(id="2", start_time="12:00", duration=12 * 60),  # 12 hours
            MockBlockAssignment(id="3", start_time="00:00", duration=60),  # 1 hour (overlaps with 1)
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments)

        with pytest.raises(SchedulePlanValidationError) as exc_info:
            validate_schedule_plan(plan)

        assert "exceeds 24 hours" in str(exc_info.value).lower() or "overlap" in str(exc_info.value).lower()

    def test_invalid_start_time_format_should_fail(self):
        """Invalid start_time format should fail."""
        assignments = [
            MockBlockAssignment(id="1", start_time="invalid", duration=30),
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments)

        with pytest.raises(SchedulePlanValidationError) as exc_info:
            validate_schedule_plan(plan)

        assert "invalid" in str(exc_info.value).lower() or "format" in str(exc_info.value).lower()

    def test_negative_duration_should_fail(self):
        """Negative duration should fail."""
        assignments = [
            MockBlockAssignment(id="1", start_time="00:00", duration=-10),
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments)

        with pytest.raises(SchedulePlanValidationError) as exc_info:
            validate_schedule_plan(plan)

        assert "invalid duration" in str(exc_info.value).lower() or "duration" in str(exc_info.value).lower()

    def test_missing_label_reference_should_fail(self):
        """Block assignment referencing non-existent label should fail."""
        assignments = [
            MockBlockAssignment(id="1", start_time="00:00", duration=30, label_id="missing-label"),
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments, labels=[])

        with pytest.raises(SchedulePlanValidationError) as exc_info:
            validate_schedule_plan(plan)

        assert "label" in str(exc_info.value).lower()

    def test_valid_label_reference_should_pass(self):
        """Block assignment referencing existing label should pass."""
        class MockLabel:
            def __init__(self, id):
                self.id = id

        label = MockLabel(id="label-1")
        assignments = [
            MockBlockAssignment(id="1", start_time="00:00", duration=30, label_id="label-1"),
        ]
        plan = MockSchedulePlan(id="plan-1", block_assignments=assignments, labels=[label])

        # Should not raise
        validate_schedule_plan(plan)

    def test_plan_with_channel_validates_grid_boundaries(self):
        """Plan with channel relationship should validate grid boundaries on assignments."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        assignments = [
            MockBlockAssignment(
                id="1",
                start_time="06:00",
                duration=25,  # Not a multiple of 30!
                content_type="asset",
                content_reference="ref",
            ),
        ]
        plan = MockSchedulePlan(id="plan-1", channel=channel, block_assignments=assignments)

        with pytest.raises(SchedulePlanValidationError) as exc_info:
            validate_schedule_plan(plan)

        # Should include grid boundary violation
        assert "multiple" in str(exc_info.value).lower() or "grid" in str(exc_info.value).lower()

    def test_plan_with_channel_valid_grid_should_pass(self):
        """Plan with channel and valid grid-aligned assignments should pass."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        assignments = [
            MockBlockAssignment(
                id="1",
                start_time="06:00",
                duration=30,  # Valid
                content_type="asset",
                content_reference="ref",
            ),
            MockBlockAssignment(
                id="2",
                start_time="06:30",
                duration=60,  # Valid
                content_type="asset",
                content_reference="ref",
            ),
        ]
        plan = MockSchedulePlan(id="plan-1", channel=channel, block_assignments=assignments)

        # Should not raise
        validate_schedule_plan(plan)


class TestSchedulePlanBlockAssignmentContract:
    """Tests for ProgramContract validation."""

    def test_valid_assignment_should_pass(self):
        """Valid assignment should pass validation."""
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",
            duration=30,
            content_type="asset",
            content_reference="asset-uuid-123",
        )

        # Should not raise
        validate_block_assignment(assignment)

    def test_missing_start_time_should_fail(self):
        """Missing start_time should fail."""
        assignment = MockBlockAssignment(id="assign-1", start_time=None, duration=30)

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment)

        assert "start_time" in str(exc_info.value).lower()

    def test_missing_duration_should_fail(self):
        """Missing duration should fail."""
        assignment = MockBlockAssignment(id="assign-1", start_time="06:00", duration=None)

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment)

        assert "duration" in str(exc_info.value).lower()

    def test_negative_duration_should_fail(self):
        """Negative duration should fail."""
        assignment = MockBlockAssignment(id="assign-1", start_time="06:00", duration=-10)

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment)

        assert "positive" in str(exc_info.value).lower()

    def test_invalid_content_type_should_fail(self):
        """Invalid content_type should fail."""
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",
            duration=30,
            content_type="invalid_type",
            content_reference="ref",
        )

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment)

        assert "content_type" in str(exc_info.value).lower()

    def test_missing_content_reference_should_fail(self):
        """Missing content_reference should fail."""
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",
            duration=30,
            content_type="asset",
            content_reference=None,
        )

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment)

        # The validation error uses "content_ref" in the message
        assert "content_ref" in str(exc_info.value).lower() or "content_reference" in str(exc_info.value).lower()

    def test_invalid_start_time_format_should_fail(self):
        """Invalid start_time format should fail."""
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="25:00",  # Invalid hour
            duration=30,
            content_type="asset",
            content_reference="ref",
        )

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment)

        assert "range" in str(exc_info.value).lower() or "format" in str(exc_info.value).lower()

    def test_valid_grid_aligned_assignment_should_pass(self):
        """Assignment aligned with 30-minute grid should pass."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",  # Aligned with 30-min grid
            duration=30,  # Multiple of 30
            content_type="asset",
            content_reference="ref",
        )

        # Should not raise
        validate_block_assignment(assignment, channel=channel)

    def test_duration_not_multiple_of_grid_should_fail(self):
        """Duration not a multiple of grid size should fail."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",
            duration=25,  # Not a multiple of 30!
            content_type="asset",
            content_reference="ref",
        )

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment, channel=channel)

        assert "multiple" in str(exc_info.value).lower() or "grid size" in str(exc_info.value).lower()
        assert "25" in str(exc_info.value)
        assert "30" in str(exc_info.value)

    def test_start_time_not_aligned_with_grid_should_fail(self):
        """Start time not aligned with grid boundaries should fail."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:15",  # Not aligned with 30-min grid (should be 06:00 or 06:30)
            duration=30,
            content_type="asset",
            content_reference="ref",
        )

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment, channel=channel)

        assert "align" in str(exc_info.value).lower() or "grid" in str(exc_info.value).lower()

    def test_valid_grid_aligned_with_offset_should_pass(self):
        """Assignment aligned with grid using offset should pass."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[5])
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:05",  # Aligned with offset 5 + 30-min grid
            duration=30,
            content_type="asset",
            content_reference="ref",
        )

        # Should not raise
        validate_block_assignment(assignment, channel=channel)

    def test_valid_60_minute_grid_should_pass(self):
        """Assignment aligned with 60-minute grid should pass."""
        channel = MockChannel(grid_block_minutes=60, block_start_offsets_minutes=[0])
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",
            duration=60,  # Multiple of 60
            content_type="asset",
            content_reference="ref",
        )

        # Should not raise
        validate_block_assignment(assignment, channel=channel)

    def test_60_minute_grid_with_30_minute_duration_should_fail(self):
        """30-minute duration on 60-minute grid should fail."""
        channel = MockChannel(grid_block_minutes=60, block_start_offsets_minutes=[0])
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",
            duration=30,  # Not a multiple of 60!
            content_type="asset",
            content_reference="ref",
        )

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment, channel=channel)

        assert "multiple" in str(exc_info.value).lower()

    def test_assignment_without_channel_should_skip_grid_validation(self):
        """Assignment without channel should skip grid validation."""
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:15",  # Would fail grid validation
            duration=25,  # Would fail grid validation
            content_type="asset",
            content_reference="ref",
        )

        # Should not raise (grid validation skipped when channel not provided)
        validate_block_assignment(assignment)

    def test_multiple_allowed_offsets_should_pass(self):
        """Assignment aligned with any allowed offset should pass."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[0, 15])
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:15",  # Aligned with offset 15
            duration=30,
            content_type="asset",
            content_reference="ref",
        )

        # Should not raise
        validate_block_assignment(assignment, channel=channel)

    def test_assignment_with_plan_channel_should_validate_grid(self):
        """Assignment with plan that has channel should automatically validate grid."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        plan = MockSchedulePlan(id="plan-1", channel=channel)
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",
            duration=25,  # Not a multiple of 30!
            content_type="asset",
            content_reference="ref",
        )

        # Should fail because duration is not a multiple of grid size
        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment, plan=plan)

        assert "multiple" in str(exc_info.value).lower() or "grid size" in str(exc_info.value).lower()

    def test_assignment_with_plan_channel_valid_should_pass(self):
        """Assignment with plan that has channel and valid grid alignment should pass."""
        channel = MockChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        plan = MockSchedulePlan(id="plan-1", channel=channel)
        assignment = MockBlockAssignment(
            id="assign-1",
            start_time="06:00",
            duration=30,  # Valid multiple of 30
            content_type="asset",
            content_reference="ref",
        )

        # Should not raise
        validate_block_assignment(assignment, plan=plan)


class TestScheduleDayContract:
    """Tests for ScheduleDayContract validation."""

    def test_valid_schedule_day_should_pass(self):
        """Valid schedule day should pass validation."""
        events = [
            MockPlaylogEvent(
                uuid="event-1",
                start_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
                end_utc=datetime(2025, 1, 1, 6, 30, 0, tzinfo=timezone.utc),
                schedule_day_id="day-1",
            ),
            MockPlaylogEvent(
                uuid="event-2",
                start_utc=datetime(2025, 1, 1, 6, 30, 0, tzinfo=timezone.utc),
                end_utc=datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc),
                schedule_day_id="day-1",
            ),
        ]
        schedule_day = MockScheduleDay(id="day-1", playlog_events=events)

        # Should not raise
        validate_schedule_day(schedule_day)

    def test_overlapping_playlog_events_should_fail(self):
        """Overlapping playlog events should fail."""
        events = [
            MockPlaylogEvent(
                uuid="event-1",
                start_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
                end_utc=datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc),
                schedule_day_id="day-1",
            ),
            MockPlaylogEvent(
                uuid="event-2",
                start_utc=datetime(2025, 1, 1, 6, 30, 0, tzinfo=timezone.utc),  # Overlaps!
                end_utc=datetime(2025, 1, 1, 7, 30, 0, tzinfo=timezone.utc),
                schedule_day_id="day-1",
            ),
        ]
        schedule_day = MockScheduleDay(id="day-1", playlog_events=events)

        with pytest.raises(ScheduleDayValidationError) as exc_info:
            validate_schedule_day(schedule_day)

        assert "overlap" in str(exc_info.value).lower()

    def test_invalid_timestamp_should_fail(self):
        """Invalid timestamp (start >= end) should fail."""
        events = [
            MockPlaylogEvent(
                uuid="event-1",
                start_utc=datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc),
                end_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),  # End before start!
                schedule_day_id="day-1",
            ),
        ]
        schedule_day = MockScheduleDay(id="day-1", playlog_events=events)

        with pytest.raises(ScheduleDayValidationError) as exc_info:
            validate_schedule_day(schedule_day)

        assert "start_utc" in str(exc_info.value).lower() or "end_utc" in str(exc_info.value).lower()

    def test_schedule_day_id_mismatch_should_fail(self):
        """PlaylogEvent with mismatched schedule_day_id should fail."""
        events = [
            MockPlaylogEvent(
                uuid="event-1",
                start_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
                end_utc=datetime(2025, 1, 1, 6, 30, 0, tzinfo=timezone.utc),
                schedule_day_id="wrong-day",  # Mismatch!
            ),
        ]
        schedule_day = MockScheduleDay(id="day-1", playlog_events=events)

        with pytest.raises(ScheduleDayValidationError) as exc_info:
            validate_schedule_day(schedule_day)

        assert "mismatch" in str(exc_info.value).lower() or "schedule_day_id" in str(exc_info.value).lower()


class TestPlaylogEventContract:
    """Tests for PlaylogEventContract validation."""

    def test_valid_playlog_event_should_pass(self):
        """Valid playlog event should pass validation."""
        event = MockPlaylogEvent(
            uuid="event-1",
            channel_id="channel-1",
            asset_uuid="asset-123",
            start_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
            end_utc=datetime(2025, 1, 1, 6, 30, 0, tzinfo=timezone.utc),
            broadcast_day="2025-01-01",
        )

        # Should not raise
        validate_playlog_event(event)

    def test_missing_start_utc_should_fail(self):
        """Missing start_utc should fail."""
        event = MockPlaylogEvent(
            uuid="event-1",
            start_utc=None,
            end_utc=datetime(2025, 1, 1, 6, 30, 0, tzinfo=timezone.utc),
        )

        with pytest.raises(PlaylogEventValidationError) as exc_info:
            validate_playlog_event(event)

        assert "start_utc" in str(exc_info.value).lower()

    def test_missing_end_utc_should_fail(self):
        """Missing end_utc should fail."""
        event = MockPlaylogEvent(
            uuid="event-1",
            start_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
            end_utc=None,
        )

        with pytest.raises(PlaylogEventValidationError) as exc_info:
            validate_playlog_event(event)

        assert "end_utc" in str(exc_info.value).lower()

    def test_start_utc_greater_than_end_utc_should_fail(self):
        """start_utc >= end_utc should fail."""
        event = MockPlaylogEvent(
            uuid="event-1",
            start_utc=datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc),
            end_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
        )

        with pytest.raises(PlaylogEventValidationError) as exc_info:
            validate_playlog_event(event)

        assert "less than" in str(exc_info.value).lower() or "start_utc" in str(exc_info.value).lower()

    def test_missing_asset_uuid_should_fail(self):
        """Missing asset_uuid should fail."""
        event = MockPlaylogEvent(
            uuid="event-1",
            asset_uuid=None,
            start_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
            end_utc=datetime(2025, 1, 1, 6, 30, 0, tzinfo=timezone.utc),
        )

        with pytest.raises(PlaylogEventValidationError) as exc_info:
            validate_playlog_event(event)

        assert "asset_uuid" in str(exc_info.value).lower()

    def test_invalid_broadcast_day_format_should_fail(self):
        """Invalid broadcast_day format should fail."""
        event = MockPlaylogEvent(
            uuid="event-1",
            start_utc=datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
            end_utc=datetime(2025, 1, 1, 6, 30, 0, tzinfo=timezone.utc),
            broadcast_day="invalid-format",
        )

        with pytest.raises(PlaylogEventValidationError) as exc_info:
            validate_playlog_event(event)

        assert "broadcast_day" in str(exc_info.value).lower() or "format" in str(exc_info.value).lower()


class TestPolicyRuleViolation:
    """Tests for ContentPolicyRule validation (future feature placeholder)."""

    def test_policy_rule_validation_placeholder(self):
        """Placeholder test for ContentPolicyRule validation."""
        # When ContentPolicyRule is implemented, add tests here
        # Example: family_safe policy should reject adult content
        pass

