"""
Contract Test: Consumption Adapter Model

Invariant: INV-SINGLE-ACTIVATION-PATH-001
    ProgramDirector.start_channel() is the sole channel activation entry point.
    No parallel activation paths may exist.

Target state (Phases 8b–8d):
    - HLS phantom management is extracted from PD into HlsConsumptionAdapter
    - Raw TS fanout wiring is extracted from PD into TsConsumptionAdapter
    - Both adapters call PD.start_channel() as the single lifecycle entry point
    - _ensure_channel_active_for_hls() is deleted (~190 lines)

These tests MUST FAIL before Phase 8b–8d and PASS after Phase 8d.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[2]  # tests/contracts -> tests -> retrovue

PD_PATH = REPO_ROOT / "server/src/retrovue/runtime/program_director.py"
RUNTIME_DIR = REPO_ROOT / "server/src/retrovue/runtime"


def _pd_source() -> str:
    return PD_PATH.read_text()


# ---------------------------------------------------------------------------
# INV-SINGLE-ACTIVATION-PATH-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvSingleActivationPath001:
    """INV-SINGLE-ACTIVATION-PATH-001 — start_channel() is the sole lifecycle entry point."""

    def test_ensure_channel_active_for_hls_removed(self):
        """
        After Phase 8d: _ensure_channel_active_for_hls() must not exist.

        This was a ~190-line parallel activation path for HLS. The refactor
        extracts HLS phantom management into HlsConsumptionAdapter and routes
        channel activation through PD.start_channel().

        CURRENTLY FAILS (RED): method still exists in PD.
        PASSES (GREEN) after Phase 8d removes it.
        """
        source = _pd_source()
        assert "def _ensure_channel_active_for_hls" not in source, (
            "INV-SINGLE-ACTIVATION-PATH-001 VIOLATED: "
            "_ensure_channel_active_for_hls() is a parallel activation path "
            "that must be removed. HLS phantom management belongs in "
            "HlsConsumptionAdapter. Channel activation belongs in start_channel()."
        )

    def test_hls_phantom_sessions_not_inline_in_pd(self):
        """
        After Phase 8d: _hls_phantom_sessions dict must not be managed inline
        in PD's activation path. Phantom lifecycle belongs in HlsConsumptionAdapter.

        CURRENTLY FAILS (RED): _hls_phantom_sessions is managed inline in PD.
        PASSES (GREEN) after Phase 8b extracts it into HlsConsumptionAdapter.
        """
        source = _pd_source()
        # The guard: PD may still hold a reference to the adapter (which
        # holds _hls_phantom_sessions), but PD itself must not contain
        # the direct dict management logic (pop/set inline).
        # We assert the large inline phantom management block is gone by
        # checking that _hls_phantom_sessions is not assigned-to in PD.
        # After refactor PD hands off to HlsConsumptionAdapter which owns it.
        assert "self._hls_phantom_sessions[" not in source, (
            "INV-SINGLE-ACTIVATION-PATH-001 VIOLATED: "
            "ProgramDirector directly manages _hls_phantom_sessions[]. "
            "Phantom session tracking belongs in HlsConsumptionAdapter. "
            "PD must not contain inline phantom lifecycle logic."
        )

    def test_hls_consumption_adapter_exists(self):
        """
        After Phase 8b: HlsConsumptionAdapter must exist as a class in the
        runtime package. It is responsible for HLS phantom management, keeping
        the channel stream alive while HLS clients poll.

        CURRENTLY FAILS (RED): class does not exist.
        PASSES (GREEN) after Phase 8b creates it.
        """
        # Look in program_director.py or a dedicated file
        pd_source = _pd_source()
        adapter_file = RUNTIME_DIR / "consumption_adapters.py"
        found_in_pd = "class HlsConsumptionAdapter" in pd_source
        found_in_file = adapter_file.exists() and "class HlsConsumptionAdapter" in adapter_file.read_text()
        assert found_in_pd or found_in_file, (
            "INV-SINGLE-ACTIVATION-PATH-001: "
            "HlsConsumptionAdapter class not found. "
            "Phase 8b must extract HLS phantom management into this class. "
            "Place in runtime/consumption_adapters.py or program_director.py."
        )

    def test_ts_consumption_adapter_exists(self):
        """
        After Phase 8c: TsConsumptionAdapter must exist as a class in the
        runtime package. It is responsible for raw TS fanout wiring.

        CURRENTLY FAILS (RED): class does not exist.
        PASSES (GREEN) after Phase 8c creates it.
        """
        pd_source = _pd_source()
        adapter_file = RUNTIME_DIR / "consumption_adapters.py"
        found_in_pd = "class TsConsumptionAdapter" in pd_source
        found_in_file = adapter_file.exists() and "class TsConsumptionAdapter" in adapter_file.read_text()
        assert found_in_pd or found_in_file, (
            "INV-SINGLE-ACTIVATION-PATH-001: "
            "TsConsumptionAdapter class not found. "
            "Phase 8c must extract raw TS fanout wiring into this class. "
            "Place in runtime/consumption_adapters.py or program_director.py."
        )
