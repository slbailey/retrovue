"""
Contract test: INV-CRUD-ISLAND-RETIRED-001

Enforces that the retired CRUD island entities (SchedulePlan, Zone, Program,
SchedulePlanLabel) are not imported by any production module. The DSL +
ScheduleRevision/ScheduleItem path is the sole scheduling authority per
RETA-88 Option B.
"""

import ast
import pathlib

import pytest

PRODUCTION_ROOT = pathlib.Path(__file__).resolve().parents[3] / "src" / "retrovue"

RETIRED_NAMES = frozenset({"SchedulePlan", "Zone", "Program", "SchedulePlanLabel"})

# Zone is also used as a timezone concept; only flag imports from domain.entities
ENTITIES_MODULE_FRAGMENTS = ("domain.entities", "entities")


def _production_python_files():
    """Yield all .py files under the production source tree."""
    for p in PRODUCTION_ROOT.rglob("*.py"):
        # Skip __pycache__
        if "__pycache__" in p.parts:
            continue
        yield p


def _imports_retired_entity(filepath: pathlib.Path) -> list[str]:
    """Return list of retired entity names imported from domain.entities in *filepath*."""
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return []

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and any(
                frag in node.module for frag in ENTITIES_MODULE_FRAGMENTS
            ):
                for alias in node.names:
                    name = alias.name
                    if name in RETIRED_NAMES:
                        violations.append(name)
    return violations


def test_no_production_module_imports_retired_crud_entities():
    """INV-CRUD-ISLAND-RETIRED-001: no production module imports retired entities."""
    all_violations: dict[str, list[str]] = {}
    for filepath in _production_python_files():
        violations = _imports_retired_entity(filepath)
        if violations:
            rel = filepath.relative_to(PRODUCTION_ROOT)
            all_violations[str(rel)] = violations

    assert all_violations == {}, (
        f"Production modules still import retired CRUD island entities:\n"
        + "\n".join(
            f"  {path}: {', '.join(names)}"
            for path, names in sorted(all_violations.items())
        )
    )
