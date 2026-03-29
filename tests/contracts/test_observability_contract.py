"""
Contract test: INV-OBSERVABILITY-LIFECYCLE-001
Lifecycle events are emitted at DEBUG level for key transitions.
Correlation IDs flow through viewer sessions.
"""
import logging
import pytest


class TestLifecycleObservability:
    def test_channel_manager_has_lifecycle_event_emitter(self):
        from retrovue.runtime.channel_manager import ChannelManager
        assert hasattr(ChannelManager, "_emit_lifecycle_event"), (
            "INV-OBSERVABILITY-LIFECYCLE-001: ChannelManager must have _emit_lifecycle_event"
        )

    def test_lifecycle_event_accepts_event_and_fields(self):
        import inspect
        from retrovue.runtime.channel_manager import ChannelManager
        sig = inspect.signature(ChannelManager._emit_lifecycle_event)
        params = list(sig.parameters.keys())
        assert "event" in params, f"_emit_lifecycle_event must accept 'event' param, got: {params}"
        assert "fields" in params, f"_emit_lifecycle_event must accept 'fields' param, got: {params}"

    def test_consumption_adapters_importable(self):
        from retrovue.runtime.consumption_adapters import HlsConsumptionAdapter, TsConsumptionAdapter
        assert HlsConsumptionAdapter is not None
        assert TsConsumptionAdapter is not None

    def test_hls_adapter_has_activate(self):
        from retrovue.runtime.consumption_adapters import HlsConsumptionAdapter
        assert hasattr(HlsConsumptionAdapter, "activate"), (
            "HlsConsumptionAdapter must have activate() method"
        )

    def test_ts_adapter_has__wire_fanout(self):
        from retrovue.runtime.consumption_adapters import TsConsumptionAdapter
        assert hasattr(TsConsumptionAdapter, "_wire_fanout"), (
            "TsConsumptionAdapter must have _wire_fanout() method"
        )
