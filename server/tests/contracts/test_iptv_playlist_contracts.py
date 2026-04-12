"""
IPTV Playlist Contract Tests

Invariants:
    INV-IPTV-M3U-COMPLETE-001:
        Every configured channel MUST appear in the M3U playlist with
        tvg-id, tvg-name, tvg-chno, group-title, and a valid stream URL.

    INV-IPTV-XMLTV-COMPLETE-001:
        Every configured channel MUST have a <channel> element in the
        XMLTV output. Every EPG entry MUST produce a <programme> element
        with valid XMLTV timestamps and required fields.

    INV-IPTV-M3U-FORMAT-001:
        M3U output MUST start with #EXTM3U header and each entry MUST
        follow the #EXTINF + URL two-line pattern.

    INV-IPTV-XMLTV-FORMAT-001:
        XMLTV output MUST be well-formed XML with proper timestamp format
        (YYYYMMDDHHmmss +/-HHMM).
"""

import re
import xml.etree.ElementTree as ET

import pytest


# ---------------------------------------------------------------------------
# Fixtures: synthetic channel + EPG data (no database, no YAML files)
# ---------------------------------------------------------------------------

FAKE_CHANNELS = [
    {
        "channel_id": "test-network",
        "channel_id_int": 3,
        "name": "Test Network",
        "schedule_config": {"channel_type": "network"},
    },
    {
        "channel_id": "test-movies",
        "channel_id_int": 7,
        "name": "Test Movies",
        "schedule_config": {"channel_type": "movie"},
    },
]

FAKE_EPG_ENTRIES = [
    {
        "channel_id": "test-network",
        "channel_name": "Test Network",
        "start_time": "2026-03-06T06:00:00",
        "end_time": "2026-03-06T06:30:00",
        "title": "Cheers",
        "episode_title": "Give Me a Ring Sometime",
        "season": 1,
        "episode": 1,
        "description": "Sam meets Diane.",
        "duration_minutes": 24.5,
        "slot_minutes": 30.0,
        "display_duration": None,
    },
    {
        "channel_id": "test-movies",
        "channel_name": "Test Movies",
        "start_time": "2026-03-06T20:00:00",
        "end_time": "2026-03-06T22:00:00",
        "title": "Die Hard",
        "episode_title": "",
        "season": None,
        "episode": None,
        "description": "An NYPD officer tries to save hostages.",
        "duration_minutes": 112.0,
        "slot_minutes": 120.0,
        "display_duration": "1h 52m",
    },
]


# ===========================================================================
# INV-IPTV-M3U-COMPLETE-001
# ===========================================================================


class TestInvIptvM3uComplete001:
    """Every configured channel appears in M3U with correct attributes."""

    def test_all_channels_present(self):
        """TM3U-C-001: M3U contains an entry for every channel."""
        from retrovue.web.iptv import generate_m3u

        m3u = generate_m3u(FAKE_CHANNELS, base_url="http://localhost:8000")

        for ch in FAKE_CHANNELS:
            assert ch["channel_id"] in m3u, (
                f"Channel {ch['channel_id']} missing from M3U"
            )

    def test_tvg_attributes_present(self):
        """TM3U-C-002: Each entry has tvg-id, tvg-name, tvg-chno, group-title."""
        from retrovue.web.iptv import generate_m3u

        m3u = generate_m3u(FAKE_CHANNELS, base_url="http://localhost:8000")

        for ch in FAKE_CHANNELS:
            assert f'tvg-id="{ch["channel_id"]}"' in m3u
            assert f'tvg-name="{ch["name"]}"' in m3u
            assert f'tvg-chno="{ch["channel_id_int"]}"' in m3u

    def test_stream_urls_correct(self):
        """TM3U-C-003: Stream URLs point to the IPTV channel .ts endpoint."""
        from retrovue.web.iptv import generate_m3u

        m3u = generate_m3u(FAKE_CHANNELS, base_url="http://localhost:8000")

        for ch in FAKE_CHANNELS:
            expected_url = f"http://localhost:8000/channel/{ch['channel_id']}.ts"
            assert expected_url in m3u

    def test_group_title_maps_channel_type(self):
        """TM3U-C-004: group-title reflects channel_type (Network vs Movies)."""
        from retrovue.web.iptv import generate_m3u

        m3u = generate_m3u(FAKE_CHANNELS, base_url="http://localhost:8000")

        assert 'group-title="Network"' in m3u
        assert 'group-title="Movies"' in m3u

    def test_channels_sorted_by_number(self):
        """TM3U-C-005: Channels appear in channel number order."""
        from retrovue.web.iptv import generate_m3u

        m3u = generate_m3u(FAKE_CHANNELS, base_url="http://localhost:8000")
        lines = m3u.strip().split("\n")

        # Extract tvg-chno values in order
        chno_pattern = re.compile(r'tvg-chno="(\d+)"')
        channel_numbers = []
        for line in lines:
            match = chno_pattern.search(line)
            if match:
                channel_numbers.append(int(match.group(1)))

        assert channel_numbers == sorted(channel_numbers), (
            f"Channels not sorted by number: {channel_numbers}"
        )


# ===========================================================================
# INV-IPTV-M3U-FORMAT-001
# ===========================================================================


