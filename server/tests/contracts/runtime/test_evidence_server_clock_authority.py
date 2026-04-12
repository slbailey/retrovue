"""INV-AUTHORITY-SINGLE-OWNER-001 — Evidence server clock authority tests.

Proves that DurableAckStore and AsRunWriter use an injected MasterClock
for all timestamps, not datetime.now() or time.time().

V6 from RETA-8 audit: evidence_server.py uses datetime.now(timezone.utc)
directly in AckStore._persist_to_disk (line 261), AsRunWriter.__init__
(lines 277, 294).
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.evidence_server import AsRunWriter, DurableAckStore


class TestDurableAckStoreClockAuthority:
    """DurableAckStore must use injected clock, not datetime.now()."""

    def test_persist_uses_injected_clock(self, tmp_path: Path) -> None:
        """Ack file updated_utc must reflect injected clock, not wall clock."""
        # Controlled clock pinned to a known time far from wall clock.
        clock = ControllableMasterClock(
            epoch=datetime(2000, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        )
        store = DurableAckStore(ack_dir=str(tmp_path), clock=clock)
        store.update("ch1", "sess1", 42)

        ack_file = tmp_path / "ch1" / "sess1.ack"
        content = ack_file.read_text()
        # The timestamp must come from the controlled clock (2000-06-15T12:00:00)
        assert "2000-06-15T12:00:00" in content, (
            f"AckStore._persist_to_disk still uses datetime.now() — "
            f"expected controlled clock time 2000-06-15T12:00:00, got:\n{content}"
        )

    def test_persist_does_not_call_datetime_now(self, tmp_path: Path) -> None:
        """datetime.now must not be called from _persist_to_disk."""
        clock = ControllableMasterClock(
            epoch=datetime(2000, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        )
        store = DurableAckStore(ack_dir=str(tmp_path), clock=clock)

        with patch("retrovue.runtime.evidence_server.datetime") as mock_dt:
            mock_dt.now.side_effect = AssertionError(
                "datetime.now() called — clock authority violation"
            )
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            # Should NOT raise — persist should use injected clock
            store.update("ch1", "sess1", 1)


class TestAsRunWriterClockAuthority:
    """AsRunWriter must use injected clock, not datetime.now()."""

    def test_init_uses_injected_clock_for_date(self, tmp_path: Path) -> None:
        """AsRunWriter must derive 'today' from the injected clock."""
        clock = ControllableMasterClock(
            epoch=datetime(2000, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        )
        writer = AsRunWriter("ch1", asrun_dir=str(tmp_path), clock=clock)
        try:
            # File should be named with the controlled clock date, not today's date.
            expected_asrun = tmp_path / "ch1" / "2000-06-15.asrun"
            assert expected_asrun.exists(), (
                f"AsRunWriter used wall-clock date for filename — "
                f"expected {expected_asrun}, but it does not exist. "
                f"Files: {list((tmp_path / 'ch1').iterdir())}"
            )
        finally:
            writer.close()

    def test_header_uses_injected_clock(self, tmp_path: Path) -> None:
        """AsRunWriter header OPENED_UTC must reflect the injected clock."""
        clock = ControllableMasterClock(
            epoch=datetime(2000, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        )
        writer = AsRunWriter("ch1", asrun_dir=str(tmp_path), clock=clock)
        try:
            asrun_file = tmp_path / "ch1" / "2000-06-15.asrun"
            if asrun_file.exists():
                header = asrun_file.read_text()
                assert "2000-06-15" in header, (
                    f"Header OPENED_UTC uses wall clock — expected controlled time, "
                    f"got:\n{header}"
                )
        finally:
            writer.close()
