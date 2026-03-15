"""
Contract tests for Plex HDHomeRun virtual tuner discovery.

Verifies:
  INV-PLEX-DISCOVERY-001 — /discover.json payload correctness
  INV-PLEX-TUNER-STATUS-001 — /lineup_status.json scan state
  Plex Compatibility Interface — discovery endpoint behavior
"""

import json
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

    Includes number (Plex GuideNumber); uses 100+index for stable numeric IDs.
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
# INV-PLEX-DISCOVERY-001
# ---------------------------------------------------------------------------


def _make_http_client(adapter: PlexAdapter) -> TestClient:
    """Public interface: HTTP client for Plex endpoints."""
    app = FastAPI()
    app.include_router(create_plex_router(adapter))
    return TestClient(app)


class TestPlexDiscovery:
    """INV-PLEX-DISCOVERY-001 contract tests."""

    REQUIRED_FIELDS = {"FriendlyName", "DeviceID", "BaseURL", "LineupURL", "TunerCount"}

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

    def test_discover_includes_base_url(self):
        """Discovery MUST include BaseURL (Plex Compatibility Interface)."""
        adapter = _make_adapter(_make_channels("HBO"), base_url="http://192.168.1.50:8000")
        result = adapter.discover()
        assert "BaseURL" in result, (
            "Plex discovery invariant violated: /discover.json missing BaseURL"
        )
        assert result["BaseURL"] == "http://192.168.1.50:8000", (
            f"BaseURL must match adapter base: got {result['BaseURL']!r}"
        )

    # -------------------------------------------------------------------
    # HTTP endpoint behavior (public interface)
    # -------------------------------------------------------------------

    def test_discover_endpoint_returns_200(self):
        """Endpoint MUST return HTTP 200 (Plex Compatibility Interface)."""
        adapter = _make_adapter(_make_channels("HBO"))
        client = _make_http_client(adapter)
        response = client.get("/discover.json")
        assert response.status_code == 200, (
            f"Plex discovery invariant violated: expected HTTP 200, got {response.status_code}"
        )

    def test_discover_endpoint_returns_valid_json(self):
        """Response MUST be valid JSON (Plex Compatibility Interface)."""
        adapter = _make_adapter(_make_channels("HBO"))
        client = _make_http_client(adapter)
        response = client.get("/discover.json")
        assert response.status_code == 200
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise AssertionError(
                f"Plex discovery invariant violated: response is not valid JSON: {e}"
            ) from e
        assert isinstance(data, dict)

    def test_discover_endpoint_has_all_required_fields(self):
        """Response MUST contain FriendlyName, DeviceID, BaseURL, LineupURL, TunerCount."""
        adapter = _make_adapter(_make_channels("HBO", "CNN"))
        client = _make_http_client(adapter)
        response = client.get("/discover.json")
        assert response.status_code == 200
        data = response.json()
        missing = TestPlexDiscovery.REQUIRED_FIELDS - set(data.keys())
        assert not missing, (
            f"Plex discovery invariant violated: /discover.json missing fields: {missing}"
        )

    def test_discover_tuner_count_at_least_one_when_channels_exist(self):
        """TunerCount MUST be >= 1 when channels are registered (Plex Compatibility Interface)."""
        adapter = _make_adapter(_make_channels("HBO"))
        client = _make_http_client(adapter)
        response = client.get("/discover.json")
        assert response.status_code == 200
        data = response.json()
        assert data["TunerCount"] >= 1, (
            "Plex discovery invariant violated: TunerCount must be >= 1 when channels exist"
        )

    def test_discover_device_id_stable_across_requests(self):
        """DeviceID MUST remain stable across repeated requests (stable device identity invariant)."""
        adapter = _make_adapter(_make_channels("HBO"))
        client = _make_http_client(adapter)
        r1 = client.get("/discover.json")
        r2 = client.get("/discover.json")
        assert r1.status_code == 200 and r2.status_code == 200
        id1 = r1.json().get("DeviceID")
        id2 = r2.json().get("DeviceID")
        assert id1 == id2, (
            "Plex stable device identity invariant violated: DeviceID changed across requests"
        )

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
