"""INV-PLAYOUT-MODULE-EXTRACTION-001: Extracted helper classes are importable
from their dedicated sibling modules, and backward-compatible re-exports from
the original modules remain functional.
"""

import importlib
import pytest


# ── New dedicated module imports (RED before extraction) ─────────────────

class TestPdHelpersModule:
    """Classes extracted from program_director.py into pd_helpers.py."""

    def test_import_raw_ts_response(self):
        mod = importlib.import_module("retrovue.runtime.pd_helpers")
        assert hasattr(mod, "_RawTSResponse")

    def test_import_hls_access_filter(self):
        mod = importlib.import_module("retrovue.runtime.pd_helpers")
        assert hasattr(mod, "HLSAccessFilter")

    def test_import_system_mode(self):
        mod = importlib.import_module("retrovue.runtime.pd_helpers")
        assert hasattr(mod, "SystemMode")

    def test_import_hls_diagnostics_state(self):
        mod = importlib.import_module("retrovue.runtime.pd_helpers")
        assert hasattr(mod, "HlsDiagnosticsState")

    def test_import_channel_manager_provider(self):
        mod = importlib.import_module("retrovue.runtime.pd_helpers")
        assert hasattr(mod, "ChannelManagerProvider")


class TestCmHelpersModule:
    """Classes extracted from channel_manager.py into cm_helpers.py."""

    def test_import_feed_state(self):
        mod = importlib.import_module("retrovue.runtime.cm_helpers")
        assert hasattr(mod, "_FeedState")

    def test_import_as_run_annotation(self):
        mod = importlib.import_module("retrovue.runtime.cm_helpers")
        assert hasattr(mod, "_AsRunAnnotation")

    def test_import_traced_socket(self):
        mod = importlib.import_module("retrovue.runtime.cm_helpers")
        assert hasattr(mod, "TracedSocket")


class TestBlockPlanProducerModule:
    """BlockPlanProducer extracted into its own module."""

    def test_import_block_plan_producer(self):
        mod = importlib.import_module("retrovue.runtime.block_plan_producer")
        assert hasattr(mod, "BlockPlanProducer")


# ── Backward-compatible re-exports (should stay GREEN) ───────────────────

class TestBackwardCompatProgramDirector:
    """Re-exports from program_director must still work."""

    def test_reexport_raw_ts_response(self):
        from retrovue.runtime.program_director import _RawTSResponse
        assert _RawTSResponse is not None

    def test_reexport_hls_access_filter(self):
        from retrovue.runtime.program_director import HLSAccessFilter
        assert HLSAccessFilter is not None

    def test_reexport_system_mode(self):
        from retrovue.runtime.program_director import SystemMode
        assert SystemMode is not None

    def test_reexport_hls_diagnostics_state(self):
        from retrovue.runtime.program_director import HlsDiagnosticsState
        assert HlsDiagnosticsState is not None


class TestBackwardCompatChannelManager:
    """Re-exports from channel_manager must still work."""

    def test_reexport_block_plan_producer(self):
        from retrovue.runtime.channel_manager import BlockPlanProducer
        assert BlockPlanProducer is not None

    def test_reexport_feed_state(self):
        from retrovue.runtime.channel_manager import _FeedState
        assert _FeedState is not None

    def test_reexport_as_run_annotation(self):
        from retrovue.runtime.channel_manager import _AsRunAnnotation
        assert _AsRunAnnotation is not None

    def test_reexport_traced_socket(self):
        from retrovue.runtime.channel_manager import TracedSocket
        assert TracedSocket is not None
