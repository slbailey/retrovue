"""
INV-WATCH-DELEGATES-001 — Watch CLI delegates to workflow.

Contract requirements:
- The `retrovue source watch` CLI command MUST delegate all business logic
  to `SourceWatchService` in the workflow layer.
- The CLI command MUST NOT import `watchdog`, `SourceIngestService`, or
  threading/timer primitives.
- `SourceWatchService` MUST reside in the `workflows/` package.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

import ast
import importlib
import inspect
from pathlib import Path

import pytest


def _get_source_cli_path() -> Path:
    """Return the filesystem path to source.py CLI module."""
    import retrovue.cli.commands.source as source_mod
    return Path(inspect.getfile(source_mod))


def _get_source_cli_imports() -> set[str]:
    """Parse the source.py CLI module AST and extract all module-level imported names."""
    source_path = _get_source_cli_path()
    tree = ast.parse(source_path.read_text())
    imports: set[str] = set()
    # Only check module-level imports (not inside function bodies)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
            for alias in node.names:
                imports.add(alias.name)
    return imports


def _get_watch_function_imports() -> set[str]:
    """Parse imports inside the source_watch CLI function only."""
    source_path = _get_source_cli_path()
    tree = ast.parse(source_path.read_text())
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "source_watch":
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        imports.add(alias.name)
                elif isinstance(child, ast.ImportFrom):
                    if child.module:
                        imports.add(child.module)
                    for alias in child.names:
                        imports.add(alias.name)
    return imports


class TestInvWatchDelegates001:
    """Contract tests for INV-WATCH-DELEGATES-001."""

    def test_twd_001_no_watchdog_import(self):
        """source_watch function does not import watchdog."""
        all_imports = _get_source_cli_imports() | _get_watch_function_imports()
        watchdog_imports = {i for i in all_imports if "watchdog" in i}
        assert not watchdog_imports, (
            f"source.py imports watchdog modules {watchdog_imports} — "
            "watch business logic MUST live in SourceWatchService, not CLI"
        )

    def test_twd_002_no_ingest_service_import(self):
        """source_watch function does not import SourceIngestService."""
        imports = _get_watch_function_imports()
        assert "SourceIngestService" not in imports, (
            "source_watch function imports SourceIngestService — watch CLI MUST delegate "
            "ingest orchestration to SourceWatchService"
        )

    def test_twd_003_no_timer_import(self):
        """source_watch function does not import threading/timer primitives."""
        forbidden = {"threading", "asyncio", "Timer", "Event", "Thread"}
        all_imports = _get_source_cli_imports() | _get_watch_function_imports()
        violations = all_imports & forbidden
        assert not violations, (
            f"source.py imports timer/thread primitives {violations} — "
            "debounce logic MUST live in SourceWatchService"
        )

    def test_twd_004_delegates_to_workflow(self):
        """Watch CLI command calls SourceWatchService workflow entry point."""
        all_imports = _get_source_cli_imports() | _get_watch_function_imports()
        has_watch_import = any(
            "source_watch" in i or "SourceWatchService" in i
            for i in all_imports
        )
        assert has_watch_import, (
            "source.py does not import SourceWatchService or source_watch — "
            "watch command MUST delegate to workflow layer"
        )

    def test_twd_005_service_in_workflows(self):
        """SourceWatchService resides in workflows/ package."""
        from retrovue.workflows.source_watch import SourceWatchService  # noqa: F401

        mod = importlib.import_module("retrovue.workflows.source_watch")
        mod_path = Path(inspect.getfile(mod))
        assert "workflows" in mod_path.parts, (
            f"SourceWatchService found at {mod_path} — MUST be in workflows/ package"
        )
