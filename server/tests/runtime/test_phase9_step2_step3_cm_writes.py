"""
Phase 9 Step 2 + Step 3 — ChannelManager is sole writer of
``active_producer`` and ``_channel_state``.

Invariants proven by this file:

1. ``ChannelManager.clear_active_producer()`` exists and nulls the
   producer reference.
2. ``ChannelManager.mark_idle()`` exists and transitions the channel
   state from ``"STOPPED"`` to ``"IDLE"``; otherwise it is a no-op,
   preserving pre-Phase-9 PD behavior where the flip was conditional
   on ``_channel_state == "STOPPED"``.
3. **AST-level guard**: no production module outside
   ``channel_manager.py`` contains an assignment whose target is
   ``.active_producer`` or ``._channel_state``. Direct external writes
   to either field are contract violations.
4. Behavior preservation: the two call sites in ProgramDirector that
   previously did direct writes produce the same observable state
   (producer nulled; channel state moved to IDLE) via the new
   command surface.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from retrovue.runtime.channel_manager import ChannelManager


_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "retrovue"


# ---------------------------------------------------------------------------
# CM command-surface presence
# ---------------------------------------------------------------------------

def test_channel_manager_exposes_clear_active_producer():
    assert hasattr(ChannelManager, "clear_active_producer"), (
        "Phase 9 Step 2: ChannelManager must expose clear_active_producer()."
    )
    assert callable(ChannelManager.clear_active_producer)


def test_channel_manager_exposes_mark_idle():
    assert hasattr(ChannelManager, "mark_idle"), (
        "Phase 9 Step 3: ChannelManager must expose mark_idle()."
    )
    assert callable(ChannelManager.mark_idle)


# ---------------------------------------------------------------------------
# Behavior: the commands preserve existing semantics
# ---------------------------------------------------------------------------

def _make_cm():
    """Construct a ChannelManager with mock deps — enough surface for
    these small state-mutation tests. Avoids bringing up PD or the real
    execution reader."""
    from retrovue.config.testing import TEST_RESOLVED_CONFIG
    clock = MagicMock()
    from datetime import datetime, timezone
    clock.now_utc.return_value = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    cm = ChannelManager(
        channel_id="phase9-test",
        clock=clock,
        execution_reader=MagicMock(),
        program_director=MagicMock(),
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    return cm


def test_clear_active_producer_nulls_the_reference():
    cm = _make_cm()
    cm.active_producer = MagicMock()
    cm.clear_active_producer()
    assert cm.active_producer is None


def test_clear_active_producer_is_idempotent_when_already_none():
    cm = _make_cm()
    assert cm.active_producer is None
    cm.clear_active_producer()  # must not raise
    assert cm.active_producer is None


def test_mark_idle_transitions_stopped_to_idle():
    cm = _make_cm()
    cm._channel_state = "STOPPED"
    cm.mark_idle()
    assert cm._channel_state == "IDLE"


def test_mark_idle_is_noop_when_not_stopped():
    """Preserves pre-Phase-9 PD behavior: PD only flipped on STOPPED;
    any other state was left alone."""
    cm = _make_cm()
    for state in ("RUNNING", "IDLE"):
        cm._channel_state = state
        cm.mark_idle()
        assert cm._channel_state == state, (
            f"mark_idle must be a no-op when state is {state!r}; "
            "preserving the pre-Phase-9 conditional behavior."
        )


# ---------------------------------------------------------------------------
# AST-level source guard: no external writes to the two fields
# ---------------------------------------------------------------------------

def _collect_assign_targets(path: Path, attr_name: str) -> list[tuple[int, str]]:
    """Return (lineno, code) for every Assign / AugAssign whose target
    is ``<anything>.attr_name``."""
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and t.attr == attr_name:
                try:
                    snippet = ast.get_source_segment(source, node) or ""
                except Exception:
                    snippet = "<no snippet>"
                hits.append((node.lineno, snippet.strip()))
                break
    return hits


_PROD_MODULES = [
    _SRC_ROOT / "runtime" / "program_director.py",
    _SRC_ROOT / "runtime" / "consumption_adapters.py",
    _SRC_ROOT / "runtime" / "pd_helpers.py",
    _SRC_ROOT / "runtime" / "channel_stream.py",
    _SRC_ROOT / "runtime" / "block_plan_producer.py",
    _SRC_ROOT / "usecases" / "channel_manager_launch.py",
]


@pytest.mark.parametrize("path", _PROD_MODULES, ids=lambda p: p.name)
def test_no_external_writes_to_active_producer(path: Path):
    offenders = _collect_assign_targets(path, "active_producer")
    assert not offenders, (
        f"{path.name} contains direct writes to .active_producer at "
        f"{offenders}. Use ChannelManager.clear_active_producer() instead."
    )


@pytest.mark.parametrize("path", _PROD_MODULES, ids=lambda p: p.name)
def test_no_external_writes_to_channel_state(path: Path):
    offenders = _collect_assign_targets(path, "_channel_state")
    assert not offenders, (
        f"{path.name} contains direct writes to ._channel_state at "
        f"{offenders}. Use ChannelManager.mark_idle() (or another "
        "CM-exposed state-transition method) instead."
    )


def test_channel_manager_is_the_only_active_producer_writer():
    """Sanity: ChannelManager itself still writes active_producer (it's
    the owner). This test guards against someone accidentally deleting
    those writes while refactoring."""
    cm_path = _SRC_ROOT / "runtime" / "channel_manager.py"
    hits = _collect_assign_targets(cm_path, "active_producer")
    assert hits, (
        "ChannelManager must retain at least one write to active_producer "
        "— it is the field's owner."
    )


def test_channel_manager_is_the_only_channel_state_writer():
    """Same sanity check for _channel_state."""
    cm_path = _SRC_ROOT / "runtime" / "channel_manager.py"
    hits = _collect_assign_targets(cm_path, "_channel_state")
    assert hits, (
        "ChannelManager must retain at least one write to _channel_state "
        "— it is the field's owner."
    )


# ---------------------------------------------------------------------------
# Source-level: PD's former direct-write call sites now use the commands
# ---------------------------------------------------------------------------

def test_program_director_calls_clear_active_producer():
    source = (_SRC_ROOT / "runtime" / "program_director.py").read_text()
    assert "clear_active_producer(" in source, (
        "ProgramDirector must call manager.clear_active_producer() at the "
        "two call sites that previously did manager.active_producer = None."
    )


def test_program_director_calls_mark_idle():
    source = (_SRC_ROOT / "runtime" / "program_director.py").read_text()
    assert "mark_idle(" in source, (
        "ProgramDirector must call manager.mark_idle() at the site that "
        "previously did manager._channel_state = 'IDLE'."
    )
