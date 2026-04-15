"""
Contract test: INV-CHANNEL-LIST-CACHE-001

Verifies that ProgramDirector caches the channel list after prewarm,
returns the cached value on repeated calls (without re-querying the provider),
and correctly invalidates the cache on /admin/reload-config.
"""
from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from retrovue.config.testing import TEST_RESOLVED_CONFIG
from retrovue.runtime.config import ChannelConfig, InlineChannelConfigProvider, DEFAULT_PROGRAM_FORMAT
from retrovue.runtime.program_director import ProgramDirector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(channel_id: str, number: int) -> ChannelConfig:
    return ChannelConfig(
        channel_id=channel_id,
        number=number,
        channel_id_int=number,
        name=channel_id.title(),
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source="dsl",
        schedule_config={},
    )


def _make_director(configs: list[ChannelConfig]) -> ProgramDirector:
    """Create a ProgramDirector with an InlineChannelConfigProvider, no real startup."""
    return ProgramDirector(
        channel_config_provider=InlineChannelConfigProvider(configs),
        resolved_config=TEST_RESOLVED_CONFIG,
    )


# ---------------------------------------------------------------------------
# INV-CHANNEL-LIST-CACHE-001 tests
# ---------------------------------------------------------------------------

class TestChannelListCache:

    def test_cache_none_before_prewarm(self):
        """Before prewarm completes, _cached_channels_list is None."""
        pd = _make_director([_make_config("ch1", 1)])
        assert pd._cached_channels_list is None

    def test_load_channels_list_before_prewarm_returns_data_without_caching(self):
        """_load_channels_list() returns data even before prewarm but does NOT cache it
        (startup_complete is not set, so we don't want to freeze a partial list)."""
        pd = _make_director([_make_config("ch1", 1)])
        # startup_complete NOT set
        assert not pd._startup_complete.is_set()

        result = pd._load_channels_list()
        assert len(result) == 1
        assert result[0]["channel_id"] == "ch1"
        # Must not have cached it (prewarm not done)
        assert pd._cached_channels_list is None

    def test_load_channels_list_after_startup_complete_caches_result(self):
        """After startup_complete is set, _load_channels_list() caches the result."""
        pd = _make_director([_make_config("ch1", 1)])
        pd._startup_complete.set()  # simulate prewarm done

        result = pd._load_channels_list()
        assert pd._cached_channels_list is not None
        assert pd._cached_channels_list is result  # same object

    def test_repeated_calls_return_same_cached_object(self):
        """Repeated calls return the same list object (no repeated provider calls)."""
        call_count = [0]
        orig_build = ProgramDirector._build_channels_list

        def counting_build(self):
            call_count[0] += 1
            return orig_build(self)

        pd = _make_director([_make_config("ch1", 1), _make_config("ch2", 2)])
        pd._startup_complete.set()

        with patch.object(ProgramDirector, "_build_channels_list", counting_build):
            r1 = pd._load_channels_list()
            r2 = pd._load_channels_list()
            r3 = pd._load_channels_list()

        # _build_channels_list should have been called exactly once
        # (first call builds; subsequent calls hit cache)
        assert call_count[0] == 1
        assert r1 is r2 is r3

    def test_prewarm_populates_cache(self):
        """_prewarm_channel_schedules() populates _cached_channels_list."""
        pd = _make_director([_make_config("ch1", 1)])
        # _prewarm_channel_schedules requires schedule services; patch the inner loop
        # to just skip compilation (no DB available in unit test context)
        with patch.object(pd, "_get_schedule_service_for_channel") as mock_svc:
            mock_svc.return_value.load_schedule.return_value = (True, None)
            pd._prewarm_channel_schedules()

        assert pd._cached_channels_list is not None
        assert any(c["channel_id"] == "ch1" for c in pd._cached_channels_list)

    def test_reload_config_invalidates_cache(self):
        """_reload_config() sets _cached_channels_list to None."""
        pd = _make_director([_make_config("ch1", 1)])
        pd._startup_complete.set()
        # Populate cache
        pd._load_channels_list()
        assert pd._cached_channels_list is not None

        # Reload (provider has no reload method on InlineChannelConfigProvider — that's fine)
        result = pd._reload_config()

        # Cache must be cleared
        assert pd._cached_channels_list is None
        assert "channel_list_cache" in result["reloaded"]

    def test_post_reload_call_rebuilds_from_provider(self):
        """After reload invalidates cache, next call rebuilds from provider."""
        pd = _make_director([_make_config("ch1", 1)])
        pd._startup_complete.set()

        # First population
        r1 = pd._load_channels_list()
        assert pd._cached_channels_list is not None

        # Reload
        pd._reload_config()
        assert pd._cached_channels_list is None

        # Next call rebuilds
        r2 = pd._load_channels_list()
        assert pd._cached_channels_list is not None
        assert r2[0]["channel_id"] == "ch1"

    def test_post_reload_reflects_provider_changes(self):
        """After reload + provider update, next call returns fresh data."""
        provider = InlineChannelConfigProvider([_make_config("ch1", 1)])
        pd = ProgramDirector(
            channel_config_provider=provider,
            resolved_config=TEST_RESOLVED_CONFIG,
        )
        pd._startup_complete.set()

        r1 = pd._load_channels_list()
        assert len(r1) == 1

        # Simulate a channel addition
        provider.add_config(_make_config("ch2", 2))

        # Before reload, cache returns stale data
        r_stale = pd._load_channels_list()
        assert len(r_stale) == 1  # still cached

        # After reload, fresh data
        pd._reload_config()
        r_fresh = pd._load_channels_list()
        assert len(r_fresh) == 2
        channel_ids = {c["channel_id"] for c in r_fresh}
        assert "ch1" in channel_ids
        assert "ch2" in channel_ids

    def test_build_channels_list_not_affected_by_cache(self):
        """_build_channels_list() always queries the provider, ignoring cache."""
        pd = _make_director([_make_config("ch1", 1)])
        pd._startup_complete.set()
        pd._load_channels_list()  # populate cache

        # Add a channel to the provider
        pd._channel_config_provider.add_config(_make_config("ch2", 2))

        # _build_channels_list must see the new channel (bypasses cache)
        raw = pd._build_channels_list()
        assert len(raw) == 2

        # But cached result is still stale (cache not invalidated)
        cached = pd._load_channels_list()
        assert len(cached) == 1  # stale cache — correct behavior until reload
