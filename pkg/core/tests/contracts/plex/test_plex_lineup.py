"""
Contract tests for Plex HDHomeRun channel lineup.

Verifies:
  INV-PLEX-LINEUP-001 — /lineup.json channel accuracy
"""

import pytest

from retrovue.integrations.plex.adapter import PlexAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channels(*names: str) -> list[dict]:
    """Build minimal channel dicts matching ProgramDirector._load_channels_list format."""
    return [
        {
            "channel_id": name.lower().replace(" ", "-"),
            "channel_id_int": i + 1,
            "name": name,
            "schedule_config": {"channel_type": "network"},
        }
        for i, name in enumerate(names)
    ]


def _make_adapter(channels: list[dict], *, base_url: str = "http://192.168.1.50:8000") -> PlexAdapter:
    return PlexAdapter(channels=channels, base_url=base_url)


# ---------------------------------------------------------------------------
# INV-PLEX-LINEUP-001
# ---------------------------------------------------------------------------


class TestPlexLineup:
    """INV-PLEX-LINEUP-001 contract tests."""

    REQUIRED_ENTRY_FIELDS = {"GuideNumber", "GuideName", "URL"}

    def test_lineup_entry_count_matches_registry(self):
        """Lineup MUST contain exactly one entry per registered channel."""
        channels = _make_channels("HBO", "CNN", "ESPN")
        adapter = _make_adapter(channels)
        lineup = adapter.lineup()

        assert len(lineup) == len(channels), (
            f"INV-PLEX-LINEUP-001 violated: lineup has {len(lineup)} entries "
            f"but registry has {len(channels)} channels"
        )

    def test_lineup_entries_have_required_fields(self):
        """Each entry MUST contain GuideNumber, GuideName, URL."""
        channels = _make_channels("HBO", "CNN")
        adapter = _make_adapter(channels)

        for entry in adapter.lineup():
            missing = self.REQUIRED_ENTRY_FIELDS - set(entry.keys())
            assert not missing, (
                f"INV-PLEX-LINEUP-001 violated: lineup entry missing fields: {missing}"
            )

    def test_guide_name_matches_channel_display_name(self):
        """GuideName MUST match the channel's display name from the registry."""
        channels = _make_channels("HBO", "CNN")
        adapter = _make_adapter(channels)
        lineup = adapter.lineup()

        expected_names = {ch["name"] for ch in channels}
        actual_names = {entry["GuideName"] for entry in lineup}

        assert actual_names == expected_names, (
            f"INV-PLEX-LINEUP-001 violated: GuideName mismatch — "
            f"expected {expected_names}, got {actual_names}"
        )

    def test_guide_numbers_are_unique(self):
        """GuideNumber MUST be unique per channel."""
        channels = _make_channels("HBO", "CNN", "ESPN")
        adapter = _make_adapter(channels)
        lineup = adapter.lineup()

        numbers = [entry["GuideNumber"] for entry in lineup]
        assert len(numbers) == len(set(numbers)), (
            f"INV-PLEX-LINEUP-001 violated: duplicate GuideNumbers: {numbers}"
        )

    def test_url_points_to_channel_ts_endpoint(self):
        """URL MUST resolve to /channel/{id}.ts."""
        channels = _make_channels("HBO")
        adapter = _make_adapter(channels, base_url="http://10.0.0.1:8000")
        lineup = adapter.lineup()

        url = lineup[0]["URL"]
        assert "/channel/" in url and url.endswith(".ts"), (
            f"INV-PLEX-LINEUP-001 violated: URL '{url}' is not a /channel/{{id}}.ts endpoint"
        )

    def test_url_contains_correct_channel_id(self):
        """URL MUST reference the correct channel_id."""
        channels = _make_channels("HBO")
        adapter = _make_adapter(channels, base_url="http://10.0.0.1:8000")
        lineup = adapter.lineup()

        url = lineup[0]["URL"]
        assert f"/channel/{channels[0]['channel_id']}.ts" in url, (
            f"INV-PLEX-LINEUP-001 violated: URL '{url}' does not contain "
            f"channel_id '{channels[0]['channel_id']}'"
        )

    def test_url_uses_adapter_base_url(self):
        """URL MUST use the adapter's base URL for stream resolution."""
        channels = _make_channels("HBO")
        base = "http://192.168.1.99:9000"
        adapter = _make_adapter(channels, base_url=base)
        lineup = adapter.lineup()

        assert lineup[0]["URL"].startswith(base), (
            f"INV-PLEX-LINEUP-001 violated: URL does not start with base_url '{base}'"
        )

    def test_no_phantom_channels(self):
        """Lineup MUST NOT contain channels absent from the registry."""
        channels = _make_channels("HBO")
        adapter = _make_adapter(channels)
        lineup = adapter.lineup()

        registry_ids = {ch["channel_id"] for ch in channels}
        for entry in lineup:
            # Extract channel_id from URL
            url = entry["URL"]
            url_channel = url.rsplit("/channel/", 1)[-1].replace(".ts", "")
            assert url_channel in registry_ids, (
                f"INV-PLEX-LINEUP-001 violated: phantom channel '{url_channel}' "
                f"in lineup but not in registry"
            )

    def test_empty_registry_produces_empty_lineup(self):
        """Empty channel registry MUST produce an empty lineup array."""
        adapter = _make_adapter([])
        lineup = adapter.lineup()

        assert lineup == [], (
            "INV-PLEX-LINEUP-001 violated: non-empty lineup for empty registry"
        )

    def test_lineup_does_not_reorder_or_filter(self):
        """Adapter MUST NOT filter or omit channels from the registry."""
        channels = _make_channels("HBO", "CNN", "ESPN", "AMC", "TNT")
        adapter = _make_adapter(channels)
        lineup = adapter.lineup()

        lineup_names = {entry["GuideName"] for entry in lineup}
        registry_names = {ch["name"] for ch in channels}

        assert lineup_names == registry_names, (
            f"INV-PLEX-LINEUP-001 violated: lineup names {lineup_names} "
            f"do not match registry names {registry_names}"
        )
