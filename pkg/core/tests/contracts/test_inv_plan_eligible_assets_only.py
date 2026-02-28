"""Contract tests for INV-PLAN-ELIGIBLE-ASSETS-ONLY-001.

All SchedulableAssets resolved from an active SchedulePlan's zones must be
eligible (state=ready and approved_for_broadcast=true) at the time of
ScheduleDay generation.

Derived from: LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY.
"""

from __future__ import annotations

from datetime import time as dt_time

import pytest


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

_EOD = dt_time(23, 59, 59, 999999)


def _parse_time(t: str) -> dt_time:
    if t in ("24:00", "24:00:00"):
        return _EOD
    parts = t.split(":")
    return dt_time(int(parts[0]), int(parts[1]), 0)


class _StubZone:
    """Lightweight stand-in for a Zone entity (no DB required)."""

    def __init__(
        self,
        name: str = "zone",
        start_time: str = "00:00",
        end_time: str = "24:00",
        day_filters: list[str] | None = None,
        enabled: bool = True,
        schedulable_assets: list[str] | None = None,
    ):
        self.name = name
        self.enabled = enabled
        self.day_filters = day_filters
        self.start_time = _parse_time(start_time)
        self.end_time = _parse_time(end_time)
        self.schedulable_assets = schedulable_assets or []


def _make_checker(eligible_ids: set[str]):
    """Return an eligibility checker that treats listed IDs as eligible."""

    def checker(asset_id: str) -> tuple[bool, str]:
        if asset_id in eligible_ids:
            return (True, "")
        return (False, "state=enriching, approved_for_broadcast=false")

    return checker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvPlanEligibleAssetsOnly001:
    """INV-PLAN-ELIGIBLE-ASSETS-ONLY-001

    Only eligible assets (state=ready, approved_for_broadcast=true) may be
    resolved from an active plan's zones.

    Enforcement lives in check_asset_eligibility() called via
    validate_zone_plan_integrity().

    Derived from: LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY.
    """

    def test_reject_ineligible_asset_in_zone(self):
        """INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 -- negative

        Invariant: INV-PLAN-ELIGIBLE-ASSETS-ONLY-001
        Derived law(s): LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY
        Failure class: Planning
        Scenario: A zone references an asset with state=enriching,
                  approved_for_broadcast=false. validate_zone_plan_integrity
                  must raise ValueError with the invariant name.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(
                name="Primetime",
                start_time="00:00",
                end_time="24:00",
                schedulable_assets=["asset-ineligible-001"],
            ),
        ]

        checker = _make_checker(eligible_ids=set())  # nothing eligible

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity(
                zones, asset_eligibility_checker=checker
            )

        assert "INV-PLAN-ELIGIBLE-ASSETS-ONLY-001" in str(exc_info.value), (
            "INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 VIOLATED: "
            "ineligible asset in zone was rejected but the violation message "
            "does not carry the constitutional invariant name."
        )

    def test_accept_eligible_assets_in_zone(self):
        """INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 -- positive

        Invariant: INV-PLAN-ELIGIBLE-ASSETS-ONLY-001
        Derived law(s): LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: A zone references two assets that are both eligible
                  (state=ready, approved_for_broadcast=true). Must pass
                  without exception.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(
                name="Primetime",
                start_time="00:00",
                end_time="24:00",
                schedulable_assets=["asset-ok-001", "asset-ok-002"],
            ),
        ]

        checker = _make_checker(eligible_ids={"asset-ok-001", "asset-ok-002"})

        # Should not raise — all assets are eligible.
        validate_zone_plan_integrity(
            zones, asset_eligibility_checker=checker
        )

    def test_reject_mixed_eligible_and_ineligible(self):
        """INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 -- negative (mixed)

        Invariant: INV-PLAN-ELIGIBLE-ASSETS-ONLY-001
        Derived law(s): LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY
        Failure class: Planning
        Scenario: A zone references one eligible and one ineligible asset.
                  The ineligible asset must cause rejection.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(
                name="Daytime",
                start_time="00:00",
                end_time="24:00",
                schedulable_assets=["asset-ok-001", "asset-bad-001"],
            ),
        ]

        checker = _make_checker(eligible_ids={"asset-ok-001"})

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity(
                zones, asset_eligibility_checker=checker
            )

        msg = str(exc_info.value)
        assert "INV-PLAN-ELIGIBLE-ASSETS-ONLY-001" in msg
        assert "asset-bad-001" in msg

    def test_skip_check_when_no_resolver(self):
        """INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 -- no resolver

        When no asset_eligibility_checker is provided, eligibility
        checking is skipped (backward compatible). The zone still
        passes grid/overlap/coverage checks.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(
                name="Primetime",
                start_time="00:00",
                end_time="24:00",
                schedulable_assets=["anything"],
            ),
        ]

        # No checker → no eligibility enforcement. Should not raise.
        validate_zone_plan_integrity(zones)
