"""INV-CM-SUPPLY-RESOLUTION-SOLE-OWNER-001: Block resolution and failure-
surfacing are owned exclusively by SupplyController.

Post-Phase-5C.2 (INV-BPP-RETIRED-001): BPP-module checks retired; the
surviving invariant is that SupplyController exposes the resolution surface
and that ChannelManager's ``_producer_driver_loop`` routes through it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
CM_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "channel_manager.py"


class TestSupplyControllerResolutionSurface:
    """SupplyController exposes resolve_current, resolve_next, fail."""

    def test_resolve_current_present(self) -> None:
        from retrovue.runtime.supply_controller import SupplyController
        assert hasattr(SupplyController, "resolve_current")

    def test_resolve_next_present(self) -> None:
        from retrovue.runtime.supply_controller import SupplyController
        assert hasattr(SupplyController, "resolve_next")

    def test_fail_present(self) -> None:
        from retrovue.runtime.supply_controller import SupplyController
        assert hasattr(SupplyController, "fail")


class TestChannelManagerDriverLoopUsesSupply:
    """CM's orchestration routes through SupplyController, not the reader."""

    def test_driver_loop_uses_supply_resolve_next(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager
        src = inspect.getsource(ChannelManager._producer_driver_loop)
        assert "self._supply.resolve_next" in src, (
            "CM's driver loop MUST resolve next-block via self._supply.resolve_next(...)"
        )

    def test_producer_start_uses_supply_resolve_current(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager
        src = inspect.getsource(ChannelManager._producer_start)
        assert "self._supply.resolve_current" in src, (
            "CM's producer-start MUST resolve current-block via "
            "self._supply.resolve_current(...)"
        )

    def test_producer_fail_routes_through_supply(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager
        src = inspect.getsource(ChannelManager._producer_fail)
        assert "self._supply.fail" in src, (
            "CM's producer-fail MUST delegate to self._supply.fail(reason) "
            "for log + callback dispatch"
        )
