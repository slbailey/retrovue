"""
IPTV playlist generation — M3U and XMLTV.

Pure functions that accept channel configs and EPG entries (dicts)
and return formatted strings. No I/O, no database access.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring


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


def _xmltv_timestamp(iso_str: str) -> str:
    """Convert ISO 8601 datetime string to XMLTV timestamp format.

    Input:  2026-03-06T06:00:00
    Output: 20260306060000 +0000

    Naive datetimes are assumed UTC.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        offset = dt.strftime("%z")
        # Ensure +HHMM format (strftime gives +HHMM already)
    else:
        offset = "+0000"
    return dt.strftime("%Y%m%d%H%M%S") + " " + offset


def generate_xmltv(
    channels: list[dict[str, Any]],
    epg_entries: list[dict[str, Any]],
) -> str:
    """Generate XMLTV guide XML from channel configs and EPG entries."""
    tv = Element("tv", attrib={
        "generator-info-name": "RetroVue",
        "generator-info-url": "",
    })

    # <channel> elements
    for ch in sorted(channels, key=lambda c: c.get("channel_id_int", 0)):
        chan_el = SubElement(tv, "channel", id=ch["channel_id"])
        dn = SubElement(chan_el, "display-name")
        dn.text = ch["name"]

    # <programme> elements
    for entry in epg_entries:
        prog = SubElement(tv, "programme", attrib={
            "start": _xmltv_timestamp(entry["start_time"]),
            "stop": _xmltv_timestamp(entry["end_time"]),
            "channel": entry["channel_id"],
        })

        title_el = SubElement(prog, "title")
        title_el.text = entry.get("title", "")

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
