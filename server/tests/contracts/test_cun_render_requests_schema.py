"""
Contract tests for INV-CUN-SCHEDULE-SCOPED-001.

Validates that cun_render_requests exists as a dedicated table (not in processor_jobs)
with the required columns, constraints, and indexes for SKIP LOCKED claim patterns.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, text

from retrovue.infra.uow import session


class TestCunRenderRequestsSchema:
    """INV-CUN-SCHEDULE-SCOPED-001: CUN render queue is schedule-scoped."""

    def test_table_exists(self):
        """cun_render_requests table MUST exist as its own relation."""
        with session() as db:
            insp = inspect(db.bind)
            tables = insp.get_table_names()
        assert "cun_render_requests" in tables

    def test_table_is_separate_from_processor_jobs(self):
        """CUN render requests MUST NOT be stored in processor_jobs."""
        with session() as db:
            insp = inspect(db.bind)
            pj_cols = {c["name"] for c in insp.get_columns("processor_jobs")}
        # processor_jobs must not have CUN-specific columns
        assert "segment_start_utc" not in pj_cols
        assert "next_program_title" not in pj_cols
        assert "template_id" not in pj_cols
        assert "content_hash" not in pj_cols

    def test_required_columns_present(self):
        """All specified columns MUST exist with correct types."""
        with session() as db:
            insp = inspect(db.bind)
            cols = {c["name"]: c for c in insp.get_columns("cun_render_requests")}

        required = [
            "id", "channel_id", "segment_start_utc", "next_program_title",
            "template_id", "status", "rendered_asset_path", "content_hash",
            "priority", "error_message", "created_at", "started_at", "completed_at",
        ]
        for col_name in required:
            assert col_name in cols, f"Missing required column: {col_name}"

    def test_primary_key_is_id(self):
        """Primary key MUST be the id column."""
        with session() as db:
            insp = inspect(db.bind)
            pk = insp.get_pk_constraint("cun_render_requests")
        assert pk["constrained_columns"] == ["id"]

    def test_channel_id_foreign_key(self):
        """channel_id MUST reference channels(id)."""
        with session() as db:
            insp = inspect(db.bind)
            fks = insp.get_foreign_keys("cun_render_requests")
        channel_fks = [
            fk for fk in fks
            if fk["referred_table"] == "channels"
            and fk["constrained_columns"] == ["channel_id"]
            and fk["referred_columns"] == ["id"]
        ]
        assert len(channel_fks) == 1, "channel_id FK to channels(id) required"

    def test_unique_constraint_channel_segment(self):
        """UNIQUE(channel_id, segment_start_utc) MUST exist."""
        with session() as db:
            insp = inspect(db.bind)
            uniques = insp.get_unique_constraints("cun_render_requests")
        col_sets = [
            sorted(u["column_names"]) for u in uniques
        ]
        assert sorted(["channel_id", "segment_start_utc"]) in col_sets, \
            "UNIQUE(channel_id, segment_start_utc) constraint required"

    def test_pending_partial_index_exists(self):
        """Partial index on (status, priority, created_at) WHERE status='pending' MUST exist."""
        with session() as db:
            insp = inspect(db.bind)
            indexes = insp.get_indexes("cun_render_requests")
        pending_idx = [
            idx for idx in indexes
            if idx["name"] == "idx_cun_render_pending"
        ]
        assert len(pending_idx) == 1, "idx_cun_render_pending partial index required"

    def test_content_hash_partial_index_exists(self):
        """Partial index on (content_hash, status) WHERE status='completed' MUST exist."""
        with session() as db:
            insp = inspect(db.bind)
            indexes = insp.get_indexes("cun_render_requests")
        hash_idx = [
            idx for idx in indexes
            if idx["name"] == "idx_cun_render_content_hash"
        ]
        assert len(hash_idx) == 1, "idx_cun_render_content_hash partial index required"

    def test_status_default_is_pending(self):
        """status column MUST default to 'pending'."""
        with session() as db:
            insp = inspect(db.bind)
            cols = {c["name"]: c for c in insp.get_columns("cun_render_requests")}
        status_col = cols["status"]
        default = str(status_col.get("default", "") or "")
        assert "pending" in default.lower(), f"status default must be 'pending', got: {default}"

    def test_priority_default_is_100(self):
        """priority column MUST default to 100."""
        with session() as db:
            insp = inspect(db.bind)
            cols = {c["name"]: c for c in insp.get_columns("cun_render_requests")}
        priority_col = cols["priority"]
        default = str(priority_col.get("default", "") or "")
        assert "100" in default, f"priority default must be 100, got: {default}"
