"""Contract tests for INV-TIER2-EXPANSION-CANONICAL-001.

All Tier-2 writers MUST call expand_editorial_block() with asset_library.
Omitting asset_library causes silent fallback to static filler instead of
real interstitials from the channel's traffic configuration.

Rules:
1. rebuild_tier2() MUST pass asset_library to expand_editorial_block().
2. PlaylistBuilderDaemon._extend_to_target() MUST pass asset_library to
   expand_editorial_block().
3. Both writers MUST produce identical Tier-2 output for the same input.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_expand_editorial_block_calls(source: str) -> list[dict]:
    """Find all calls to expand_editorial_block in source and return their kwargs."""
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match: expand_editorial_block(...) — direct call
        if isinstance(func, ast.Name) and func.id == "expand_editorial_block":
            kw_names = [kw.arg for kw in node.keywords]
            calls.append({"line": node.lineno, "kwargs": kw_names})
        # Match: self.expand_editorial_block(...) or module.expand_editorial_block(...)
        elif isinstance(func, ast.Attribute) and func.attr == "expand_editorial_block":
            kw_names = [kw.arg for kw in node.keywords]
            calls.append({"line": node.lineno, "kwargs": kw_names})
    return calls


# ---------------------------------------------------------------------------
# Rule 1: rebuild_tier2 MUST pass asset_library
# ---------------------------------------------------------------------------

class TestRule1RebuildPassesAssetLibrary:
    """Rule 1: rebuild_tier2() MUST pass asset_library to expand_editorial_block()."""

    def test_rebuild_tier2_passes_asset_library(self):
        """Inspect rebuild_tier2 source to verify expand_editorial_block()
        is called with asset_library keyword argument.

        VIOLATION: rebuild_tier2() calls expand_editorial_block() with only
        filler_uri and filler_duration_ms, omitting asset_library. This causes
        fill_ad_blocks() to fall back to static filler.mp4 instead of using
        real interstitials from the DatabaseAssetLibrary.
        """
        from retrovue.usecases.schedule_rebuild import rebuild_tier2

        source = textwrap.dedent(inspect.getsource(rebuild_tier2))
        calls = _find_expand_editorial_block_calls(source)

        assert calls, (
            "INV-TIER2-EXPANSION-CANONICAL-001 Rule 1: "
            "rebuild_tier2() does not call expand_editorial_block() at all."
        )

        for call in calls:
            assert "asset_library" in call["kwargs"], (
                f"INV-TIER2-EXPANSION-CANONICAL-001 Rule 1: "
                f"rebuild_tier2() calls expand_editorial_block() at line {call['line']} "
                f"WITHOUT asset_library kwarg. Found kwargs: {call['kwargs']}. "
                f"All Tier-2 writers MUST pass asset_library to prevent "
                f"silent fallback to static filler."
            )


# ---------------------------------------------------------------------------
# Rule 2: daemon _extend_to_target MUST pass asset_library
# ---------------------------------------------------------------------------

class TestRule2DaemonPassesAssetLibrary:
    """Rule 2: _extend_to_target() MUST pass asset_library to expand_editorial_block()."""

    def test_extend_to_target_passes_asset_library(self):
        """Inspect _extend_to_target source to verify expand_editorial_block()
        is called with asset_library keyword argument."""
        from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon

        source = textwrap.dedent(
            inspect.getsource(PlaylistBuilderDaemon._extend_to_target)
        )
        calls = _find_expand_editorial_block_calls(source)

        assert calls, (
            "INV-TIER2-EXPANSION-CANONICAL-001 Rule 2: "
            "_extend_to_target() does not call expand_editorial_block() at all."
        )

        for call in calls:
            assert "asset_library" in call["kwargs"], (
                f"INV-TIER2-EXPANSION-CANONICAL-001 Rule 2: "
                f"_extend_to_target() calls expand_editorial_block() at line {call['line']} "
                f"WITHOUT asset_library kwarg. Found kwargs: {call['kwargs']}. "
                f"All Tier-2 writers MUST pass asset_library."
            )


# ---------------------------------------------------------------------------
# Rule 3: equivalence — both writers produce same output for same input
# ---------------------------------------------------------------------------

class TestRule3ExpansionEquivalence:
    """Rule 3: rebuild and daemon MUST produce identical Tier-2 for same input."""

    def test_both_writers_use_same_function(self):
        """Both rebuild_tier2 and daemon MUST import expand_editorial_block
        from the same module (retrovue.runtime.schedule_items_reader)."""
        import retrovue.usecases.schedule_rebuild as rebuild_mod
        import retrovue.runtime.playlist_builder_daemon as daemon_mod

        # Both modules must reference the same function object
        rebuild_fn = getattr(rebuild_mod, "expand_editorial_block", None)
        daemon_fn = getattr(daemon_mod, "expand_editorial_block", None)

        assert rebuild_fn is not None, (
            "INV-TIER2-EXPANSION-CANONICAL-001 Rule 3: "
            "rebuild module does not import expand_editorial_block."
        )
        assert daemon_fn is not None, (
            "INV-TIER2-EXPANSION-CANONICAL-001 Rule 3: "
            "daemon module does not import expand_editorial_block."
        )
        assert rebuild_fn is daemon_fn, (
            "INV-TIER2-EXPANSION-CANONICAL-001 Rule 3: "
            "rebuild and daemon import different expand_editorial_block functions. "
            "Both MUST use the canonical function from schedule_items_reader."
        )
