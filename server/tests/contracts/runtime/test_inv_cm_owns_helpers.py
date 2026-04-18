"""INV-CM-OWNS-AIR-BRIDGE-001 + INV-CM-OWNS-SUPPLY-CONTROLLER-001:
ChannelManager constructs the per-channel AirBridge and SupplyController
itself as instance attributes.

Post-Phase-5C.2 (INV-BPP-RETIRED-001): helpers are no longer injected into
BPP (which is retired). CM holds them directly and its orchestration methods
use them.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
CM_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "channel_manager.py"


class TestChannelManagerImports:
    """CM imports AirBridge and SupplyController at the module level."""

    def test_cm_imports_air_bridge(self) -> None:
        src = CM_PATH.read_text()
        assert "from .air_bridge import AirBridge" in src or (
            "from retrovue.runtime.air_bridge import AirBridge" in src
        ), "channel_manager.py MUST import AirBridge"

    def test_cm_imports_supply_controller(self) -> None:
        src = CM_PATH.read_text()
        assert "from .supply_controller import SupplyController" in src or (
            "from retrovue.runtime.supply_controller import SupplyController" in src
        ), "channel_manager.py MUST import SupplyController"


class TestChannelManagerConstructsHelpers:
    """CM's producer-helpers construction path instantiates both."""

    def test_build_producer_constructs_air_bridge(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        src = inspect.getsource(ChannelManager._build_producer_for_mode)
        assert "AirBridge(" in src, (
            "ChannelManager._build_producer_for_mode MUST construct an AirBridge"
        )

    def test_build_producer_constructs_supply_controller(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        src = inspect.getsource(ChannelManager._build_producer_for_mode)
        assert "SupplyController(" in src, (
            "ChannelManager._build_producer_for_mode MUST construct a SupplyController"
        )

    def test_build_producer_stores_air_bridge_on_cm(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        src = inspect.getsource(ChannelManager._build_producer_for_mode)
        assert "self._air_bridge = " in src, (
            "CM's helper construction MUST store AirBridge on self._air_bridge "
            "(post-INV-BPP-RETIRED-001: no injection target; CM holds directly)"
        )

    def test_build_producer_stores_supply_on_cm(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        src = inspect.getsource(ChannelManager._build_producer_for_mode)
        assert "self._supply = " in src, (
            "CM's helper construction MUST store SupplyController on self._supply"
        )
