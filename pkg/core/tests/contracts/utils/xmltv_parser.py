"""
Parse XMLTV document for contract tests.

Provides a public-interface-only way to extract channels and programme
entries from XMLTV XML. Used by XMLTV and EPG contract tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET


@dataclass
class XmltvChannel:
    """Parsed <channel> element."""

    id: str
    display_name: str | None


@dataclass
class XmltvProgramme:
    """Parsed <programme> element with start/stop as comparable values."""

    channel: str
    start: str  # XMLTV format YYYYMMDDHHMMSS ±HHMM
    stop: str
    start_parsed: int  # epoch seconds for ordering/gap checks
    stop_parsed: int
    title: str | None = None


def _parse_xmltv_timestamp(ts: str) -> int:
    """Convert XMLTV timestamp to epoch seconds for comparison.

    Format: YYYYMMDDHHMMSS ±HHMM
    """
    # Optional space before offset
    parts = re.split(r"\s+", ts.strip(), 1)
    if len(parts) != 2:
        raise ValueError(f"XMLTV time format invariant violated: timestamp must include timezone offset: {ts!r}")
    dt_part, offset_part = parts[0], parts[1]
    if len(dt_part) != 14:
        raise ValueError(f"XMLTV time format invariant violated: date part must be 14 digits: {dt_part!r}")
    from datetime import datetime, timezone, timedelta

    year = int(dt_part[0:4])
    month = int(dt_part[4:6])
    day = int(dt_part[6:8])
    hour = int(dt_part[8:10])
    minute = int(dt_part[10:12])
    second = int(dt_part[12:14])
    sign = 1 if offset_part.startswith("+") else -1
    oh = int(offset_part[1:3])
    om = int(offset_part[3:5])
    tz = timezone(timedelta(minutes=sign * (oh * 60 + om)))
    dt = datetime(year, month, day, hour, minute, second, tzinfo=tz)
    return int(dt.timestamp())


def parse_xmltv(xml_str: str) -> tuple[list[XmltvChannel], list[XmltvProgramme]]:
    """Parse XMLTV XML and return channels and programmes.

    Returns:
        (channels, programmes) for use in contract assertions.
    """
    root = ET.fromstring(xml_str)
    if root.tag != "tv":
        raise ValueError(
            f"XMLTV structure invariant violated: root element must be <tv>, got <{root.tag}>"
        )

    channels: list[XmltvChannel] = []
    for ch in root.findall("channel"):
        ch_id = ch.get("id")
        if ch_id is None:
            raise ValueError("XMLTV channel identity invariant violated: <channel> missing id")
        dn = ch.find("display-name")
        channels.append(
            XmltvChannel(
                id=ch_id,
                display_name=dn.text if dn is not None and dn.text else None,
            )
        )

    programmes: list[XmltvProgramme] = []
    for prog in root.findall("programme"):
        channel = prog.get("channel")
        start = prog.get("start")
        stop = prog.get("stop")
        if not channel or not start or not stop:
            raise ValueError(
                "XMLTV programme invariant violated: programme must have channel, start, stop"
            )
        try:
            start_parsed = _parse_xmltv_timestamp(start)
            stop_parsed = _parse_xmltv_timestamp(stop)
        except ValueError as e:
            raise ValueError(f"XMLTV time format invariant violated: {e}") from e
        title_el = prog.find("title")
        programmes.append(
            XmltvProgramme(
                channel=channel,
                start=start,
                stop=stop,
                start_parsed=start_parsed,
                stop_parsed=stop_parsed,
                title=title_el.text if title_el is not None and title_el.text else None,
            )
        )

    return channels, programmes


def programmes_by_channel(programmes: list[XmltvProgramme]) -> dict[str, list[XmltvProgramme]]:
    """Group programmes by channel id. Returns dict channel_id -> list of programmes (unsorted)."""
    by_ch: dict[str, list[XmltvProgramme]] = {}
    for p in programmes:
        by_ch.setdefault(p.channel, []).append(p)
    return by_ch
