"""
Contract tests for Plex HDHomeRun virtual tuner discovery.

Verifies:
  INV-PLEX-DISCOVERY-001 — /discover.json payload correctness
  INV-PLEX-TUNER-STATUS-001 — /lineup_status.json scan state
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
# INV-PLEX-DISCOVERY-001
# ---------------------------------------------------------------------------


class TestPlexDiscovery:
    """INV-PLEX-DISCOVERY-001 contract tests."""

    REQUIRED_FIELDS = {"FriendlyName", "DeviceID", "TunerCount", "LineupURL"}

    def test_discover_contains_all_required_hdhomerun_fields(self):
        """Response MUST include FriendlyName, DeviceID, TunerCount, LineupURL."""
        adapter = _make_adapter(_make_channels("HBO", "CNN"))
        result = adapter.discover()

        missing = self.REQUIRED_FIELDS - set(result.keys())
        assert not missing, (
            f"INV-PLEX-DISCOVERY-001 violated: /discover.json missing fields: {missing}"
        )

    def test_tuner_count_equals_channel_registry_size(self):
        """TunerCount MUST equal the number of registered channels."""
        channels = _make_channels("HBO", "CNN", "ESPN")
        adapter = _make_adapter(channels)
        result = adapter.discover()

        assert result["TunerCount"] == len(channels), (
            f"INV-PLEX-DISCOVERY-001 violated: TunerCount={result['TunerCount']} "
            f"but registry has {len(channels)} channels"
        )

    def test_tuner_count_updates_with_channel_list(self):
        """TunerCount MUST reflect current registry, not a cached value."""
        one = _make_channels("HBO")
        three = _make_channels("HBO", "CNN", "ESPN")

        assert _make_adapter(one).discover()["TunerCount"] == 1
        assert _make_adapter(three).discover()["TunerCount"] == 3

    def test_device_id_is_stable_hex_string(self):
        """DeviceID MUST be a stable hex identifier."""
        adapter = _make_adapter(_make_channels("HBO"))
        result = adapter.discover()

        device_id = result["DeviceID"]
        assert isinstance(device_id, str), "DeviceID must be a string"
        assert len(device_id) >= 8, "DeviceID must be at least 8 characters"
        # Hex check — must be valid hexadecimal
        try:
            int(device_id, 16)
        except ValueError:
            pytest.fail(
                f"INV-PLEX-DISCOVERY-001 violated: DeviceID '{device_id}' is not valid hex"
            )

    def test_device_id_stable_across_calls(self):
        """DeviceID MUST be identical across consecutive discover() calls."""
        adapter = _make_adapter(_make_channels("HBO"))
        id1 = adapter.discover()["DeviceID"]
        id2 = adapter.discover()["DeviceID"]

        assert id1 == id2, (
            "INV-PLEX-DISCOVERY-001 violated: DeviceID changed between calls"
        )

    def test_lineup_url_points_to_adapter_lineup(self):
        """LineupURL MUST reference the adapter's own /lineup.json."""
        adapter = _make_adapter(
            _make_channels("HBO"), base_url="http://192.168.1.50:8000"
        )
        result = adapter.discover()

        assert result["LineupURL"].endswith("/lineup.json"), (
            f"INV-PLEX-DISCOVERY-001 violated: LineupURL '{result['LineupURL']}' "
            f"does not end with /lineup.json"
        )

    def test_discover_no_hardware_fiction_fields(self):
        """Response MUST NOT include fields implying physical hardware."""
        adapter = _make_adapter(_make_channels("HBO"))
        result = adapter.discover()

        forbidden = {"FirmwareVersion", "FirmwareName", "ModelNumber", "HardwareModel"}
        present = forbidden & set(result.keys())
        assert not present, (
            f"INV-PLEX-DISCOVERY-001 violated: hardware fiction fields present: {present}"
        )

    def test_discover_empty_channel_list(self):
        """TunerCount MUST be 0 when no channels are registered."""
        adapter = _make_adapter([])
        result = adapter.discover()

        assert result["TunerCount"] == 0

    # -------------------------------------------------------------------
    # INV-PLEX-TUNER-STATUS-001
    # -------------------------------------------------------------------

    def test_tuner_status_scan_not_in_progress(self):
        """ScanInProgress MUST be 0 — no physical scan exists."""
        adapter = _make_adapter(_make_channels("HBO"))
        result = adapter.lineup_status()

        assert result["ScanInProgress"] == 0, (
            "INV-PLEX-TUNER-STATUS-001 violated: ScanInProgress != 0"
        )

    def test_tuner_status_scan_possible(self):
        """ScanPossible MUST be 1 — Plex requires this for device functionality."""
        adapter = _make_adapter(_make_channels("HBO"))
        result = adapter.lineup_status()

        assert result["ScanPossible"] == 1, (
            "INV-PLEX-TUNER-STATUS-001 violated: ScanPossible != 1"
        )

    def test_tuner_status_source_is_cable(self):
        """Source MUST be 'Cable'."""
        adapter = _make_adapter(_make_channels("HBO"))
        result = adapter.lineup_status()

        assert result["Source"] == "Cable", (
            f"INV-PLEX-TUNER-STATUS-001 violated: Source='{result['Source']}', expected 'Cable'"
        )

    def test_tuner_status_invariant_across_channel_counts(self):
        """Response MUST NOT change based on channel count or viewer state."""
        status_0 = _make_adapter([]).lineup_status()
        status_3 = _make_adapter(_make_channels("A", "B", "C")).lineup_status()

        assert status_0 == status_3, (
            "INV-PLEX-TUNER-STATUS-001 violated: status changed with channel count"
        )
