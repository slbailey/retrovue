"""
Contract tests for INV-HLS-PHANTOM-CLEANUP-001.

HLS phantom viewers MUST be cleaned up when channel startup fails.
Failed HLS responses (non-200) MUST NOT refresh the phantom viewer's
activity timestamp.

Tests use AST scanning of the handler source to verify structural
properties — the same pattern used by INV-CHANNEL-STARTUP-CONCURRENCY-001.
"""

import ast
import inspect
import textwrap

import pytest


def _get_register_endpoints_source():
    """Get the full source of _register_endpoints for nested function scanning."""
    from retrovue.runtime.program_director import ProgramDirector

    method = getattr(ProgramDirector, "_register_endpoints")
    return textwrap.dedent(inspect.getsource(method))


def _extract_nested_function(parent_source: str, func_name: str) -> ast.AsyncFunctionDef | ast.FunctionDef | None:
    """Extract the AST node of a nested function definition."""
    tree = ast.parse(parent_source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node
    return None


def _extract_nested_function_source(parent_source: str, func_name: str) -> str | None:
    """Extract the dedented source lines of a nested function."""
    node = _extract_nested_function(parent_source, func_name)
    if node is None:
        return None
    lines = parent_source.splitlines()
    raw = "\n".join(lines[node.lineno - 1 : node.end_lineno])
    return textwrap.dedent(raw)


def _find_assignments_to_subscript(tree: ast.AST, dict_name: str) -> list[int]:
    """Find line numbers where self.<dict_name>[...] = ... appears.

    Detects:
        self._hls_last_activity[channel_id] = ...
    """
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            val = target.value
            if (
                isinstance(val, ast.Attribute)
                and val.attr == dict_name
                and isinstance(val.value, ast.Name)
                and val.value.id == "self"
            ):
                lines.append(node.lineno)
    return lines


def _find_method_calls(tree: ast.AST, method_name: str) -> list[int]:
    """Find line numbers of calls to .<method_name>() anywhere in the tree."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == method_name:
                lines.append(node.lineno)
    return lines


def _find_attr_method_calls(tree: ast.AST, attr: str, method: str) -> list[int]:
    """Find line numbers of calls like self.<attr>.<method>(...) or <var>.<method>(...)."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == method:
                lines.append(node.lineno)
    return lines


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvHlsPhantomCleanup:
    """INV-HLS-PHANTOM-CLEANUP-001 contract tests."""

    def test_hls_playlist_no_unconditional_activity_update(self):
        """hls_playlist() MUST NOT unconditionally update _hls_last_activity.

        An _hls_last_activity assignment in the top-level body of
        hls_playlist() (outside any if/with/for block) would fire on
        every request — including 503 failures — preventing the phantom
        drain thread from ever detecting idle timeout.

        Allowed: activity set inside `if not seg.is_running()` (initial
        baseline during phantom creation), and after the success check.
        """
        parent_src = _get_register_endpoints_source()
        func_node = _extract_nested_function(parent_src, "hls_playlist")
        assert func_node is not None, "hls_playlist() not found"

        func_src = _extract_nested_function_source(parent_src, "hls_playlist")
        func_tree = ast.parse(func_src)

        # Walk only the TOP-LEVEL statements of the function body
        # (not nested inside if/for/with/try blocks).
        func_body = func_tree.body[0].body  # AsyncFunctionDef -> body

        top_level_activity_updates = []
        for stmt in func_body:
            # Check direct Assign at top level
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "_hls_last_activity"
                    ):
                        top_level_activity_updates.append(stmt.lineno)
            # Check With blocks at top level — these are unconditional too
            # (a `with lock:` followed by an assignment still runs every call)
            if isinstance(stmt, ast.With):
                for inner in stmt.body:
                    if isinstance(inner, ast.Assign):
                        for target in inner.targets:
                            if (
                                isinstance(target, ast.Subscript)
                                and isinstance(target.value, ast.Attribute)
                                and target.value.attr == "_hls_last_activity"
                            ):
                                top_level_activity_updates.append(inner.lineno)

        # Find the get_playlist() call line (success check)
        get_playlist_lines = _find_method_calls(func_tree, "get_playlist")
        assert get_playlist_lines, "hls_playlist() has no get_playlist() call"
        first_get_playlist = min(get_playlist_lines)

        # Top-level activity updates BEFORE get_playlist() are the bug:
        # they fire on every request unconditionally.
        # Top-level activity updates AFTER get_playlist() are correct:
        # they only execute when returning a 200.
        early_unconditional = [
            ln for ln in top_level_activity_updates
            if ln < first_get_playlist
        ]
        assert not early_unconditional, (
            f"INV-HLS-PHANTOM-CLEANUP-001 violated: _hls_last_activity "
            f"unconditionally updated at top-level line(s) "
            f"{early_unconditional} — BEFORE get_playlist() at line "
            f"{first_get_playlist}. Every 503 retry refreshes the "
            f"timestamp, preventing phantom idle timeout."
        )

    def test_hls_segment_no_early_activity_update(self):
        """hls_segment() MUST NOT update _hls_last_activity before the
        success path (get_segment() returning data).
        """
        parent_src = _get_register_endpoints_source()
        func_src = _extract_nested_function_source(parent_src, "hls_segment")
        assert func_src is not None, "hls_segment() not found"

        func_tree = ast.parse(func_src)

        activity_lines = _find_assignments_to_subscript(func_tree, "_hls_last_activity")
        assert activity_lines, (
            "hls_segment() has no _hls_last_activity assignment"
        )

        get_segment_lines = _find_method_calls(func_tree, "get_segment")
        assert get_segment_lines, "hls_segment() has no get_segment() call"

        first_get_segment = min(get_segment_lines)

        early_updates = [ln for ln in activity_lines if ln < first_get_segment]
        assert not early_updates, (
            f"INV-HLS-PHANTOM-CLEANUP-001 violated: _hls_last_activity "
            f"updated at line(s) {early_updates} in hls_segment() — "
            f"BEFORE get_segment() at line {first_get_segment}."
        )

    def test_hls_playlist_cleans_up_on_startup_failure(self):
        """hls_playlist() MUST call seg.stop() when startup fails (no fanout).

        Regression: before the fix, a failed startup left the segmenter in
        is_running()==True state, preventing all future startup attempts.
        The handler's startup-needed branch (if not seg.is_running()) was
        never re-entered, so the channel returned 503 forever.
        """
        parent_src = _get_register_endpoints_source()
        func_src = _extract_nested_function_source(parent_src, "hls_playlist")
        assert func_src is not None, "hls_playlist() not found"

        # The handler must contain seg.stop() — cleanup of zombie segmenter
        assert ".stop()" in func_src, (
            "INV-HLS-PHANTOM-CLEANUP-001 violated: hls_playlist() has no "
            "seg.stop() call — failed startup leaves zombie segmenter "
            "that blocks all future startup attempts"
        )

    def test_hls_playlist_cleans_up_phantom_session_on_failure(self):
        """hls_playlist() MUST remove the phantom session from
        _hls_phantom_sessions when startup fails.

        Regression: the phantom session dict entry was written during
        startup setup but never removed on the failure path.
        """
        parent_src = _get_register_endpoints_source()
        func_src = _extract_nested_function_source(parent_src, "hls_playlist")
        assert func_src is not None, "hls_playlist() not found"

        func_tree = ast.parse(func_src)

        # Must contain _hls_phantom_sessions.pop() for cleanup
        pop_lines = _find_attr_method_calls(func_tree, "_hls_phantom_sessions", "pop")
        assert pop_lines, (
            "INV-HLS-PHANTOM-CLEANUP-001 violated: hls_playlist() never "
            "calls _hls_phantom_sessions.pop() — phantom session leaked "
            "on startup failure"
        )

    def test_hls_playlist_sets_initial_activity_during_phantom_creation(self):
        """hls_playlist() MUST set _hls_last_activity when creating a phantom,
        so the drain thread has a valid initial baseline.

        Without this, the drain thread reads _hls_last_activity.get(cid, 0)
        which returns epoch 0, computing an enormous idle_seconds that
        immediately triggers phantom teardown — before the segmenter even
        has time to produce its first segment.
        """
        parent_src = _get_register_endpoints_source()
        func_src = _extract_nested_function_source(parent_src, "hls_playlist")
        assert func_src is not None, "hls_playlist() not found"

        func_tree = ast.parse(func_src)

        # Find _hls_last_activity assignments
        activity_lines = _find_assignments_to_subscript(func_tree, "_hls_last_activity")

        # Find _hls_phantom_sessions assignments (where phantom is created)
        phantom_lines = _find_assignments_to_subscript(func_tree, "_hls_phantom_sessions")
        assert phantom_lines, "No _hls_phantom_sessions assignment found"

        phantom_creation_line = min(phantom_lines)

        # At least one activity assignment must be near (within 5 lines of)
        # the phantom creation — this is the initial baseline
        nearby = [
            ln for ln in activity_lines
            if abs(ln - phantom_creation_line) <= 5
        ]
        assert nearby, (
            "INV-HLS-PHANTOM-CLEANUP-001 violated: _hls_last_activity "
            "is not set near phantom creation (line %d). The drain "
            "thread will have no valid baseline and may tear down "
            "the phantom immediately." % phantom_creation_line
        )
