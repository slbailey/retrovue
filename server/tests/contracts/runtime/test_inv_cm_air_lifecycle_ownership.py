"""INV-CM-AIR-LIFECYCLE-SOLE-OWNER-001: AirBridge is the sole owner of the AIR
subprocess lifecycle.

Post-Phase-5C.2 (INV-BPP-RETIRED-001): BPP-specific delegation assertions
retired. The ownership invariant now reads: AirBridge owns subprocess
lifecycle; only AirBridge on the runtime path imports launch_air /
terminate_air.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
AIR_BRIDGE_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "air_bridge.py"


class TestAirBridgeModule:
    """AirBridge is importable with the required public surface."""

    def test_module_importable(self) -> None:
        mod = importlib.import_module("retrovue.runtime.air_bridge")
        assert hasattr(mod, "AirBridge"), "air_bridge.py MUST expose class AirBridge"

    def test_public_surface(self) -> None:
        from retrovue.runtime.air_bridge import AirBridge

        required = {"spawn", "terminate", "socket_path", "reader_socket_queue", "grpc_addr"}
        missing = required - set(dir(AirBridge))
        assert not missing, f"AirBridge missing required members: {sorted(missing)}"

    def test_imports_launch_air(self) -> None:
        """AirBridge MUST be the module that imports launch_air/terminate_air."""
        src = AIR_BRIDGE_PATH.read_text()
        assert "launch_air" in src, "air_bridge.py MUST import launch_air"
        assert "terminate_air" in src, "air_bridge.py MUST import terminate_air"


class TestNoOtherLaunchAirCallers:
    """No runtime-path module other than air_bridge.py imports launch_air/terminate_air."""

    def test_only_air_bridge_imports_launch_air_on_runtime_path(self) -> None:
        """Scan the runtime-path modules (``retrovue.runtime.*``) for imports
        of launch_air/terminate_air. Only air_bridge.py is permitted.

        Scope: channel-runtime path only. The usecase module itself defines
        launch_air/terminate_air and is naturally excluded. Operator-facing
        CLI tools (``retrovue.cli.*``) are excluded from this invariant —
        they may launch AIR manually for debugging without going through
        the channel runtime broker.
        """
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
                        leaked = names & {"launch_air", "terminate_air"}
                        if leaked:
                            offenders.append(f"{py.relative_to(REPO_ROOT)}: {sorted(leaked)}")
        assert not offenders, (
            "On the runtime path, only retrovue.runtime.air_bridge may import "
            f"launch_air/terminate_air. Offenders: {offenders}"
        )
