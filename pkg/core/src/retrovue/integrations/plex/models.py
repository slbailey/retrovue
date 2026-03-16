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

# Stable device identifier — derived from project name hash.
# INV-HDHOMERUN-COMPAT-001-R1: DeviceID MUST be 8 uppercase hex chars, unique.
_DEFAULT_DEVICE_ID = "52565545"  # hex("RVUE"[0:4] ascii codes)
_DEFAULT_FRIENDLY_NAME = "RetroVue"


def make_discover_payload(
    *,
    base_url: str,
    tuner_count: int,
    device_id: str = _DEFAULT_DEVICE_ID,
    friendly_name: str = _DEFAULT_FRIENDLY_NAME,
) -> dict[str, Any]:
    """Build an HDHomeRun /discover.json response.

    INV-HDHOMERUN-COMPAT-001-R1: MUST include Manufacturer=Silicondust,
    ModelNumber, FirmwareName, FirmwareVersion so Plex identifies the
    device as a native HDHomeRun CONNECT tuner.
    """
    return {
        "FriendlyName": friendly_name,
        "Manufacturer": "Silicondust",
        "ModelNumber": "HDHR5-4US",
        "FirmwareName": "hdhomerun5_atsc",
        "FirmwareVersion": "20210210",
        "DeviceID": device_id,
        "DeviceAuth": "retrovue",
        "BaseURL": base_url.rstrip("/"),
        "LineupURL": f"{base_url.rstrip('/')}/lineup.json",
        "TunerCount": tuner_count,
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
    GuideName from display name, URL from /channel/{id}.ts (canonical id).
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
