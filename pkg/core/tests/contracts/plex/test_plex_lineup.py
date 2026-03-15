"""
Contract tests for Plex HDHomeRun channel lineup.

Verifies:
  INV-PLEX-LINEUP-001 — /lineup.json channel accuracy
  Plex Compatibility Interface — lineup invariants (GuideNumber, order, URLs, determinism)
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from retrovue.integrations.plex.adapter import PlexAdapter
from retrovue.integrations.plex.router import create_plex_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channels(*names: str) -> list[dict]:
    """Build minimal channel dicts matching ProgramDirector._load_channels_list format.

    Includes number (Plex GuideNumber); uses 100+index so lineup ordering is deterministic.
    """
    return [
        {
            "channel_id": name.lower().replace(" ", "-"),
            "number": 100 + (i + 1),
            "channel_id_int": 100 + (i + 1),
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

    def test_guide_numbers_are_numeric_strings(self):
        """GuideNumber MUST be a numeric string (Plex Compatibility Interface)."""
        channels = _make_channels("HBO", "CNN")
        adapter = _make_adapter(channels)
        lineup = adapter.lineup()
        for entry in lineup:
            gn = entry["GuideNumber"]
            assert isinstance(gn, str), (
                f"Plex lineup invariant violated: GuideNumber must be string, got {type(gn).__name__}"
            )
            assert gn.isdigit(), (
                f"Plex lineup invariant violated: GuideNumber must be numeric string, got {gn!r}"
            )

    def test_guide_numbers_sorted_ascending(self):
        """Channel ordering invariant: lineup MUST be in ascending GuideNumber order."""
        channels = _make_channels("HBO", "CNN", "ESPN")
        adapter = _make_adapter(channels)
        lineup = adapter.lineup()
        numbers = [entry["GuideNumber"] for entry in lineup]
        sorted_numbers = sorted(numbers, key=lambda x: (int(x) if x.isdigit() else 0))
        assert numbers == sorted_numbers, (
            f"Plex channel ordering invariant violated: GuideNumbers must be ascending, "
            f"got {numbers}, expected {sorted_numbers}"
        )

    def test_lineup_urls_are_absolute(self):
        """URLs MUST be absolute (Plex Compatibility Interface)."""
        channels = _make_channels("HBO")
        adapter = _make_adapter(channels, base_url="http://192.168.1.50:8000")
        lineup = adapter.lineup()
        for entry in lineup:
            url = entry["URL"]
            assert url.startswith("http://") or url.startswith("https://"), (
                f"Plex lineup invariant violated: URL must be absolute, got {url!r}"
            )

    def test_lineup_deterministic_across_calls(self):
        """Lineup determinism invariant: same set and order across repeated requests."""
        channels = _make_channels("HBO", "CNN")
        adapter = _make_adapter(channels)
        lineup1 = adapter.lineup()
        lineup2 = adapter.lineup()
        assert len(lineup1) == len(lineup2)
        for a, b in zip(lineup1, lineup2):
            assert a["GuideNumber"] == b["GuideNumber"], (
                "Plex lineup determinism invariant violated: GuideNumber changed between calls"
            )
            assert a["URL"] == b["URL"], (
                "Plex lineup determinism invariant violated: URL changed between calls"
            )

    def test_lineup_endpoint_returns_200_and_json_array(self):
        """Lineup endpoint MUST return HTTP 200 and a JSON array (public interface)."""
        app = FastAPI()
        app.include_router(create_plex_router(_make_adapter(_make_channels("HBO"))))
        client = TestClient(app)
        response = client.get("/lineup.json")
        assert response.status_code == 200, (
            f"Plex lineup invariant violated: expected HTTP 200, got {response.status_code}"
        )
        data = response.json()
        assert isinstance(data, list), (
            f"Plex lineup invariant violated: response must be JSON array, got {type(data).__name__}"
        )
