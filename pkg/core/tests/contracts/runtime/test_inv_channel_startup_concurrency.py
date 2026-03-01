"""
Contract tests for INV-CHANNEL-STARTUP-CONCURRENCY-001.

Concurrent channel startup operations MUST be bounded by a global
concurrency semaphore. When at capacity, new startup requests MUST fail
fast (503) rather than queue unboundedly.
"""

import ast
import inspect
import textwrap

import pytest


STARTUP_CAP = 4  # expected concurrency limit


def _get_register_endpoints_source():
    """Get the full source of _register_endpoints for nested function scanning."""
    from retrovue.runtime.program_director import ProgramDirector

    method = getattr(ProgramDirector, "_register_endpoints")
    return textwrap.dedent(inspect.getsource(method))


def _extract_nested_function_source(parent_source: str, func_name: str) -> str | None:
    """Extract the source lines of a nested function definition from parent source.

    Walks the AST of parent_source, finds the FunctionDef/AsyncFunctionDef
    with matching name, and returns the dedented source lines.
    """
    tree = ast.parse(parent_source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                lines = parent_source.splitlines()
                # node.lineno is 1-based, end_lineno is inclusive
                raw = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                return textwrap.dedent(raw)
    return None


def _source_contains_attr_call(source: str, obj_attr: str, method: str) -> bool:
    """Check if source contains a call like self.<obj_attr>.<method>().

    Detects patterns such as:
        self._startup_semaphore.locked()
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Looking for: self._startup_semaphore.locked()
        # AST shape: Call(func=Attribute(value=Attribute(value=Name(id='self'),
        #            attr='_startup_semaphore'), attr='locked'))
        if isinstance(func, ast.Attribute) and func.attr == method:
            val = func.value
            if isinstance(val, ast.Attribute) and val.attr == obj_attr:
                return True
    return False


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvChannelStartupConcurrency001:
    """INV-CHANNEL-STARTUP-CONCURRENCY-001 contract tests."""

    def test_stream_channel_has_semaphore_guard(self):
        """stream_channel() MUST check _startup_semaphore.locked() before startup.

        AST scan of the nested stream_channel function verifies the
        semaphore capacity check is present, ensuring fail-fast 503
        when at concurrency limit.
        """
        parent_src = _get_register_endpoints_source()
        func_src = _extract_nested_function_source(parent_src, "stream_channel")
        assert func_src is not None, (
            "stream_channel() nested function not found in _register_endpoints"
        )

        assert _source_contains_attr_call(func_src, "_startup_semaphore", "locked"), (
            "INV-CHANNEL-STARTUP-CONCURRENCY-001 violated: stream_channel() "
            "does not check self._startup_semaphore.locked() — "
            "no fail-fast guard for startup stampede"
        )

    def test_hls_playlist_has_semaphore_guard(self):
        """hls_playlist() MUST check _startup_semaphore.locked() before startup.

        AST scan of the nested hls_playlist function verifies the
        semaphore capacity check is present, ensuring fail-fast 503
        when at concurrency limit.
        """
        parent_src = _get_register_endpoints_source()
        func_src = _extract_nested_function_source(parent_src, "hls_playlist")
        assert func_src is not None, (
            "hls_playlist() nested function not found in _register_endpoints"
        )

        assert _source_contains_attr_call(func_src, "_startup_semaphore", "locked"), (
            "INV-CHANNEL-STARTUP-CONCURRENCY-001 violated: hls_playlist() "
            "does not check self._startup_semaphore.locked() — "
            "no fail-fast guard for startup stampede"
        )

    def test_startup_semaphore_and_executor_bounded(self):
        """ProgramDirector MUST have _startup_semaphore and _startup_executor
        both bounded to STARTUP_CAP.

        The semaphore limits concurrency; the executor provides the thread
        pool. They MUST agree on the cap.
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from retrovue.runtime.program_director import ProgramDirector
        from retrovue.runtime.config import InlineChannelConfigProvider

        pd = ProgramDirector(
            channel_config_provider=InlineChannelConfigProvider([]),
            host="127.0.0.1",
            port=0,
        )

        # Semaphore must exist
        assert hasattr(pd, "_startup_semaphore"), (
            "ProgramDirector missing _startup_semaphore"
        )
        sem = pd._startup_semaphore
        assert isinstance(sem, asyncio.Semaphore), (
            f"_startup_semaphore is {type(sem).__name__}, expected asyncio.Semaphore"
        )
        assert sem._value == STARTUP_CAP, (
            f"_startup_semaphore capacity={sem._value}, expected {STARTUP_CAP}"
        )

        # Executor must match
        executor = pd._startup_executor
        assert isinstance(executor, ThreadPoolExecutor)
        assert executor._max_workers == STARTUP_CAP, (
            f"_startup_executor max_workers={executor._max_workers}, "
            f"expected {STARTUP_CAP}"
        )
