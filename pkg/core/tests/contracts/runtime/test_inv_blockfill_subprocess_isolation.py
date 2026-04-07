"""Contract tests for INV-BLOCKFILL-SUBPROCESS-ISOLATION-001.

PlaylistBuilderDaemon._extend_to_target() MUST execute block expansion
in a subprocess for memory isolation.

Rules:
1. _extend_to_target() MUST NOT call expand_editorial_block directly.
   Expansion MUST be delegated to a subprocess.
2. ProcessPoolExecutor (or equivalent) MUST use max_tasks_per_child=1
   to guarantee process-per-batch isolation.
"""

import ast
import inspect
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_extend_source():
    from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon
    source = inspect.getsource(PlaylistBuilderDaemon._extend_to_target)
    return textwrap.dedent(source)


def _get_extend_ast():
    return ast.parse(_get_extend_source())


# ---------------------------------------------------------------------------
# SUBPROCESS-ISOLATION-001: No direct expand_editorial_block call
# ---------------------------------------------------------------------------

class TestSubprocessIsolation001:
    """_extend_to_target MUST NOT call expand_editorial_block in-process."""

    def test_no_direct_expand_call(self):
        """AST scan: expand_editorial_block MUST NOT appear as a direct
        function call within _extend_to_target body."""
        tree = _get_extend_ast()
        direct_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for bare name call: expand_editorial_block(...)
                if isinstance(node.func, ast.Name) and node.func.id == "expand_editorial_block":
                    direct_calls.append(node.lineno)
                # Check for attribute call: module.expand_editorial_block(...)
                if isinstance(node.func, ast.Attribute) and node.func.attr == "expand_editorial_block":
                    direct_calls.append(node.lineno)
        assert not direct_calls, (
            f"INV-BLOCKFILL-SUBPROCESS-ISOLATION-001 VIOLATION: "
            f"_extend_to_target calls expand_editorial_block directly "
            f"at line(s) {direct_calls}. Expansion MUST run in a subprocess."
        )

    def test_subprocess_dispatch_present(self):
        """_extend_to_target MUST contain ProcessPoolExecutor or
        multiprocessing.Process dispatch."""
        source = _get_extend_source()
        has_pool_executor = "ProcessPoolExecutor" in source
        has_mp_process = "multiprocessing.Process" in source
        has_subprocess_call = has_pool_executor or has_mp_process
        assert has_subprocess_call, (
            "INV-BLOCKFILL-SUBPROCESS-ISOLATION-001 VIOLATION: "
            "_extend_to_target does not use ProcessPoolExecutor or "
            "multiprocessing.Process for subprocess dispatch."
        )


# ---------------------------------------------------------------------------
# SUBPROCESS-ISOLATION-002: max_tasks_per_child=1
# ---------------------------------------------------------------------------

class TestSubprocessIsolation002:
    """ProcessPoolExecutor MUST use max_tasks_per_child=1."""

    def test_max_tasks_per_child_set(self):
        """AST scan: ProcessPoolExecutor constructor MUST include
        max_tasks_per_child=1 keyword argument."""
        tree = _get_extend_ast()
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Match ProcessPoolExecutor(...)
            func = node.func
            is_ppe = (
                (isinstance(func, ast.Name) and func.id == "ProcessPoolExecutor")
                or (isinstance(func, ast.Attribute) and func.attr == "ProcessPoolExecutor")
            )
            if not is_ppe:
                continue
            for kw in node.keywords:
                if kw.arg == "max_tasks_per_child":
                    if isinstance(kw.value, ast.Constant) and kw.value.value == 1:
                        found = True
        assert found, (
            "INV-BLOCKFILL-SUBPROCESS-ISOLATION-001 VIOLATION: "
            "ProcessPoolExecutor MUST be constructed with "
            "max_tasks_per_child=1 to guarantee process-per-batch isolation."
        )
