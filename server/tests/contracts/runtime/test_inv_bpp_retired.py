"""INV-BPP-RETIRED-001: BlockPlanProducer retires as ADR-004 Phase 5C.2
completes. Module removed; CM owns everything it previously did.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
CM_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "channel_manager.py"
BPP_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "block_plan_producer.py"
SRC_RUNTIME = REPO_ROOT / "server" / "src" / "retrovue" / "runtime"


class TestBlockPlanProducerModuleRetired:
    """The module file and class are no longer importable."""

    def test_module_file_does_not_exist(self) -> None:
        assert not BPP_PATH.exists(), (
            "server/src/retrovue/runtime/block_plan_producer.py MUST be deleted "
            "(INV-BPP-RETIRED-001)"
        )

    def test_module_is_not_importable(self) -> None:
        with pytest.raises(ImportError):
            importlib.import_module("retrovue.runtime.block_plan_producer")


class TestChannelManagerOwnsProducerActivity:
    """CM exposes is_producer_active() as the authoritative activity check."""

    def test_is_producer_active_present(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager
        assert hasattr(ChannelManager, "is_producer_active"), (
            "ChannelManager MUST expose is_producer_active() "
            "(INV-BPP-RETIRED-001)"
        )


class TestNoProductionImportsOfBpp:
    """No runtime-path production file imports BlockPlanProducer."""

    def test_no_production_imports(self) -> None:
        offenders: list[str] = []
        for py in SRC_RUNTIME.rglob("*.py"):
            text = py.read_text()
            if "from .block_plan_producer import" in text:
                offenders.append(str(py.relative_to(REPO_ROOT)))
            elif "from retrovue.runtime.block_plan_producer import" in text:
                offenders.append(str(py.relative_to(REPO_ROOT)))
            elif "import retrovue.runtime.block_plan_producer" in text:
                offenders.append(str(py.relative_to(REPO_ROOT)))
        assert not offenders, (
            f"Production files import retired BPP module: {offenders}"
        )

    def test_channel_manager_does_not_reexport_bpp(self) -> None:
        """CM MUST NOT import or re-export BlockPlanProducer. Legacy
        docstring mentions are tolerated (no functional effect)."""
        import ast
        tree = ast.parse(CM_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "block_plan_producer" in node.module:
                    pytest.fail(
                        "channel_manager.py MUST NOT import from "
                        f"block_plan_producer: {ast.dump(node)}"
                    )
                for alias in (node.names or []):
                    assert alias.name != "BlockPlanProducer", (
                        "channel_manager.py MUST NOT re-export BlockPlanProducer"
                    )
            if isinstance(node, ast.Import):
                for alias in (node.names or []):
                    assert "block_plan_producer" not in alias.name, (
                        "channel_manager.py MUST NOT import block_plan_producer module"
                    )


class TestProgramDirectorUsesCmActivityCheck:
    """PD's truthy guards use is_producer_active()."""

    def test_pd_does_not_check_active_producer_as_bpp(self) -> None:
        pd_path = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "program_director.py"
        src = pd_path.read_text()
        # 'if manager.active_producer:' implies BPP-instance truthiness.
        # Post-5C.2, the check MUST be via is_producer_active().
        assert "if manager.active_producer:" not in src, (
            "ProgramDirector MUST use manager.is_producer_active() instead of "
            "'if manager.active_producer:' (INV-BPP-RETIRED-001)"
        )
