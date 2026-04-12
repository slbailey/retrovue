"""
Contract tests for INV-EXECUTIONENTRY-MASTERCLOCK-ALIGNED-001.

ExecutionEntry timestamps MUST be derived exclusively from MasterClock
at generation time. No ExecutionEntry may use an independent wall-clock,
local timestamp, or any time source other than the session's MasterClock.

PLAYLOG-002 (Tier 2): Timestamps match the injected clock.
PLAYLOG-003 (Tier 2): Different injected clocks produce different timestamps.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from retrovue.scheduling.execution_entry import derive_execution_entries
from retrovue.scheduling.transmission_log import TransmissionLogEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# EPOCH: a fixed reference point for deterministic clock injection.
EPOCH = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
EPOCH_MS = int(EPOCH.timestamp() * 1000)


def _make_tl_entry(
    *,
    start_utc_ms: int,
    end_utc_ms: int,
    channel_id: str = "test-channel",
    entry_id: str = "tl-001",
    asset_path: str = "/media/show.ts",
) -> TransmissionLogEntry:
    """Build a TransmissionLogEntry with explicit clock-derived timestamps."""
    return TransmissionLogEntry(
        entry_id=entry_id,
        channel_id=channel_id,
        broadcast_day=date(2026, 1, 1),
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        asset_id="asset-001",
        asset_path=asset_path,
        title="Test Show",
        plan_id="plan-001",
        schedule_day_date=date(2026, 1, 1),
    )


# ---------------------------------------------------------------------------
# PLAYLOG-002: ExecutionEntry timestamps match the injected clock
# ---------------------------------------------------------------------------

class TestInvExecutionentryMasterclockAligned001:
    """Contract tests for INV-EXECUTIONENTRY-MASTERCLOCK-ALIGNED-001."""

    def test_playlog_002_timestamps_match_injected_clock(self):
        """PLAYLOG-002: ExecutionEntry timestamps are derived from the
        source TransmissionLogEntry timestamps (which are MasterClock-derived).

        Given a TransmissionLogEntry with start=EPOCH+30min, end=EPOCH+60min,
        the derived ExecutionEntry must have identical timestamps.
        """
        thirty_min_ms = 30 * 60 * 1000
        sixty_min_ms = 60 * 60 * 1000

        tl = _make_tl_entry(
            start_utc_ms=EPOCH_MS + thirty_min_ms,
            end_utc_ms=EPOCH_MS + sixty_min_ms,
        )

        entries = derive_execution_entries([tl])

        assert len(entries) == 1
        ee = entries[0]
        assert ee.start_utc_ms == EPOCH_MS + thirty_min_ms
        assert ee.end_utc_ms == EPOCH_MS + sixty_min_ms
        # Traceability back to source
        assert ee.transmission_log_ref == tl.entry_id

    def test_playlog_003_different_clocks_produce_different_timestamps(self):
        """PLAYLOG-003: Two generation runs with different injected clock
        values produce timestamps differing by the exact clock delta.

        Run A: clock at EPOCH → entry [EPOCH+30min, EPOCH+60min]
        Run B: clock at EPOCH+24h → entry [EPOCH+24h+30min, EPOCH+24h+60min]

        The 24-hour delta between clocks must be exactly reflected.
        """
        thirty_min_ms = 30 * 60 * 1000
        sixty_min_ms = 60 * 60 * 1000
        twenty_four_hours_ms = 24 * 60 * 60 * 1000

        # Run A: clock at EPOCH
        tl_a = _make_tl_entry(
            entry_id="tl-run-a",
            start_utc_ms=EPOCH_MS + thirty_min_ms,
            end_utc_ms=EPOCH_MS + sixty_min_ms,
        )
        entries_a = derive_execution_entries([tl_a])

        # Run B: clock at EPOCH + 24h
        tl_b = _make_tl_entry(
            entry_id="tl-run-b",
            start_utc_ms=EPOCH_MS + twenty_four_hours_ms + thirty_min_ms,
            end_utc_ms=EPOCH_MS + twenty_four_hours_ms + sixty_min_ms,
        )
        entries_b = derive_execution_entries([tl_b])

        ee_a = entries_a[0]
        ee_b = entries_b[0]

        # Timestamps differ by exactly 24 hours
        assert ee_b.start_utc_ms - ee_a.start_utc_ms == twenty_four_hours_ms
        assert ee_b.end_utc_ms - ee_a.end_utc_ms == twenty_four_hours_ms

        # No shared state between runs
        assert ee_a.entry_id != ee_b.entry_id
        assert ee_a.transmission_log_ref != ee_b.transmission_log_ref

    def test_multiple_entries_all_clock_derived(self):
        """Multiple TransmissionLogEntries produce ExecutionEntries with
        timestamps exactly matching their source — no drift, no rounding."""
        grid_ms = 30 * 60 * 1000  # 30-min grid

        tl_entries = [
            _make_tl_entry(
                entry_id=f"tl-{i:03d}",
                start_utc_ms=EPOCH_MS + i * grid_ms,
                end_utc_ms=EPOCH_MS + (i + 1) * grid_ms,
            )
            for i in range(48)  # Full 24-hour day
        ]

        exec_entries = derive_execution_entries(tl_entries)

        assert len(exec_entries) == 48
        for i, ee in enumerate(exec_entries):
            assert ee.start_utc_ms == EPOCH_MS + i * grid_ms
            assert ee.end_utc_ms == EPOCH_MS + (i + 1) * grid_ms
            assert ee.transmission_log_ref == f"tl-{i:03d}"
