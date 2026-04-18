"""INV-CM-AIR-GRPC-SOLE-OWNER-001: The gRPC surface to AIR (feed_blockplan,
iter_blockplan_events) is owned exclusively by AirBridge on the channel-
runtime path.

Post-Phase-5C.2 (INV-BPP-RETIRED-001): BPP-delegation assertions retired.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
AIR_BRIDGE_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "air_bridge.py"


class TestAirBridgeGrpcSurface:
    """AirBridge exposes the full gRPC surface and imports the helpers."""

    def test_air_bridge_exposes_iter_events(self) -> None:
        from retrovue.runtime.air_bridge import AirBridge

        assert hasattr(AirBridge, "iter_events"), (
            "AirBridge MUST expose iter_events() for BlockPlan event subscription"
        )

    def test_air_bridge_exposes_feed(self) -> None:
        from retrovue.runtime.air_bridge import AirBridge

        assert hasattr(AirBridge, "feed"), (
            "AirBridge MUST expose feed(block) for FeedBlockPlan RPC"
        )

    def test_air_bridge_imports_grpc_helpers(self) -> None:
        src = AIR_BRIDGE_PATH.read_text()
        assert "feed_blockplan" in src, "air_bridge.py MUST import feed_blockplan"
        assert "iter_blockplan_events" in src, (
            "air_bridge.py MUST import iter_blockplan_events"
        )


class TestNoOtherGrpcCallers:
    """No runtime-path module other than air_bridge.py imports the gRPC helpers."""

    def test_only_air_bridge_imports_grpc_helpers_on_runtime_path(self) -> None:
        runtime_root = REPO_ROOT / "server" / "src" / "retrovue" / "runtime"
        allowed = {(runtime_root / "air_bridge.py").resolve()}
        offenders: list[str] = []
        for py in runtime_root.rglob("*.py"):
            if py.resolve() in allowed:
                continue
            try:
                tree = ast.parse(py.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "channel_manager_launch" in node.module:
                        names = {alias.name for alias in (node.names or [])}
                        leaked = names & {"feed_blockplan", "iter_blockplan_events"}
                        if leaked:
                            offenders.append(
                                f"{py.relative_to(REPO_ROOT)}: {sorted(leaked)}"
                            )
        assert not offenders, (
            "On the runtime path, only retrovue.runtime.air_bridge may import "
            f"feed_blockplan/iter_blockplan_events. Offenders: {offenders}"
        )
