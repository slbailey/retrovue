"""
Phase 9 Step 4 — ProgramDirector is sole writer of ``_fanout_buffers``.

Invariants proven by this file:

1. ``ProgramDirector.register_fanout_buffer(channel_id, fanout)`` exists
   and performs exactly the write semantics of
   ``self._fanout_buffers[channel_id] = fanout`` (under the existing
   ``_fanout_lock``).

2. No module outside ``program_director.py`` contains a subscript
   assignment targeting ``._fanout_buffers[...]``. The
   ``HlsConsumptionAdapter``'s previous direct write
   (``pd._fanout_buffers[channel_id] = fanout``) is gone; the adapter
   calls ``pd.register_fanout_buffer(...)`` instead.

3. Behavior preservation: after ``register_fanout_buffer(cid, f)``,
   lookup via ``pd._fanout_buffers[cid]`` returns ``f``; and the write
   is idempotent (second registration replaces the prior fanout — the
   same behavior as direct subscript assignment had).
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from retrovue.runtime.program_director import ProgramDirector


_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "retrovue"


# ---------------------------------------------------------------------------
# PD surface
# ---------------------------------------------------------------------------

def test_program_director_exposes_register_fanout_buffer():
    assert hasattr(ProgramDirector, "register_fanout_buffer"), (
        "Phase 9 Step 4: ProgramDirector must expose "
        "register_fanout_buffer() so adapters do not write "
        "_fanout_buffers directly."
    )
    assert callable(ProgramDirector.register_fanout_buffer)


# ---------------------------------------------------------------------------
# Behavior: the command is a behavior-preserving wrapper over the direct
# subscript assignment
# ---------------------------------------------------------------------------

def _make_bare_pd():
    """Construct a PD skeleton with just the surfaces the write path
    needs: `_fanout_buffers`, `_fanout_lock`. This matches the
    minimal-harness pattern established in Phase 8 Step 4 tests."""
    pd = ProgramDirector.__new__(ProgramDirector)
    pd._fanout_buffers = {}
    pd._fanout_lock = threading.Lock()
    return pd


def test_register_fanout_buffer_writes_the_registry():
    pd = _make_bare_pd()
    fake_fanout = MagicMock()
    pd.register_fanout_buffer("ch-1", fake_fanout)
    assert pd._fanout_buffers["ch-1"] is fake_fanout


def test_register_fanout_buffer_replaces_existing_entry():
    """Same semantic as the pre-Phase-9 subscript assignment: if a
    fanout already exists for the channel, the new one replaces it."""
    pd = _make_bare_pd()
    first = MagicMock()
    second = MagicMock()
    pd.register_fanout_buffer("ch-1", first)
    pd.register_fanout_buffer("ch-1", second)
    assert pd._fanout_buffers["ch-1"] is second


# ---------------------------------------------------------------------------
# AST-level source guard: no external subscript writes to _fanout_buffers
# ---------------------------------------------------------------------------

def _collect_fanout_subscript_assigns(path: Path) -> list[tuple[int, str]]:
    """Walk the AST for subscript-assignments whose subscript base is
    an attribute named ``_fanout_buffers``. This catches

        X._fanout_buffers[key] = value
        X._fanout_buffers[key] += value    (AugAssign)

    but ignores method calls like ``pop`` or ``clear`` (those are
    pattern-scanned separately if needed). Comments and docstrings are
    invisible to the AST so there are no false positives.
    """
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            base = target.value
            if isinstance(base, ast.Attribute) and base.attr == "_fanout_buffers":
                try:
                    snippet = ast.get_source_segment(source, node) or ""
                except Exception:
                    snippet = "<no snippet>"
                hits.append((node.lineno, snippet.strip()))
                break
    return hits


_PROD_MODULES = [
    _SRC_ROOT / "runtime" / "consumption_adapters.py",
    _SRC_ROOT / "runtime" / "channel_manager.py",
    _SRC_ROOT / "runtime" / "pd_helpers.py",
    _SRC_ROOT / "runtime" / "channel_stream.py",
    _SRC_ROOT / "runtime" / "block_plan_producer.py",
    _SRC_ROOT / "usecases" / "channel_manager_launch.py",
]


@pytest.mark.parametrize("path", _PROD_MODULES, ids=lambda p: p.name)
def test_no_external_subscript_write_to_fanout_buffers(path: Path):
    offenders = _collect_fanout_subscript_assigns(path)
    assert not offenders, (
        f"{path.name} contains direct subscript writes to "
        f"._fanout_buffers at {offenders}. Use "
        "pd.register_fanout_buffer(channel_id, fanout) instead."
    )


def test_program_director_retains_internal_fanout_buffer_writes():
    """Sanity: PD is the field's owner. It must still write
    ``self._fanout_buffers[...]`` inside its own methods (e.g.
    ``_get_or_create_fanout_buffer``). If those writes disappear,
    something else has gone wrong."""
    pd_path = _SRC_ROOT / "runtime" / "program_director.py"
    hits = _collect_fanout_subscript_assigns(pd_path)
    assert hits, (
        "program_director.py must retain at least one subscript write "
        "to ._fanout_buffers — PD is the owner."
    )


# ---------------------------------------------------------------------------
# Source-level: adapter uses the command; PD exposes it
# ---------------------------------------------------------------------------

def test_consumption_adapters_calls_register_fanout_buffer():
    source = (_SRC_ROOT / "runtime" / "consumption_adapters.py").read_text()
    assert "register_fanout_buffer(" in source, (
        "HlsConsumptionAdapter must call pd.register_fanout_buffer(...) "
        "to register fanouts it constructs; direct subscript assignment "
        "on pd._fanout_buffers is no longer permitted."
    )


def test_consumption_adapters_does_not_reference_fanout_buffers_by_attribute():
    """A complementary guard that also catches forms like
    ``pd._fanout_buffers.update({...})`` which wouldn't surface as an
    AST subscript Assign. We require that ``consumption_adapters.py``
    contains no reference to ``._fanout_buffers`` at all — all
    interaction flows through ``register_fanout_buffer``.
    """
    source = (_SRC_ROOT / "runtime" / "consumption_adapters.py").read_text()
    assert "_fanout_buffers" not in source, (
        "consumption_adapters.py must not mention ._fanout_buffers in "
        "any form. Use pd.register_fanout_buffer(...) only."
    )
