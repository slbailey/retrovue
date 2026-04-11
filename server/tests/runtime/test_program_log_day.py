"""
Tests for ProgramLogDay entity and rebuild CLI.
"""

from __future__ import annotations

from retrovue.domain.entities import ProgramLogDay


class TestProgramLogDayEntity:
    def test_entity_attributes(self):
        """ProgramLogDay has the expected columns."""
        assert hasattr(ProgramLogDay, "id")
        assert hasattr(ProgramLogDay, "channel_id")
        assert hasattr(ProgramLogDay, "broadcast_day")
        assert hasattr(ProgramLogDay, "schedule_hash")
        assert hasattr(ProgramLogDay, "program_log_json")
        assert hasattr(ProgramLogDay, "locked")
        assert hasattr(ProgramLogDay, "created_at")

    def test_table_name(self):
        assert ProgramLogDay.__tablename__ == "program_log_days"

    def test_unique_constraint(self):
        """Verify unique constraint on (channel_id, broadcast_day)."""
        constraints = [c.name for c in ProgramLogDay.__table__.constraints if hasattr(c, "name")]
        assert "uq_program_log_days_channel_day" in constraints
