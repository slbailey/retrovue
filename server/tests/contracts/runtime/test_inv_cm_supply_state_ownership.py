"""INV-CM-SUPPLY-STATE-SOLE-WRITER-001: Supply bookkeeping (current-block
cursor, last-fed-block dedup) is owned exclusively by SupplyController.

Post-Phase-5C.2 (INV-BPP-RETIRED-001): BPP-delegation assertions retired.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]


class TestSupplyControllerModule:
    """SupplyController module and class are present with the required surface."""

    def test_module_importable(self) -> None:
        mod = importlib.import_module("retrovue.runtime.supply_controller")
        assert hasattr(mod, "SupplyController"), (
            "supply_controller.py MUST expose class SupplyController"
        )

    def test_public_surface(self) -> None:
        from retrovue.runtime.supply_controller import SupplyController

        required = {
            "seed", "mark_fed", "is_duplicate_feed", "reset",
            "current_block", "last_fed_block_id",
        }
        missing = required - set(dir(SupplyController))
        assert not missing, f"SupplyController missing members: {sorted(missing)}"


class TestNoOtherSupplyStateWriters:
    """No runtime-path module other than SupplyController writes the supply fields."""

    def test_only_supply_controller_writes_cursor_fields(self) -> None:
        runtime_root = REPO_ROOT / "server" / "src" / "retrovue" / "runtime"
        allowed = {(runtime_root / "supply_controller.py").resolve()}
        forbidden_tokens = ["._current_block =", "._last_fed_block_id ="]
        offenders: list[str] = []
        for py in runtime_root.rglob("*.py"):
            if py.resolve() in allowed:
                continue
            text = py.read_text()
            for token in forbidden_tokens:
                if token in text:
                    offenders.append(f"{py.relative_to(REPO_ROOT)}: writes {token!r}")
        assert not offenders, (
            "Supply cursor / last-fed fields may be written only by SupplyController. "
            f"Offenders: {offenders}"
        )
