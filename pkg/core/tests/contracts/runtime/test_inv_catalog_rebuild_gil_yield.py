"""Contract tests for INV-CATALOG-REBUILD-GIL-YIELD-001.

CatalogAssetResolver._load() MUST periodically yield the GIL during
the asset-processing loop so that the upstream reader thread is not
starved during concurrent catalog rebuilds.

Rules:
1. _load() MUST call time.sleep(>=0.010) periodically inside the
   asset-processing loop.
2. The yield MUST be conditional — executed only at batch boundaries,
   not on every iteration.
3. The yield MUST execute multiple times during a large rebuild so that
   no single GIL-held stretch exceeds the upstream reader's select
   timeout.
"""

import ast
import inspect
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Rule 1: time.sleep(>=0.010) exists in _load()
# ---------------------------------------------------------------------------

class TestRule1SleepExists:
    """Rule 1: _load() MUST contain time.sleep(>=0.010)."""

    def test_sleep_present_with_sufficient_duration(self):
        """AST scan: _load() MUST contain at least one time.sleep() call
        with an argument >= 0.010 (10ms minimum GIL yield)."""
        from retrovue.runtime.catalog_resolver import CatalogAssetResolver

        source = textwrap.dedent(inspect.getsource(CatalogAssetResolver._load))
        tree = ast.parse(source)

        sleep_args = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "sleep":
                if node.args and isinstance(node.args[0], ast.Constant):
                    sleep_args.append(node.args[0].value)

        assert sleep_args, (
            "INV-CATALOG-REBUILD-GIL-YIELD-001 Rule 1: "
            "no time.sleep() calls found in CatalogAssetResolver._load()"
        )

        MIN_YIELD_S = 0.010
        for val in sleep_args:
            assert val >= MIN_YIELD_S, (
                f"INV-CATALOG-REBUILD-GIL-YIELD-001 Rule 1: "
                f"time.sleep({val}) is insufficient. "
                f"Minimum yield MUST be >= {MIN_YIELD_S}s (10ms) "
                f"to prevent upstream reader starvation."
            )


# ---------------------------------------------------------------------------
# Rule 2: yield is inside a loop AND guarded by a conditional
# ---------------------------------------------------------------------------

class TestRule2ConditionalInsideLoop:
    """Rule 2: The time.sleep() yield MUST be inside a loop node and
    guarded by a conditional (batch/modulo check)."""

    def test_sleep_nested_in_loop(self):
        """AST structural: time.sleep() MUST be nested inside a For or
        While node within _load()."""
        from retrovue.runtime.catalog_resolver import CatalogAssetResolver

        source = textwrap.dedent(inspect.getsource(CatalogAssetResolver._load))
        tree = ast.parse(source)

        def _find_sleep_in_loop(node, in_loop=False):
            """Walk the AST and return True if a time.sleep() call is
            found inside a loop body."""
            if isinstance(node, (ast.For, ast.While)):
                in_loop = True
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "sleep":
                    if in_loop:
                        return True
            for child in ast.iter_child_nodes(node):
                if _find_sleep_in_loop(child, in_loop):
                    return True
            return False

        assert _find_sleep_in_loop(tree), (
            "INV-CATALOG-REBUILD-GIL-YIELD-001 Rule 2: "
            "time.sleep() in _load() is NOT inside a loop node. "
            "The yield MUST occur inside the asset-processing loop."
        )

    def test_sleep_guarded_by_conditional(self):
        """AST structural: time.sleep() inside the loop MUST be guarded
        by an If node (batch boundary check), not called unconditionally
        on every iteration."""
        from retrovue.runtime.catalog_resolver import CatalogAssetResolver

        source = textwrap.dedent(inspect.getsource(CatalogAssetResolver._load))
        tree = ast.parse(source)

        def _find_sleep_in_if_in_loop(node, in_loop=False, in_if=False):
            """Walk the AST and return True if a time.sleep() call is
            found inside an If node that is itself inside a loop."""
            if isinstance(node, (ast.For, ast.While)):
                in_loop = True
            if isinstance(node, ast.If) and in_loop:
                in_if = True
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "sleep":
                    if in_loop and in_if:
                        return True
            for child in ast.iter_child_nodes(node):
                if _find_sleep_in_if_in_loop(child, in_loop, in_if):
                    return True
            return False

        assert _find_sleep_in_if_in_loop(tree), (
            "INV-CATALOG-REBUILD-GIL-YIELD-001 Rule 2: "
            "time.sleep() in _load() is NOT guarded by a conditional "
            "inside the loop. The yield MUST be conditional (batch "
            "boundary check) — not called on every iteration."
        )
