"""
Contract Test: Lifecycle Authority

Invariant: INV-LIFECYCLE-PD-SOLE-TEARDOWN-001
    ProgramDirector is the sole teardown decision point.
    ChannelManager MUST NOT call ProgramDirector.stop_channel() directly.
    All teardown decisions flow upward via an injected callback, not via
    a direct PD reference method call.

docs/contracts/lifecycle_authority_contract.md
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path resolution — anchor on the known absolute location of this file
# ---------------------------------------------------------------------------

# This file lives at /opt/retrovue/tests/contracts/test_lifecycle_authority.py
# REPO_ROOT is always /opt/retrovue regardless of pytest CWD.
_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[2]   # tests/contracts -> tests -> retrovue

CM_PATH = REPO_ROOT / "pkg/core/src/retrovue/runtime/channel_manager.py"
PD_PATH = REPO_ROOT / "pkg/core/src/retrovue/runtime/program_director.py"


def _channel_manager_source() -> str:
    return CM_PATH.read_text()


def _program_director_source() -> str:
    return PD_PATH.read_text()


# ---------------------------------------------------------------------------
# INV-LIFECYCLE-PD-SOLE-TEARDOWN-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvLifecyclePdSoleTeardown001:
    """INV-LIFECYCLE-PD-SOLE-TEARDOWN-001 — PD is sole teardown decision point."""

    # Tier: 2 | Ownership invariant — authority boundary
    def test_channel_manager_does_not_call_pd_stop_channel_directly(self):
        """
        ChannelManager source must NOT contain direct calls to
        program_director.stop_channel(...).

        After the inversion refactor, CM calls self.on_linger_expired()
        (the injected callback). PD.stop_channel may only be called from
        within program_director.py itself.
        """
        source = _channel_manager_source()
        assert "program_director.stop_channel" not in source, (
            "INV-LIFECYCLE-PD-SOLE-TEARDOWN-001 VIOLATED: "
            "channel_manager.py calls program_director.stop_channel() directly. "
            "Use the on_linger_expired injected callback instead."
        )

    # Tier: 2 | Ownership invariant — authority boundary
    def test_channel_manager_exposes_on_linger_expired_callback(self):
        """
        ChannelManager must expose an on_linger_expired attribute (callable)
        that is invoked instead of calling PD.stop_channel directly.
        """
        source = _channel_manager_source()
        assert "on_linger_expired" in source, (
            "INV-LIFECYCLE-PD-SOLE-TEARDOWN-001: "
            "channel_manager.py must define on_linger_expired callback attribute."
        )

    # Tier: 2 | Ownership invariant — authority boundary
    def test_deferred_teardown_dead_path_removed(self):
        """
        deferred_teardown_triggered() is a dead stub that always returns False.
        After Phase 2 cleanup it must be removed from ChannelManager.
        """
        source = _channel_manager_source()
        assert "deferred_teardown_triggered" not in source, (
            "INV-LIFECYCLE-PD-SOLE-TEARDOWN-001: "
            "deferred_teardown_triggered() is dead code and must be deleted (L3 rule)."
        )

    # Tier: 2 | Ownership invariant — authority boundary
    def test_compute_jip_position_dead_path_removed(self):
        """
        compute_jip_position() is unused (deprecated). Must be removed.
        """
        source = _channel_manager_source()
        assert "def compute_jip_position" not in source, (
            "INV-LIFECYCLE-PD-SOLE-TEARDOWN-001: "
            "compute_jip_position() is dead code and must be deleted (L3 rule)."
        )

    # Tier: 2 | Ownership invariant — authority boundary
    def test_mock_grid_methods_dead_path_removed(self):
        """
        _build_mock_grid_playout_plan must NOT appear on the base ChannelManager
        class (only on the subclass MockGridChannelManager).
        """
        source = _channel_manager_source()
        tree = ast.parse(source)

        base_cm_methods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ChannelManager":
                for item in ast.walk(node):
                    if isinstance(item, ast.FunctionDef):
                        base_cm_methods.add(item.name)

        assert "_build_mock_grid_playout_plan" not in base_cm_methods, (
            "INV-LIFECYCLE-PD-SOLE-TEARDOWN-001: "
            "_build_mock_grid_playout_plan is dead on base ChannelManager and must be deleted (L3 rule)."
        )

    # Tier: 2 | Ownership invariant — authority boundary
    def test_pd_health_check_loop_does_not_poll_deferred_teardown(self):
        """
        ProgramDirector._health_check_loop must not poll deferred_teardown_triggered().
        After Phase 2, that polling path is removed because the method is gone.
        """
        source = _program_director_source()
        assert "deferred_teardown_triggered" not in source, (
            "INV-LIFECYCLE-PD-SOLE-TEARDOWN-001: "
            "program_director.py still polls deferred_teardown_triggered() — remove this dead path."
        )
