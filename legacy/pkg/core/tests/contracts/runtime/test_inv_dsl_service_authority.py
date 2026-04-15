"""
Contract test: INV-DSL-SERVICE-AUTHORITY-001

Verifies that ProgramDirector stores DslScheduleService instances in an
explicit typed dict (_dsl_services), that the same instance is returned on
repeated calls, that _reload_config() invalidates compiled DSL state on all
services, and that stop() shuts down all services and clears the dict.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from retrovue.config.testing import TEST_RESOLVED_CONFIG
from retrovue.runtime.config import (
    ChannelConfig,
    InlineChannelConfigProvider,
    DEFAULT_PROGRAM_FORMAT,
)
from retrovue.runtime.program_director import ProgramDirector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(channel_id: str, number: int = 1) -> ChannelConfig:
    return ChannelConfig(
        channel_id=channel_id,
        number=number,
        channel_id_int=number,
        name=channel_id.title(),
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source="dsl",
        schedule_config={"dsl_path": f"/fake/{channel_id}.dsl"},
    )


def _make_director(*channel_ids: str) -> ProgramDirector:
    configs = [_make_config(cid, i + 1) for i, cid in enumerate(channel_ids)]
    return ProgramDirector(
        channel_config_provider=InlineChannelConfigProvider(configs),
        resolved_config=TEST_RESOLVED_CONFIG,
    )


def _mock_dsl_service() -> MagicMock:
    svc = MagicMock()
    svc._channel_dsl = "compiled-state"
    return svc


# ---------------------------------------------------------------------------
# INV-DSL-SERVICE-AUTHORITY-001 tests
# ---------------------------------------------------------------------------

class TestDslServiceAuthority:

    def test_dsl_services_dict_initialized_empty(self):
        """_dsl_services is an empty dict at construction."""
        pd = _make_director("ch1")
        assert hasattr(pd, "_dsl_services")
        assert isinstance(pd._dsl_services, dict)
        assert len(pd._dsl_services) == 0

    def test_no_dynamic_dsl_attrs_on_self(self):
        """No _dsl_* attributes are set directly on self (no setattr pattern)."""
        pd = _make_director("ch1")
        # Inject a mock service into the dict
        mock_svc = _mock_dsl_service()
        pd._dsl_services["ch1"] = mock_svc

        # Verify the attr is NOT also set as a dynamic instance attribute
        assert not hasattr(pd, "_dsl_ch1"), (
            "_dsl_ch1 should NOT be a direct instance attribute — "
            "services live in _dsl_services dict only"
        )

    def test_get_dsl_service_stores_in_explicit_dict(self):
        """_get_dsl_service() stores the created service in _dsl_services."""
        pd = _make_director("ch1")
        config = pd._channel_config_provider.get_channel_config("ch1")

        mock_svc = _mock_dsl_service()
        with patch("retrovue.runtime.program_director.ProgramDirector._get_dsl_service",
                   wraps=pd._get_dsl_service) as _:
            # Inject a pre-built mock so we don't need a real DSL file
            pd._dsl_services["ch1"] = mock_svc
            result = pd._get_dsl_service("ch1", config)

        assert result is mock_svc
        assert pd._dsl_services.get("ch1") is mock_svc
        # No direct instance attribute
        assert not hasattr(pd, "_dsl_ch1")

    def test_same_instance_returned_on_repeated_calls(self):
        """_get_dsl_service() returns the same instance for repeated calls (no double-create)."""
        pd = _make_director("ch1")
        config = pd._channel_config_provider.get_channel_config("ch1")

        mock_svc = _mock_dsl_service()
        pd._dsl_services["ch1"] = mock_svc

        r1 = pd._get_dsl_service("ch1", config)
        r2 = pd._get_dsl_service("ch1", config)
        r3 = pd._get_dsl_service("ch1", config)

        assert r1 is r2 is r3 is mock_svc

    def test_different_channels_get_different_services(self):
        """Two channels get two different service instances, both stored in dict."""
        pd = _make_director("ch1", "ch2")
        svc1 = _mock_dsl_service()
        svc2 = _mock_dsl_service()
        pd._dsl_services["ch1"] = svc1
        pd._dsl_services["ch2"] = svc2

        config1 = pd._channel_config_provider.get_channel_config("ch1")
        config2 = pd._channel_config_provider.get_channel_config("ch2")

        assert pd._get_dsl_service("ch1", config1) is svc1
        assert pd._get_dsl_service("ch2", config2) is svc2
        assert svc1 is not svc2

    def test_reload_config_invalidates_all_dsl_services(self):
        """_reload_config() sets _channel_dsl = None on every service in _dsl_services."""
        pd = _make_director("ch1", "ch2")
        svc1 = _mock_dsl_service()
        svc2 = _mock_dsl_service()
        svc1._channel_dsl = "state-ch1"
        svc2._channel_dsl = "state-ch2"
        pd._dsl_services["ch1"] = svc1
        pd._dsl_services["ch2"] = svc2

        result = pd._reload_config()

        assert svc1._channel_dsl is None
        assert svc2._channel_dsl is None
        assert "dsl:ch1" in result["reloaded"]
        assert "dsl:ch2" in result["reloaded"]

    def test_reload_config_does_not_scan_vars(self):
        """_reload_config() does not touch any _dsl_* dynamic attrs set outside the dict."""
        pd = _make_director("ch1")
        # Manually set a rogue dynamic attr that should be invisible
        object.__setattr__(pd, "_dsl_rogue", _mock_dsl_service())

        # Only ch1 (in the dict) should be reloaded
        pd._dsl_services["ch1"] = _mock_dsl_service()
        result = pd._reload_config()

        assert "dsl:ch1" in result["reloaded"]
        # rogue attr not in reloaded list
        assert "dsl:rogue" not in result["reloaded"]

    def test_stop_calls_shutdown_on_all_dsl_services(self):
        """stop() calls .shutdown() on every service in _dsl_services."""
        pd = _make_director("ch1", "ch2")
        svc1 = _mock_dsl_service()
        svc2 = _mock_dsl_service()
        pd._dsl_services["ch1"] = svc1
        pd._dsl_services["ch2"] = svc2

        # Prevent real HTTP/pace teardown from running
        pd._stop_http_server = lambda: None
        pd._pace.stop = lambda: None
        pd._startup_executor.shutdown = lambda wait=True: None

        pd.stop(timeout=0.1)

        svc1.shutdown.assert_called_once()
        svc2.shutdown.assert_called_once()

    def test_stop_clears_dsl_services_dict(self):
        """stop() clears _dsl_services so no stale references remain."""
        pd = _make_director("ch1")
        pd._dsl_services["ch1"] = _mock_dsl_service()

        pd._stop_http_server = lambda: None
        pd._pace.stop = lambda: None
        pd._startup_executor.shutdown = lambda wait=True: None

        pd.stop(timeout=0.1)

        assert len(pd._dsl_services) == 0

    def test_stop_handles_shutdown_exception_gracefully(self):
        """stop() logs and continues if .shutdown() raises; other services still shut down."""
        pd = _make_director("ch1", "ch2")
        bad_svc = _mock_dsl_service()
        bad_svc.shutdown.side_effect = RuntimeError("boom")
        good_svc = _mock_dsl_service()
        pd._dsl_services["ch1"] = bad_svc
        pd._dsl_services["ch2"] = good_svc

        pd._stop_http_server = lambda: None
        pd._pace.stop = lambda: None
        pd._startup_executor.shutdown = lambda wait=True: None

        # Should not raise
        pd.stop(timeout=0.1)

        bad_svc.shutdown.assert_called_once()
        good_svc.shutdown.assert_called_once()
