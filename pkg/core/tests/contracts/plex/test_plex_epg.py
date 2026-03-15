"""
Contract tests for Plex XMLTV guide exposure.

Verifies:
  INV-PLEX-XMLTV-001 — /epg.xml structure validity and delegation
"""

from xml.etree.ElementTree import fromstring as xml_parse

import pytest

from retrovue.integrations.plex.adapter import PlexAdapter
from retrovue.web.iptv import generate_xmltv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channels(*names: str) -> list[dict]:
    """Build minimal channel dicts matching ProgramDirector._load_channels_list format.

    Includes number for Plex/XMLTV channel id (GuideNumber).
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


def _make_epg_entries(channel_id: str, count: int = 3) -> list[dict]:
    """Build minimal EPG entry dicts."""
    entries = []
    for i in range(count):
        hour = 6 + i
        entries.append({
            "channel_id": channel_id,
            "title": f"Program {i + 1}",
            "start_time": f"2026-03-10T{hour:02d}:00:00",
            "end_time": f"2026-03-10T{hour + 1:02d}:00:00",
        })
    return entries


def _make_adapter(
    channels: list[dict],
    epg_entries: list[dict] | None = None,
    *,
    base_url: str = "http://192.168.1.50:8000",
) -> PlexAdapter:
    if epg_entries is None:
        epg_entries = []
    return PlexAdapter(channels=channels, epg_entries=epg_entries, base_url=base_url)


# ---------------------------------------------------------------------------
# INV-PLEX-XMLTV-001
# ---------------------------------------------------------------------------


class TestPlexEPG:
    """INV-PLEX-XMLTV-001 contract tests."""

    def test_epg_xml_is_well_formed(self):
        """Response MUST be well-formed XML."""
        channels = _make_channels("HBO")
        epg = _make_epg_entries("hbo", 2)
        adapter = _make_adapter(channels, epg)

        xml_str = adapter.epg_xml()
        try:
            xml_parse(xml_str)
        except Exception as e:
            pytest.fail(
                f"INV-PLEX-XMLTV-001 violated: epg_xml() returned malformed XML: {e}"
            )

    def test_epg_xml_has_tv_root_element(self):
        """Root element MUST be <tv>."""
        channels = _make_channels("HBO")
        adapter = _make_adapter(channels, _make_epg_entries("hbo"))

        root = xml_parse(adapter.epg_xml())
        assert root.tag == "tv", (
            f"INV-PLEX-XMLTV-001 violated: root element is <{root.tag}>, expected <tv>"
        )

    def test_epg_xml_contains_channel_elements(self):
        """XMLTV MUST contain a <channel> element for each registered channel."""
        channels = _make_channels("HBO", "CNN")
        adapter = _make_adapter(channels)

        root = xml_parse(adapter.epg_xml())
        channel_els = root.findall("channel")

        assert len(channel_els) == len(channels), (
            f"INV-PLEX-XMLTV-001 violated: {len(channel_els)} <channel> elements "
            f"but {len(channels)} channels registered"
        )

    def test_epg_xml_channel_ids_match_lineup_guide_numbers(self):
        """Channel IDs in XMLTV MUST match GuideNumber from /lineup.json.

        Both use the configured channel number (Plex-facing external ID).
        """
        channels = _make_channels("HBO", "CNN")
        adapter = _make_adapter(channels)

        lineup = adapter.lineup()
        lineup_guide_numbers = {entry["GuideNumber"] for entry in lineup}

        root = xml_parse(adapter.epg_xml())
        xmltv_channel_ids = {el.get("id") for el in root.findall("channel")}

        assert xmltv_channel_ids, "INV-PLEX-XMLTV-001 violated: no channel IDs in XMLTV"
        assert lineup_guide_numbers, "INV-PLEX-LINEUP-001 violated: no GuideNumbers in lineup"

        # XMLTV <channel id> and lineup GuideNumber must both be the channel number
        assert xmltv_channel_ids == lineup_guide_numbers, (
            f"INV-PLEX-XMLTV-001 violated: XMLTV channel IDs {xmltv_channel_ids} "
            f"do not match lineup GuideNumbers {lineup_guide_numbers}"
        )

    def test_epg_xml_contains_programme_elements(self):
        """XMLTV MUST contain <programme> elements for EPG entries."""
        channels = _make_channels("HBO")
        epg = _make_epg_entries("hbo", 3)
        adapter = _make_adapter(channels, epg)

        root = xml_parse(adapter.epg_xml())
        programmes = root.findall("programme")

        assert len(programmes) == 3, (
            f"INV-PLEX-XMLTV-001 violated: expected 3 <programme> elements, "
            f"got {len(programmes)}"
        )

    def test_epg_xml_programme_has_start_stop_channel(self):
        """Each <programme> MUST have start, stop, and channel attributes."""
        channels = _make_channels("HBO")
        epg = _make_epg_entries("hbo", 1)
        adapter = _make_adapter(channels, epg)

        root = xml_parse(adapter.epg_xml())
        prog = root.find("programme")

        for attr in ("start", "stop", "channel"):
            assert prog.get(attr) is not None, (
                f"INV-PLEX-XMLTV-001 violated: <programme> missing '{attr}' attribute"
            )

    def test_epg_xml_delegates_to_generate_xmltv(self):
        """Adapter MUST produce identical output to generate_xmltv().

        This proves the adapter delegates rather than duplicating logic.
        """
        channels = _make_channels("HBO", "CNN")
        epg = _make_epg_entries("hbo", 2) + _make_epg_entries("cnn", 2)
        adapter = _make_adapter(channels, epg)

        adapter_xml = adapter.epg_xml()
        canonical_xml = generate_xmltv(channels, epg)

        assert adapter_xml == canonical_xml, (
            "INV-PLEX-XMLTV-001 violated: adapter epg_xml() output differs "
            "from generate_xmltv() — adapter MUST delegate, not duplicate"
        )

    def test_epg_xml_empty_schedule_still_valid(self):
        """XMLTV with no EPG entries MUST still be well-formed with <channel> elements."""
        channels = _make_channels("HBO")
        adapter = _make_adapter(channels, [])

        root = xml_parse(adapter.epg_xml())
        assert root.tag == "tv"
        assert len(root.findall("channel")) == 1
        assert len(root.findall("programme")) == 0

    def test_epg_xml_display_name_matches_channel_name(self):
        """<display-name> inside <channel> MUST match the channel's registry name."""
        channels = _make_channels("HBO Premium")
        adapter = _make_adapter(channels)

        root = xml_parse(adapter.epg_xml())
        channel_el = root.find("channel")
        display_name = channel_el.find("display-name").text

        assert display_name == "HBO Premium", (
            f"INV-PLEX-XMLTV-001 violated: display-name='{display_name}', "
            f"expected 'HBO Premium'"
        )
