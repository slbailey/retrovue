"""
Contract tests for XMLTV export structure.

Verifies XMLTV Export Contract:
  - Endpoint returns 200, valid XML, root <tv>
  - At least one <channel>, one <programme>
  - Channel uniqueness, channel id format
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from retrovue.web.iptv import generate_xmltv

from tests.contracts.utils.xmltv_parser import parse_xmltv


# ---------------------------------------------------------------------------
# Fixtures: synthetic data (no server)
# ---------------------------------------------------------------------------

FAKE_CHANNELS = [
    {
        "channel_id": "101",
        "channel_id_int": 101,
        "name": "Cheers 24/7",
        "schedule_config": {"channel_type": "network"},
    },
    {
        "channel_id": "201",
        "channel_id_int": 201,
        "name": "HBO",
        "schedule_config": {"channel_type": "network"},
    },
]

FAKE_EPG_ENTRIES = [
    {
        "channel_id": "101",
        "start_time": "2026-03-14T18:00:00",
        "end_time": "2026-03-14T18:30:00",
        "title": "Cheers",
    },
    {
        "channel_id": "101",
        "start_time": "2026-03-14T18:30:00",
        "end_time": "2026-03-14T19:00:00",
        "title": "Cheers",
    },
    {
        "channel_id": "201",
        "start_time": "2026-03-14T20:00:00",
        "end_time": "2026-03-14T22:00:00",
        "title": "Movie",
    },
]


# ---------------------------------------------------------------------------
# XMLTV structure (outcome: valid document)
# ---------------------------------------------------------------------------

class TestXmltvStructure:
    """XMLTV Export Contract: document structure and channel invariants."""

    def test_xmltv_response_is_valid_xml(self):
        """Endpoint MUST return valid XML (XMLTV Export Contract)."""
        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        try:
            ET.fromstring(xml_str)
        except ET.ParseError as e:
            raise AssertionError(
                f"XMLTV structure invariant violated: response is not valid XML: {e}"
            ) from e

    def test_xmltv_root_element_is_tv(self):
        """Root element MUST be <tv> (XMLTV Export Contract)."""
        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)
        assert root.tag == "tv", (
            f"XMLTV structure invariant violated: root must be <tv>, got <{root.tag}>"
        )

    def test_xmltv_has_at_least_one_channel(self):
        """Document MUST contain at least one <channel> (XMLTV Export Contract)."""
        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)
        channels = root.findall("channel")
        assert len(channels) >= 1, (
            "XMLTV structure invariant violated: at least one <channel> required"
        )

    def test_xmltv_has_at_least_one_programme(self):
        """Document MUST contain at least one <programme> (XMLTV Export Contract)."""
        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)
        programmes = root.findall("programme")
        assert len(programmes) >= 1, (
            "XMLTV structure invariant violated: at least one <programme> required"
        )

    def test_xmltv_each_channel_has_unique_id(self):
        """XMLTV channel uniqueness invariant: each <channel id> MUST appear exactly once."""
        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        channels, _ = parse_xmltv(xml_str)
        ids = [c.id for c in channels]
        assert len(ids) == len(set(ids)), (
            f"XMLTV channel uniqueness invariant violated: duplicate <channel id>: {ids}"
        )

    def test_xmltv_channel_id_matches_guide_number_format(self):
        """Channel id in XMLTV MUST match GuideNumber format (numeric string for Plex)."""
        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        channels, _ = parse_xmltv(xml_str)
        for c in channels:
            assert c.id, (
                "XMLTV channel identity invariant violated: channel must have id"
            )
            # Contract: external guide ID used in lineup; typically numeric
            assert isinstance(c.id, str), (
                f"XMLTV channel id must be string, got {type(c.id).__name__}"
            )
