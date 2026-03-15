"""
IPTV playlist generation — M3U and XMLTV.

Pure functions that accept channel configs and EPG entries (dicts)
and return formatted strings. No I/O, no database access.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo
from xml.etree.ElementTree import Element, SubElement, tostring

# Station timezone for XMLTV: Plex expects local time + offset (contract: no UTC-only).
_DEFAULT_STATION_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# M3U generation
# ---------------------------------------------------------------------------

_GROUP_TITLE_MAP = {
    "network": "Network",
    "movie": "Movies",
}


def generate_m3u(channels: list[dict[str, Any]], *, base_url: str) -> str:
    """Generate an extended M3U playlist for IPTV clients.

    Channels are sorted by channel number (tvg-chno).
    """
    base_url = base_url.rstrip("/")
    sorted_channels = sorted(channels, key=lambda c: c.get("channel_id_int", 0))

    lines = ["#EXTM3U"]
    for ch in sorted_channels:
        ch_id = ch["channel_id"]
        ch_name = ch["name"]
        ch_num = ch.get("channel_id_int", 0)
        ch_type = ch.get("schedule_config", {}).get("channel_type", "network")
        group = _GROUP_TITLE_MAP.get(ch_type, ch_type.title())

        extinf = (
            f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{ch_name}" '
            f'tvg-chno="{ch_num}" group-title="{group}",{ch_name}'
        )
        url = f"{base_url}/channel/{ch_id}.ts"
        lines.append(extinf)
        lines.append(url)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# XMLTV generation
# ---------------------------------------------------------------------------


def _xmltv_timestamp(iso_str: str, station_tz: ZoneInfo = _DEFAULT_STATION_TZ) -> str:
    """Convert ISO 8601 datetime to XMLTV format in station local time.

    Plex requires local station time with offset (not UTC-only). Converts
    the given time to the station timezone so "now" matches programme windows.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(station_tz)
    offset = local_dt.strftime("%z")  # e.g. -0400 or +0000
    return local_dt.strftime("%Y%m%d%H%M%S") + " " + offset


def _channel_number(ch: dict[str, Any]) -> int:
    """External channel number for XMLTV (Plex GuideNumber). Prefer number over channel_id_int."""
    return ch.get("number", ch.get("channel_id_int", 0))


def generate_xmltv(
    channels: list[dict[str, Any]],
    epg_entries: list[dict[str, Any]],
    base_url: str | None = None,
) -> str:
    """Generate XMLTV guide XML from channel configs and EPG entries.

    Invariant: XMLTV <channel id> and <programme channel> use the same channel number
    as Plex GuideNumber, so lineup and guide mapping is consistent. Example:

      <channel id="101">
        <display-name>Cheers 24/7</display-name>
        <icon src="http://server/art/channel/cheers-24-7.jpg"/>
      </channel>
      <programme start="20260314180000 -0400" stop="20260314183000 -0400" channel="101">
        <icon src="http://server/art/program/{asset_id}.jpg"/>
    """
    tv = Element("tv", attrib={
        "generator-info-name": "RetroVue",
        "generator-info-url": "",
    })

    base = (base_url or "").rstrip("/")

    # channel_id -> number for programme channel attribute
    channel_id_to_number: dict[str, str] = {
        ch["channel_id"]: str(_channel_number(ch)) for ch in channels
    }

    # <channel> elements: id is the external channel number (Plex GuideNumber)
    for ch in sorted(channels, key=_channel_number):
        num_str = str(_channel_number(ch))
        chan_el = SubElement(tv, "channel", attrib={"id": num_str})
        dn = SubElement(chan_el, "display-name")
        dn.text = ch["name"]
        if base:
            SubElement(chan_el, "icon", attrib={"src": f"{base}/art/channel/{ch['channel_id']}.jpg"})

    # XMLTV chronological ordering: programmes by channel then start time
    sorted_entries = sorted(
        epg_entries,
        key=lambda e: (e["channel_id"], e["start_time"]),
    )

    # <programme> elements: channel is the external number (matches <channel id>)
    for entry in sorted_entries:
        ch_id = entry["channel_id"]
        prog_channel = channel_id_to_number.get(ch_id, ch_id)
        prog = SubElement(tv, "programme", attrib={
            "start": _xmltv_timestamp(entry["start_time"]),
            "stop": _xmltv_timestamp(entry["end_time"]),
            "channel": prog_channel,
        })

        title_el = SubElement(prog, "title")
        title_el.text = entry.get("title", "")

        if base and entry.get("asset_id"):
            SubElement(prog, "icon", attrib={"src": f"{base}/art/program/{entry['asset_id']}.jpg"})

        episode_title = entry.get("episode_title", "")
        if episode_title:
            sub_el = SubElement(prog, "sub-title")
            sub_el.text = episode_title

        desc = entry.get("description", "")
        if desc:
            desc_el = SubElement(prog, "desc")
            desc_el.text = desc

        season = entry.get("season")
        episode = entry.get("episode")
        if season is not None and episode is not None:
            ep_num = SubElement(prog, "episode-num", system="xmltv_ns")
            # xmltv_ns is 0-indexed: S1E1 → "0.0."
            ep_num.text = f"{season - 1}.{episode - 1}."

    return tostring(tv, encoding="unicode", xml_declaration=False)
