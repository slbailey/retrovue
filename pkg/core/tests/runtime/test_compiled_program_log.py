"""
Tests for CompiledProgramLog entity and rebuild CLI.
"""

from __future__ import annotations

from retrovue.domain.entities import CompiledProgramLog


class TestCompiledProgramLogEntity:
    def test_entity_attributes(self):
        """CompiledProgramLog has the expected columns."""
        assert hasattr(CompiledProgramLog, "id")
        assert hasattr(CompiledProgramLog, "channel_id")
        assert hasattr(CompiledProgramLog, "broadcast_day")
        assert hasattr(CompiledProgramLog, "schedule_hash")
        assert hasattr(CompiledProgramLog, "compiled_json")
        assert hasattr(CompiledProgramLog, "locked")
        assert hasattr(CompiledProgramLog, "created_at")

    def test_table_name(self):
        assert CompiledProgramLog.__tablename__ == "compiled_program_log"

    def test_unique_constraint(self):
        """Verify unique constraint on (channel_id, broadcast_day)."""
        constraints = [c.name for c in CompiledProgramLog.__table__.constraints if hasattr(c, "name")]
        assert "uq_compiled_program_log_channel_day" in constraints
