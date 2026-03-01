"""
Contract tests for INV-SCHEDULE-PREWARM-001.

All EPG horizon building and multi-day DSL compilation MUST be performed
by the scheduler daemon. _get_or_create_manager() and _get_dsl_service()
MUST NOT invoke load_schedule() or _build_initial(). A dedicated prewarm
method MUST exist and MUST call load_schedule().
"""

import ast
import inspect
import textwrap

import pytest


def _get_method_source(cls, method_name: str) -> str:
    """Get dedented source code of a method for AST analysis."""
    method = getattr(cls, method_name)
    return textwrap.dedent(inspect.getsource(method))


def _find_calls_in_source(source: str, call_names: set[str]) -> list[str]:
    """Find all function/method calls in source that match any of call_names.

    Returns list of matched call names found.
    """
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # method call: obj.method_name(...)
            if isinstance(func, ast.Attribute) and func.attr in call_names:
                found.append(func.attr)
            # bare function call: method_name(...)
            elif isinstance(func, ast.Name) and func.id in call_names:
                found.append(func.id)
    return found


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvSchedulePrewarm001:
    """INV-SCHEDULE-PREWARM-001 contract tests."""

    def test_get_or_create_manager_no_load_schedule(self):
        """_get_or_create_manager() MUST NOT call load_schedule() or _build_initial().

        AST scan of method source proves no compilation is triggered
        on the viewer-join code path.
        """
        from retrovue.runtime.program_director import ProgramDirector

        source = _get_method_source(ProgramDirector, "_get_or_create_manager")
        forbidden = {"load_schedule", "_build_initial"}
        violations = _find_calls_in_source(source, forbidden)

        assert violations == [], (
            f"INV-SCHEDULE-PREWARM-001 violated: _get_or_create_manager() "
            f"calls {violations!r} — schedule compilation on viewer-join path"
        )

    def test_get_dsl_service_no_load_schedule(self):
        """_get_dsl_service() MUST NOT call load_schedule() or _build_initial().

        DSL service creation must be decoupled from schedule compilation.
        The scheduler daemon owns compilation via _prewarm_channel_schedules().
        """
        from retrovue.runtime.program_director import ProgramDirector

        source = _get_method_source(ProgramDirector, "_get_dsl_service")
        forbidden = {"load_schedule", "_build_initial"}
        violations = _find_calls_in_source(source, forbidden)

        assert violations == [], (
            f"INV-SCHEDULE-PREWARM-001 violated: _get_dsl_service() "
            f"calls {violations!r} — schedule compilation in service factory"
        )

    def test_prewarm_method_calls_load_schedule(self):
        """_prewarm_channel_schedules() MUST exist and MUST call load_schedule().

        The scheduler daemon startup path is the sole authority for
        schedule compilation. This test verifies the prewarm method
        exists and performs compilation.
        """
        from retrovue.runtime.program_director import ProgramDirector

        assert hasattr(ProgramDirector, "_prewarm_channel_schedules"), (
            "INV-SCHEDULE-PREWARM-001: ProgramDirector missing "
            "_prewarm_channel_schedules() method"
        )

        source = _get_method_source(ProgramDirector, "_prewarm_channel_schedules")
        required = {"load_schedule"}
        found = _find_calls_in_source(source, required)

        assert "load_schedule" in found, (
            "INV-SCHEDULE-PREWARM-001: _prewarm_channel_schedules() "
            "does not call load_schedule() — no compilation at startup"
        )
