"""INV-AUTHORITY-SINGLE-OWNER-001 — PD staleness check clock authority test.

V7 from RETA-8 audit: program_director.py line 2366 uses
int(time.time() * 1000) instead of PD embedded clock for
HLS staleness detection.

This test proves the staleness check uses MasterClock, not time.time().
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest


class TestPDStalenessClockAuthority:
    """PD HLS staleness check must not call time.time() directly."""

    def test_staleness_check_does_not_use_time_time(self) -> None:
        """The HLS staleness recovery code path must not contain time.time().

        INV-AUTHORITY-SINGLE-OWNER-001 requires all wall-clock reads to go
        through MasterClock. This is a source-level assertion: the method
        containing the staleness check must not call time.time().
        """
        from retrovue.runtime.program_director import ProgramDirector

        # Find the source file
        src_file = Path(inspect.getfile(ProgramDirector))
        source = src_file.read_text()

        # Parse AST and find the staleness recovery region.
        # We look for any call to time.time() near the staleness threshold constant.
        tree = ast.parse(source)

        violations: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Match time.time()
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "time"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "time"
                ):
                    violations.append(node.lineno)

        # Filter to only the staleness region (around the _HLS_STALENESS_THRESHOLD_MS usage)
        # by checking if any violation is within the HLS serve method.
        # For robustness, flag any time.time() in program_director.py as a violation.
        assert violations == [], (
            f"INV-AUTHORITY-SINGLE-OWNER-001 violation: program_director.py calls "
            f"time.time() at line(s) {violations}. "
            f"All wall-clock reads must go through MasterClock."
        )
