"""
Plex HDHomeRun virtual tuner — data models.

INV-HDHOMERUN-COMPAT-001: RetroVue presents as an HDHomeRun CONNECT device.
Plex only supports HDHomeRun-compatible tuners for Live TV.

Pure data structures for HDHomeRun protocol responses.
No business logic. No I/O.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# /discover.json
# ---------------------------------------------------------------------------

# Stable device identifier.
_DEFAULT_DEVICE_ID = "RVUE1234"
_DEFAULT_FRIENDLY_NAME = "RetroVue"
_DEFAULT_TUNER_COUNT = 8


def make_discover_payload(
    *,
    base_url: str,
    tuner_count: int | None = None,
    device_id: str = _DEFAULT_DEVICE_ID,
    friendly_name: str = _DEFAULT_FRIENDLY_NAME,
) -> dict[str, Any]:
    """Build an HDHomeRun /discover.json response.

    INV-HDHOMERUN-COMPAT-001-R1: MUST include Manufacturer, ModelNumber,
    FirmwareName, FirmwareVersion so Plex identifies the device as a
    compatible HDHomeRun tuner.
    """
    return {
        "FriendlyName": friendly_name,
        "Manufacturer": "RetroVue",
        "ModelNumber": "HDTC-2US",
        "FirmwareName": "hdhomerun_atsc",
        "FirmwareVersion": "20200101",
        "DeviceID": device_id,
        "DeviceAuth": "test",
        "BaseURL": base_url.rstrip("/"),
        "LineupURL": f"{base_url.rstrip('/')}/lineup.json",
        "TunerCount": tuner_count if tuner_count is not None else _DEFAULT_TUNER_COUNT,
    }


# ---------------------------------------------------------------------------
# /lineup.json
# ---------------------------------------------------------------------------


def make_lineup_entry(
    *,
    channel_id: str,
    channel_name: str,
    base_url: str,
    guide_number: int | None = None,
    hd: bool = True,
) -> dict[str, Any]:
    """Build a single HDHomeRun lineup entry.

    INV-PLEX-LINEUP-001: GuideNumber from channel config number (Plex-facing),
    GuideName from display name, URL from /channels/{id}/live.m3u8 (canonical HLS).
    INV-HDHOMERUN-COMPAT-001-R2: URLs MUST use externally-reachable address.
    """
    num = guide_number if guide_number is not None else channel_id
    entry: dict[str, Any] = {
        "GuideNumber": str(num) if isinstance(num, int) else str(num),
        "GuideName": channel_name,
        "URL": f"{base_url.rstrip('/')}/channel/{channel_id}.ts",
    }
    if hd:
        entry["HD"] = 1
    return entry


# ---------------------------------------------------------------------------
# /lineup_status.json
# ---------------------------------------------------------------------------

# INV-PLEX-TUNER-STATUS-001: Static payload — no scan, always ready.
LINEUP_STATUS = {
    "ScanInProgress": 0,
    "ScanPossible": 1,
    "Source": "Cable",
    "SourceList": ["Cable"],
}
