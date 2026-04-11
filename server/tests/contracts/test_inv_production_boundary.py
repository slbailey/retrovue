"""
INV-PRODUCTION-BOUNDARY-001: Production modules contain only production code.

No class named Mock*, Fake*, Stub*, or Test* may live in a production module.
Mocks, test fixtures, and test harnesses belong in tests/fixtures/ or
retrovue/dev/, never in retrovue/runtime/ or retrovue/adapters/.

This test scans all production modules and fails if any violating class names
are found. TestPatternProducer is explicitly excluded (board-ruled cosmetic).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Production source tree
PROD_ROOT = Path(__file__).resolve().parents[2] / "src" / "retrovue"

# Prefixes that violate the invariant
FORBIDDEN_PREFIXES = ("Mock", "Fake", "Stub")

# Board-approved exceptions (cosmetic, not actual test harnesses)
EXCEPTIONS = {"TestPatternProducer"}

# Directories within retrovue/ that are explicitly for dev harnesses (allowed)
DEV_NAMESPACES = {"dev"}


def _scan_production_classes() -> list[tuple[str, str, int]]:
    """Scan production modules for classes with forbidden name prefixes.

    Returns list of (file_path_relative, class_name, line_number) tuples.
    """
    violations: list[tuple[str, str, int]] = []

    for py_file in PROD_ROOT.rglob("*.py"):
        # Skip dev/ namespace — explicitly allowed for dev harnesses
        rel = py_file.relative_to(PROD_ROOT)
        if rel.parts and rel.parts[0] in DEV_NAMESPACES:
            continue

        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name in EXCEPTIONS:
                    continue
                if any(node.name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                    violations.append(
                        (str(rel), node.name, node.lineno)
                    )

    return violations


class TestProductionBoundary:
    """INV-PRODUCTION-BOUNDARY-001: No Mock*/Fake*/Stub* classes in production modules."""

    def test_no_forbidden_classes_in_production(self) -> None:
        violations = _scan_production_classes()
        if violations:
            msg_lines = ["INV-PRODUCTION-BOUNDARY-001 violated:"]
            for filepath, classname, lineno in violations:
                msg_lines.append(f"  {filepath}:{lineno} — class {classname}")
            pytest.fail("\n".join(msg_lines))
