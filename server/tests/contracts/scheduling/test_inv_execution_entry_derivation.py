"""
Contract tests for INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001.

Every ExecutionEntry must be traceable to a PlaylistEvent (via TransmissionLogEntry),
except those created by an explicit recorded operator override.

PLAYLOG-008 (Tier 2): ExecutionEntry without PlaylistEventEntry reference is rejected.
PLAYLOG-009 (Tier 2): ExecutionEntry with operator override is accepted.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from retrovue.scheduling.execution_entry import ExecutionEntry
from retrovue.runtime.execution_window_store import ExecutionWindowStore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EPOCH = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
EPOCH_MS = int(EPOCH.timestamp() * 1000)
ONE_HOUR_MS = 60 * 60 * 1000
GRID_BLOCK_MS = 30 * 60 * 1000
CHANNEL_ID = "test-channel"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ee(
    *,
    idx: int,
    start_ms: int,
    end_ms: int,
    transmission_log_ref: str | None = None,
    is_operator_override: bool = False,
) -> ExecutionEntry:
    return ExecutionEntry(
        entry_id=f"ex-{idx:03d}",
        channel_id=CHANNEL_ID,
        start_utc_ms=start_ms,
        end_utc_ms=end_ms,
        asset_path="/media/test.ts",
        transmission_log_ref=transmission_log_ref or "",
        is_operator_override=is_operator_override,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvExecutionentryDerivedFromTransmissionlog001:
    """Contract tests for INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001."""

    def test_playlog_008_no_ref_no_override_rejected(self):
        """PLAYLOG-008: ExecutionEntry with no transmission_log_ref and
        no operator override record is rejected.

        Creation fails before reaching the store. Fault identifies
        the missing derivation anchor.
        """
        # Entry with empty ref and not an override
        orphan_entry = ExecutionEntry(
            entry_id="ex-orphan",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + GRID_BLOCK_MS,
            asset_path="/media/test.ts",
            transmission_log_ref="",  # empty = no reference
            is_operator_override=False,
        )

        store = ExecutionWindowStore(
            channel_id=CHANNEL_ID,
            enforce_derivation_from_playlist=True,
        )

        with pytest.raises(
            ValueError,
            match="INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001-VIOLATED",
        ):
            store.add_entries([orphan_entry])

        # No entry was committed
        assert len(store.entries) == 0

    def test_playlog_009_operator_override_accepted(self):
        """PLAYLOG-009: ExecutionEntry with operator override record is
        accepted even without a transmission_log_ref.

        Override entries are a constitutional escape hatch — they bypass
        the normal derivation chain but carry their own authorization.
        """
        override_entry = ExecutionEntry(
            entry_id="ex-override",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS + ONE_HOUR_MS,
            end_utc_ms=EPOCH_MS + ONE_HOUR_MS + GRID_BLOCK_MS,
            asset_path="/media/emergency.ts",
            transmission_log_ref="",  # no TL ref
            is_operator_override=True,  # but has override authorization
        )

        store = ExecutionWindowStore(
            channel_id=CHANNEL_ID,
            enforce_derivation_from_playlist=True,
        )

        # Must not raise — override is accepted
        store.add_entries([override_entry])

        assert len(store.entries) == 1
        assert store.entries[0].is_operator_override is True
        assert store.entries[0].entry_id == "ex-override"

    def test_valid_ref_accepted(self):
        """Positive path: entry with valid transmission_log_ref is accepted."""
        entry = _make_ee(
            idx=1,
            start_ms=EPOCH_MS,
            end_ms=EPOCH_MS + GRID_BLOCK_MS,
            transmission_log_ref="tl-001",
        )

        store = ExecutionWindowStore(
            channel_id=CHANNEL_ID,
            enforce_derivation_from_playlist=True,
        )

        store.add_entries([entry])
        assert len(store.entries) == 1

    def test_mixed_valid_and_orphan_all_rejected(self):
        """If any entry in a batch has no ref and no override,
        the entire batch is rejected (fail-fast)."""
        valid = _make_ee(
            idx=1,
            start_ms=EPOCH_MS,
            end_ms=EPOCH_MS + GRID_BLOCK_MS,
            transmission_log_ref="tl-001",
        )
        orphan = ExecutionEntry(
            entry_id="ex-orphan",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS + GRID_BLOCK_MS,
            end_utc_ms=EPOCH_MS + 2 * GRID_BLOCK_MS,
            asset_path="/media/test.ts",
            transmission_log_ref="",
            is_operator_override=False,
        )

        store = ExecutionWindowStore(
            channel_id=CHANNEL_ID,
            enforce_derivation_from_playlist=True,
        )

        with pytest.raises(
            ValueError,
            match="INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001-VIOLATED",
        ):
            store.add_entries([valid, orphan])

        # Nothing committed
        assert len(store.entries) == 0

    def test_enforcement_disabled_accepts_orphan(self):
        """When derivation enforcement is disabled, orphan entries are accepted."""
        orphan = ExecutionEntry(
            entry_id="ex-orphan",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + GRID_BLOCK_MS,
            asset_path="/media/test.ts",
            transmission_log_ref="",
            is_operator_override=False,
        )

        store = ExecutionWindowStore(
            channel_id=CHANNEL_ID,
            enforce_derivation_from_playlist=False,
        )

        store.add_entries([orphan])
        assert len(store.entries) == 1
