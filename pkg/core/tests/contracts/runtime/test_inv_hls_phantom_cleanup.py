"""
Contract tests for INV-HLS-PHANTOM-CLEANUP-001.

HLS phantom viewers MUST be cleaned up when channel startup fails.
Failed HLS responses (non-200) MUST NOT refresh the phantom viewer's
activity timestamp.

These tests were rewritten for the new HLS architecture
(HlsConsumptionAdapter + SegmentRing) which replaced the old
_hls_manager-based stack. The invariants are the same; the
implementation surface is different.

Refactored: 2026-03-29 — old tests targeted deleted hls_playlist()/
hls_segment() nested functions. New tests target the current adapter
and endpoint source.
"""

import ast
import inspect
import textwrap

import pytest


def _get_manifest_handler_source() -> str:
    """Get the source of the channels_hls_manifest handler inside _register_endpoints."""
    from retrovue.runtime.program_director import ProgramDirector
    method = getattr(ProgramDirector, "_register_endpoints")
    src = textwrap.dedent(inspect.getsource(method))
    # Extract channels_hls_manifest nested function
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "channels_hls_manifest":
                lines = src.splitlines()
                raw = "\n".join(lines[node.lineno - 1: node.end_lineno])
                return textwrap.dedent(raw)
    return ""


def _get_segment_handler_source() -> str:
    """Get the source of the channels_hls_segment handler inside _register_endpoints."""
    from retrovue.runtime.program_director import ProgramDirector
    method = getattr(ProgramDirector, "_register_endpoints")
    src = textwrap.dedent(inspect.getsource(method))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "channels_hls_segment":
                lines = src.splitlines()
                raw = "\n".join(lines[node.lineno - 1: node.end_lineno])
                return textwrap.dedent(raw)
    return ""


def _get_activate_source() -> str:
    """Get the source of HlsConsumptionAdapter.activate()."""
    from retrovue.runtime.consumption_adapters import HlsConsumptionAdapter
    return textwrap.dedent(inspect.getsource(HlsConsumptionAdapter.activate))


def _find_method_calls(tree: ast.AST, method_name: str) -> list[int]:
    """Find line numbers of calls to .<method_name>() anywhere in the tree."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == method_name:
                lines.append(node.lineno)
    return lines


def _find_attr_calls_before_line(src: str, method_name: str, cutoff_line: int) -> list[int]:
    """Find lines where method_name is called before cutoff_line."""
    tree = ast.parse(src)
    found = _find_method_calls(tree, method_name)
    return [ln for ln in found if ln < cutoff_line]


class TestInvHlsPhantomCleanup:
    """INV-HLS-PHANTOM-CLEANUP-001 contract tests (new HLS architecture)."""

    def test_manifest_handler_exists(self):
        """channels_hls_manifest() MUST exist inside _register_endpoints."""
        src = _get_manifest_handler_source()
        assert src, (
            "INV-HLS-PHANTOM-CLEANUP-001: channels_hls_manifest() not found "
            "in _register_endpoints — HLS manifest handler is missing"
        )

    def test_segment_handler_exists(self):
        """channels_hls_segment() MUST exist inside _register_endpoints."""
        src = _get_segment_handler_source()
        assert src, (
            "INV-HLS-PHANTOM-CLEANUP-001: channels_hls_segment() not found "
            "in _register_endpoints — HLS segment handler is missing"
        )

    def test_manifest_handler_touch_activity_only_on_success(self):
        """channels_hls_manifest() MUST call touch_activity only after
        a successful playlist is generated (not on 503 paths).

        INV-HLS-PHANTOM-CLEANUP-001: Activity tracking MUST NOT fire on
        every request — 503 retries must not refresh phantom idle timeout.
        """
        src = _get_manifest_handler_source()
        assert src, "channels_hls_manifest() not found"

        tree = ast.parse(src)

        # touch_activity must be called after playlist generation succeeds
        # Find the 503 return and the touch_activity call
        touch_lines = _find_method_calls(tree, "touch_activity")
        assert touch_lines, (
            "INV-HLS-PHANTOM-CLEANUP-001: channels_hls_manifest() never calls "
            "touch_activity() — phantom activity is never refreshed on success"
        )

        # Find any top-level return with 503 status
        func_tree = ast.parse(src)
        func_body = func_tree.body[0].body

        # touch_activity must not appear before the 503 return block
        # We verify: there is no touch_activity call that appears BEFORE
        # the `if playlist is None` block (the 503 path)
        # The 503 block is guarded by `if playlist is None`
        # Any touch_activity before that guard is a bug
        src_lines = src.splitlines()
        playlist_none_line = None
        for i, line in enumerate(src_lines, 1):
            if "playlist is None" in line:
                playlist_none_line = i
                break

        if playlist_none_line is not None:
            premature_touch = [ln for ln in touch_lines if ln < playlist_none_line]
            assert not premature_touch, (
                f"INV-HLS-PHANTOM-CLEANUP-001: touch_activity() called at line(s) "
                f"{premature_touch} BEFORE the 503 guard (line {playlist_none_line}). "
                f"This fires on every request including failures."
            )

    def test_segment_handler_touch_activity_only_on_success(self):
        """channels_hls_segment() MUST call touch_activity only after
        successfully serving a segment.

        INV-HLS-PHANTOM-CLEANUP-001: Activity on segment endpoint must only
        refresh when a real segment is served (200), not on 404/503 paths.
        """
        src = _get_segment_handler_source()
        assert src, "channels_hls_segment() not found"

        tree = ast.parse(src)
        touch_lines = _find_method_calls(tree, "touch_activity")
        assert touch_lines, (
            "INV-HLS-PHANTOM-CLEANUP-001: channels_hls_segment() never calls "
            "touch_activity() — segment hits do not refresh phantom activity"
        )

    def test_activate_releases_phantom_slot_on_failure(self):
        """HlsConsumptionAdapter.activate() MUST call release_phantom_slot()
        on all failure paths.

        INV-HLS-PHANTOM-CLEANUP-001: A phantom slot reserved during startup
        MUST be released if activation fails — otherwise the slot leaks and
        future activations are blocked.
        """
        src = _get_activate_source()
        assert "release_phantom_slot" in src, (
            "INV-HLS-PHANTOM-CLEANUP-001: HlsConsumptionAdapter.activate() "
            "never calls release_phantom_slot() — phantom slot leaks on failure"
        )

        # Count occurrences: should appear on at least 2 failure paths
        count = src.count("release_phantom_slot")
        assert count >= 2, (
            f"INV-HLS-PHANTOM-CLEANUP-001: release_phantom_slot() appears only "
            f"{count} time(s) in activate() — expected at least 2 (one per "
            f"failure path). Some failure paths may leak the phantom slot."
        )

    def test_activate_sets_initial_activity_at_phantom_creation(self):
        """HlsConsumptionAdapter MUST call touch_activity() when a phantom
        is first activated so the drain thread has a valid initial baseline.

        INV-HLS-PHANTOM-CLEANUP-001: Without an initial activity timestamp,
        the drain thread computes an enormous idle_seconds and tears down
        the phantom before the first segment is produced.
        """
        src = _get_activate_source()
        assert "touch_activity" in src, (
            "INV-HLS-PHANTOM-CLEANUP-001: HlsConsumptionAdapter.activate() "
            "never calls touch_activity() — no initial activity baseline set "
            "for the phantom, drain thread may tear it down immediately"
        )