class TestInvIptvM3uFormat001:
    """M3U output is valid extended M3U format."""

    def test_starts_with_extm3u_header(self):
        """TM3U-F-001: Output starts with #EXTM3U."""
        from retrovue.web.iptv import generate_m3u

        m3u = generate_m3u(FAKE_CHANNELS, base_url="http://localhost:8000")

        assert m3u.startswith("#EXTM3U\n")

    def test_extinf_url_pairs(self):
        """TM3U-F-002: Each entry is an #EXTINF line followed by a URL line."""
        from retrovue.web.iptv import generate_m3u

        m3u = generate_m3u(FAKE_CHANNELS, base_url="http://localhost:8000")
        lines = m3u.strip().split("\n")

        # Skip header
        body_lines = lines[1:]
        assert len(body_lines) == len(FAKE_CHANNELS) * 2, (
            f"Expected {len(FAKE_CHANNELS) * 2} body lines, got {len(body_lines)}"
        )

        for i in range(0, len(body_lines), 2):
            assert body_lines[i].startswith("#EXTINF:"), (
                f"Line {i+1} should be #EXTINF, got: {body_lines[i]}"
            )
            assert body_lines[i + 1].startswith("http"), (
                f"Line {i+2} should be URL, got: {body_lines[i + 1]}"
            )

    def test_empty_channels_produces_header_only(self):
        """TM3U-F-003: No channels produces just the #EXTM3U header."""
        from retrovue.web.iptv import generate_m3u

        m3u = generate_m3u([], base_url="http://localhost:8000")

        assert m3u.strip() == "#EXTM3U"


# ===========================================================================
# INV-IPTV-XMLTV-COMPLETE-001
# ===========================================================================


class TestInvIptvXmltvComplete001:
    """XMLTV contains channel and programme elements for all data."""

    def test_all_channels_have_channel_element(self):
        """TXMLTV-C-001: Every configured channel has a <channel> element."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        channel_ids = {el.get("id") for el in root.findall("channel")}
        for ch in FAKE_CHANNELS:
            assert ch["channel_id"] in channel_ids, (
                f"Channel {ch['channel_id']} missing from XMLTV"
            )

    def test_channel_display_name(self):
        """TXMLTV-C-002: <channel> elements contain correct <display-name>."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        for ch in FAKE_CHANNELS:
            el = root.find(f"channel[@id='{ch['channel_id']}']")
            assert el is not None
            display_name = el.findtext("display-name")
            assert display_name == ch["name"]

    def test_all_epg_entries_have_programme(self):
        """TXMLTV-C-003: Every EPG entry produces a <programme> element."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        programmes = root.findall("programme")
        assert len(programmes) == len(FAKE_EPG_ENTRIES)

    def test_programme_has_title(self):
        """TXMLTV-C-004: Every <programme> has a <title>."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        for prog in root.findall("programme"):
            title = prog.findtext("title")
            assert title and len(title) > 0

    def test_programme_channel_matches(self):
        """TXMLTV-C-005: <programme> channel attr matches EPG entry channel_id."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        prog_channels = {p.get("channel") for p in root.findall("programme")}
        epg_channels = {e["channel_id"] for e in FAKE_EPG_ENTRIES}
        assert prog_channels == epg_channels


# ===========================================================================
# INV-IPTV-XMLTV-FORMAT-001
# ===========================================================================


class TestInvIptvXmltvFormat001:
    """XMLTV output is well-formed XML with proper timestamp format."""

    XMLTV_TS_PATTERN = re.compile(r"^\d{14} [+-]\d{4}$")

    def test_wellformed_xml(self):
        """TXMLTV-F-001: Output is parseable XML."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        # Will raise if not well-formed
        ET.fromstring(xml_str)

    def test_root_element_is_tv(self):
        """TXMLTV-F-002: Root element is <tv>."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)
        assert root.tag == "tv"

    def test_timestamp_format(self):
        """TXMLTV-F-003: start/stop use XMLTV timestamp format."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        for prog in root.findall("programme"):
            start = prog.get("start")
            stop = prog.get("stop")
            assert self.XMLTV_TS_PATTERN.match(start), (
                f"Invalid start timestamp: {start}"
            )
            assert self.XMLTV_TS_PATTERN.match(stop), (
                f"Invalid stop timestamp: {stop}"
            )

    def test_episode_num_xmltv_ns(self):
        """TXMLTV-F-004: Episodes with season/episode use xmltv_ns numbering."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        # Find the programme for Cheers (has season=1, episode=1)
        for prog in root.findall("programme"):
            if prog.findtext("title") == "Cheers":
                ep_num = prog.find("episode-num[@system='xmltv_ns']")
                assert ep_num is not None, "Missing episode-num for episodic content"
                # xmltv_ns is 0-indexed: season 1, episode 1 → "0.0."
                assert ep_num.text == "0.0."

    def test_movie_no_episode_num(self):
        """TXMLTV-F-005: Movies (no season/episode) omit episode-num."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        for prog in root.findall("programme"):
            if prog.findtext("title") == "Die Hard":
                ep_num = prog.find("episode-num")
                assert ep_num is None, "Movie should not have episode-num"

    def test_sub_title_present_when_available(self):
        """TXMLTV-F-006: <sub-title> is present when episode_title exists."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, FAKE_EPG_ENTRIES)
        root = ET.fromstring(xml_str)

        for prog in root.findall("programme"):
            if prog.findtext("title") == "Cheers":
                sub_title = prog.findtext("sub-title")
                assert sub_title == "Give Me a Ring Sometime"

    def test_empty_epg_produces_channels_only(self):
        """TXMLTV-F-007: No EPG entries produces channel elements but no programmes."""
        from retrovue.web.iptv import generate_xmltv

        xml_str = generate_xmltv(FAKE_CHANNELS, [])
        root = ET.fromstring(xml_str)

        assert len(root.findall("channel")) == len(FAKE_CHANNELS)
        assert len(root.findall("programme")) == 0
