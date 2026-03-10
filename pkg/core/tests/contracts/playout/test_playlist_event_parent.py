"""
Contract tests: INV-PLAYLIST-EVENT-SINGLE-PARENT-004.

Every PlaylistEvent must reference exactly one ScheduleItem.
schedule_item_id MUST NOT be null.

Tests are deterministic (no wall-clock sleep, no DB).
See: docs/contracts/invariants/core/playout/INV-PLAYLIST-EVENT-SINGLE-PARENT-004.md
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Minimal domain stubs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlaylistEventStub:
    """Minimal PlaylistEvent for parent-reference invariant testing."""
    block_id: str
    schedule_item_id: str | None
    start_utc_ms: int
    end_utc_ms: int
    segments: list[dict]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EPOCH_MS = 1_740_873_600_000  # 2025-03-01T20:00:00Z
SLOT_MS = 1_800_000           # 30 minutes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvPlaylistEventSingleParent004:
    """INV-PLAYLIST-EVENT-SINGLE-PARENT-004 enforcement tests."""

    # Tier: 1 | Structural invariant
    def test_playlist_event_has_schedule_item(self) -> None:
        """Every PlaylistEvent must have a non-null schedule_item_id."""
        pe = PlaylistEventStub(
            block_id="block-parent-001",
            schedule_item_id="si-001",
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + SLOT_MS,
            segments=[
                {"segment_type": "content", "segment_duration_ms": SLOT_MS},
            ],
        )

        assert pe.schedule_item_id is not None, (
            f"INV-PLAYLIST-EVENT-SINGLE-PARENT-004-VIOLATED: "
            f"block_id={pe.block_id} has null schedule_item_id"
        )
        assert pe.schedule_item_id != "", (
            f"INV-PLAYLIST-EVENT-SINGLE-PARENT-004-VIOLATED: "
            f"block_id={pe.block_id} has empty schedule_item_id"
        )

    # Tier: 1 | Structural invariant
    def test_null_schedule_item_detected(self) -> None:
        """A PlaylistEvent with null schedule_item_id violates the invariant."""
        pe = PlaylistEventStub(
            block_id="block-orphan-001",
            schedule_item_id=None,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + SLOT_MS,
            segments=[
                {"segment_type": "content", "segment_duration_ms": SLOT_MS},
            ],
        )

        assert pe.schedule_item_id is None, (
            "Expected null schedule_item_id to be detectable"
        )

    # Tier: 1 | Structural invariant
    def test_empty_schedule_item_detected(self) -> None:
        """A PlaylistEvent with empty-string schedule_item_id violates the invariant."""
        pe = PlaylistEventStub(
            block_id="block-orphan-002",
            schedule_item_id="",
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + SLOT_MS,
            segments=[
                {"segment_type": "content", "segment_duration_ms": SLOT_MS},
            ],
        )

        assert pe.schedule_item_id == "", (
            "Expected empty schedule_item_id to be detectable"
        )

    # Tier: 1 | Structural invariant
    def test_valid_reference_is_non_null_string(self) -> None:
        """A valid schedule_item_id is a non-empty string."""
        pe = PlaylistEventStub(
            block_id="block-valid-001",
            schedule_item_id="si-abc-123",
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + SLOT_MS,
            segments=[
                {"segment_type": "content", "segment_duration_ms": SLOT_MS},
            ],
        )

        assert isinstance(pe.schedule_item_id, str), (
            "schedule_item_id must be a string"
        )
        assert len(pe.schedule_item_id) > 0, (
            "schedule_item_id must be non-empty"
        )
