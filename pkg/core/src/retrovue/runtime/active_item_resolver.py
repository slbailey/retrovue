"""
Phase 3 — Active Schedule Item Resolver.

Resolve the active conceptual item using plan + configured durations.
Pure logic: (plan, elapsed_in_grid_ms, duration config) → active ScheduleItem.
No media, no paths, no ChannelManager.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from retrovue.runtime.grid import GRID_DURATION_MS
from retrovue.runtime.mock_schedule import ScheduleItem, ScheduleItemId

if TYPE_CHECKING:
    from retrovue.runtime.asset_metadata import Asset

# Mock duration config (Phase 3). Time units: milliseconds (int64).
SAMPLE_DURATION_MS = 1_499_000   # 24:59
GRID_DURATION_MS_CONFIG = 1_800_000  # 30:00, must match Phase 1
FILLER_START_MS = SAMPLE_DURATION_MS  # filler starts at 24:59 into grid


@dataclass(frozen=True)
class MockDurationConfig:
    """Phase 3 mock duration config. Not part of the plan. Prefer from_assets (Phase 2.5)."""

    sample_duration_ms: int = SAMPLE_DURATION_MS
    grid_duration_ms: int = GRID_DURATION_MS_CONFIG
    filler_start_ms: int = FILLER_START_MS

    def __post_init__(self) -> None:
        if self.filler_start_ms != self.sample_duration_ms:
            raise ValueError("filler_start_ms must equal sample_duration_ms in mock config")

    @classmethod
    def from_assets(cls, sample_asset: "Asset", grid_duration_ms: int = GRID_DURATION_MS) -> "MockDurationConfig":
        """Build config from Phase 2.5 Asset metadata. Does not open files."""
        if sample_asset.duration_ms >= grid_duration_ms:
            raise ValueError(
                f"samplecontent duration_ms ({sample_asset.duration_ms}) must be < grid_duration_ms ({grid_duration_ms})"
            )
        return cls(
            sample_duration_ms=sample_asset.duration_ms,
            grid_duration_ms=grid_duration_ms,
            filler_start_ms=sample_asset.duration_ms,
        )


def resolve_active_item(
    elapsed_in_grid_ms: int,
    *,
    config: MockDurationConfig | None = None,
) -> ScheduleItem:
    """
    Resolve the active ScheduleItem for the current moment.

    Rule: elapsed_in_grid_ms < filler_start_ms → samplecontent;
          elapsed_in_grid_ms >= filler_start_ms → filler.

    Args:
        elapsed_in_grid_ms: Elapsed time within the current grid (ms). From Phase 1.
        config: Mock duration config. Defaults to standard Phase 3 values.

    Returns:
        Active ScheduleItem (conceptual id only; no paths or PTS).

    Raises:
        ValueError: If grid_duration_ms != Phase 1 GRID_DURATION_MS (config error).
    """
    cfg = config or MockDurationConfig()

    # Grid consistency: fail fast if Phase 1 grid duration changes
    if cfg.grid_duration_ms != GRID_DURATION_MS:
        raise ValueError(
            f"grid_duration_ms ({cfg.grid_duration_ms}) must equal Phase 1 grid duration ({GRID_DURATION_MS}); "
            "configuration error"
        )

    if elapsed_in_grid_ms < cfg.filler_start_ms:
        return ScheduleItem("samplecontent")
    return ScheduleItem("filler")


def get_active_item_id(elapsed_in_grid_ms: int, config: MockDurationConfig | None = None) -> ScheduleItemId:
    """Convenience: return the active item id only (no ScheduleItem)."""
    return resolve_active_item(elapsed_in_grid_ms, config=config).id
