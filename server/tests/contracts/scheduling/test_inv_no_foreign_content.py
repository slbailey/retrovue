"""
Contract tests for INV-NO-FOREIGN-CONTENT-001.

No artifact at any layer may reference an asset not traceable to its
upstream authority.

CROSS-FOREIGN-001 (Tier 2): Foreign asset in ScheduleDay slot rejected.
CROSS-FOREIGN-002 (Tier 2): Foreign asset in TransmissionLogEntry rejected.
CROSS-FOREIGN-003 (Tier 2): Foreign asset in ExecutionEntry rejected.
"""

from __future__ import annotations

from datetime import date

import pytest

from retrovue.scheduling.execution_entry import ExecutionEntry
from retrovue.scheduling.foreign_content_validation import (
    validate_execution_entry_assets,
    validate_scheduleday_assets,
    validate_transmission_log_assets,
)
from retrovue.scheduling.transmission_log import TransmissionLogEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tl_entry(
    entry_id: str = "tl-001",
    asset_id: str = "asset-eligible",
    asset_path: str = "/media/eligible.ts",
) -> TransmissionLogEntry:
    return TransmissionLogEntry(
        entry_id=entry_id,
        channel_id="test-channel",
        broadcast_day=date(2026, 1, 1),
        start_utc_ms=0,
        end_utc_ms=1800_000,
        asset_id=asset_id,
        asset_path=asset_path,
        title="Eligible Show",
        plan_id="plan-001",
        schedule_day_date=date(2026, 1, 1),
    )


def _exec_entry(
    entry_id: str = "ex-001",
    asset_path: str = "/media/eligible.ts",
    is_override: bool = False,
) -> ExecutionEntry:
    return ExecutionEntry(
        entry_id=entry_id,
        channel_id="test-channel",
        start_utc_ms=0,
        end_utc_ms=1800_000,
        asset_path=asset_path,
        transmission_log_ref="tl-001",
        is_operator_override=is_override,
    )


# ---------------------------------------------------------------------------
# CROSS-FOREIGN-001: ScheduleDay layer
# ---------------------------------------------------------------------------

class TestInvNoForeignContent001:
    """Contract tests for INV-NO-FOREIGN-CONTENT-001."""

    def test_cross_foreign_001_foreign_asset_in_scheduleday_rejected(self):
        """CROSS-FOREIGN-001: A ScheduleDay slot referencing an asset
        absent from the generating plan's zones is rejected."""
        plan_assets = {"asset-eligible-1", "asset-eligible-2"}

        # Slot references a foreign asset
        slot_asset_ids = ["asset-eligible-1", "asset-FOREIGN"]

        with pytest.raises(ValueError, match="INV-NO-FOREIGN-CONTENT-001-VIOLATED"):
            validate_scheduleday_assets(
                slot_asset_ids=slot_asset_ids,
                plan_asset_ids=plan_assets,
            )

    def test_cross_foreign_001_eligible_assets_pass(self):
        """CROSS-FOREIGN-001 (positive): All assets from plan zones pass."""
        plan_assets = {"asset-eligible-1", "asset-eligible-2"}
        slot_asset_ids = ["asset-eligible-1", "asset-eligible-2"]

        # Must not raise
        validate_scheduleday_assets(
            slot_asset_ids=slot_asset_ids,
            plan_asset_ids=plan_assets,
        )

    # -------------------------------------------------------------------
    # CROSS-FOREIGN-002: TransmissionLog layer
    # -------------------------------------------------------------------

    def test_cross_foreign_002_foreign_asset_in_transmission_log_rejected(self):
        """CROSS-FOREIGN-002: A TransmissionLogEntry referencing an asset
        absent from the source ResolvedScheduleDay is rejected."""
        sd_asset_ids = {"asset-eligible"}

        entries = [
            _tl_entry(entry_id="tl-001", asset_id="asset-eligible"),
            _tl_entry(entry_id="tl-002", asset_id="asset-FOREIGN"),
        ]

        with pytest.raises(ValueError, match="INV-NO-FOREIGN-CONTENT-001-VIOLATED"):
            validate_transmission_log_assets(
                tl_entries=entries,
                scheduleday_asset_ids=sd_asset_ids,
            )

    def test_cross_foreign_002_eligible_assets_pass(self):
        """CROSS-FOREIGN-002 (positive): All assets from ScheduleDay pass."""
        sd_asset_ids = {"asset-eligible"}

        entries = [_tl_entry(entry_id="tl-001", asset_id="asset-eligible")]

        # Must not raise
        validate_transmission_log_assets(
            tl_entries=entries,
            scheduleday_asset_ids=sd_asset_ids,
        )

    # -------------------------------------------------------------------
    # CROSS-FOREIGN-003: ExecutionEntry layer
    # -------------------------------------------------------------------

    def test_cross_foreign_003_foreign_asset_in_execution_entry_rejected(self):
        """CROSS-FOREIGN-003: An ExecutionEntry referencing an asset path
        absent from the source TransmissionLog is rejected."""
        tl_asset_paths = {"/media/eligible.ts"}

        entries = [
            _exec_entry(entry_id="ex-001", asset_path="/media/eligible.ts"),
            _exec_entry(entry_id="ex-002", asset_path="/media/FOREIGN.ts"),
        ]

        with pytest.raises(ValueError, match="INV-NO-FOREIGN-CONTENT-001-VIOLATED"):
            validate_execution_entry_assets(
                exec_entries=entries,
                transmission_log_asset_paths=tl_asset_paths,
            )

    def test_cross_foreign_003_eligible_assets_pass(self):
        """CROSS-FOREIGN-003 (positive): All assets from TransmissionLog pass."""
        tl_asset_paths = {"/media/eligible.ts"}

        entries = [_exec_entry(entry_id="ex-001", asset_path="/media/eligible.ts")]

        # Must not raise
        validate_execution_entry_assets(
            exec_entries=entries,
            transmission_log_asset_paths=tl_asset_paths,
        )

    def test_cross_foreign_003_operator_override_exempt(self):
        """CROSS-FOREIGN-003: Operator overrides are exempt from
        foreign content validation — they explicitly authorize substitution."""
        tl_asset_paths = {"/media/eligible.ts"}

        entries = [
            _exec_entry(
                entry_id="ex-override",
                asset_path="/media/OVERRIDE.ts",
                is_override=True,
            ),
        ]

        # Must not raise — override exemption
        validate_execution_entry_assets(
            exec_entries=entries,
            transmission_log_asset_paths=tl_asset_paths,
        )
