"""Contract integrity guardrails.

Prevents silent drift between contracts, tests, and implementation.
These checks are fast, deterministic, and require no database.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# (a) IMPORT SAFETY — every module under tests/contracts/ must import cleanly
# ---------------------------------------------------------------------------

CONTRACTS_DIR = Path(__file__).resolve().parent


def _discover_test_modules() -> list[str]:
    """Return dotted module names for every .py file under tests/contracts/."""
    # The package root is tests/ (parent of contracts/)
    tests_root = CONTRACTS_DIR.parent
    modules: list[str] = []
    for info in pkgutil.walk_packages(
        path=[str(CONTRACTS_DIR)],
        prefix="tests.contracts.",
    ):
        modules.append(info.name)
    return sorted(modules)


@pytest.mark.contract
class TestImportSafety:
    """All contract test modules must import without errors."""

    def test_all_contract_modules_import(self):
        """Every .py under tests/contracts/ must be importable.

        Catches stale imports (e.g. model renames that break skipped tests)
        even in skipped test files.
        """
        modules = _discover_test_modules()
        assert len(modules) > 0, "No contract test modules discovered"

        failures: list[str] = []
        for mod_name in modules:
            try:
                importlib.import_module(mod_name)
            except Exception as exc:
                failures.append(f"{mod_name}: {exc}")

        assert not failures, (
            f"{len(failures)} contract module(s) failed to import:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )


# ---------------------------------------------------------------------------
# (b) CRITICAL API PRESENCE — contract-facing functions must exist
# ---------------------------------------------------------------------------

# Each entry: (module_path, function_name, contract_ref)
_CRITICAL_APIS = [
    (
        "retrovue.runtime.traffic_manager",
        "_build_filler_segments",
        "docs/contracts/filler_alignment.md",
    ),
    (
        "retrovue.runtime.traffic_manager",
        "fill_ad_blocks",
        "docs/contracts/traffic_manager.md",
    ),
    (
        "retrovue.runtime.program_assembly",
        "assemble_schedule_block",
        "docs/contracts/channel_dsl.md",
    ),
]


@pytest.mark.contract
class TestCriticalApiPresence:
    """Contract-driven APIs must remain importable and callable."""

    @pytest.mark.parametrize(
        "module_path,func_name,contract_ref",
        _CRITICAL_APIS,
        ids=[f"{m}.{f}" for m, f, _ in _CRITICAL_APIS],
    )
    def test_api_exists_and_callable(self, module_path, func_name, contract_ref):
        mod = importlib.import_module(module_path)
        obj = getattr(mod, func_name, None)
        assert obj is not None, (
            f"{module_path}.{func_name} not found — "
            f"required by contract {contract_ref}"
        )
        assert callable(obj), (
            f"{module_path}.{func_name} exists but is not callable"
        )


# ---------------------------------------------------------------------------
# (c) ROOT PYTEST COMPATIBILITY — sys.path includes server
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestRootPytestCompat:
    """Validates that sys.path is configured for repo-root invocation."""

    def test_pkg_core_on_sys_path(self):
        """server must be on sys.path so 'from tests.contracts...' resolves."""
        pkg_core = str(Path(__file__).resolve().parents[2])
        assert pkg_core in sys.path, (
            f"server ({pkg_core}) not in sys.path — "
            f"tests will fail when pytest runs from repo root"
        )

    def test_tests_contracts_utils_importable(self):
        """The shared test utils package must be importable."""
        mod = importlib.import_module("tests.contracts.utils")
        assert hasattr(mod, "assert_contains_fields"), (
            "tests.contracts.utils.assert_contains_fields not found"
        )
