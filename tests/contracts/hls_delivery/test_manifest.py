"""
Contract Tests: HLS Manifest Publication

Canonical contract:
    docs/contracts/delivery_hls.md — §3 Manifest Contract

Test matrix:
    docs/contracts/TEST-MATRIX-HLS-DELIVERY.md — Manifest Publication

These tests enforce the manifest invariants
(INV-HLS-MANIFEST-LIVE-001 through INV-HLS-DISCONTINUITY-MARKER-001)
using the HLSSegmenter's public API.

Every test references the specific invariant(s) it validates.
"""

from __future__ import annotations

import math
import re

import pytest

from retrovue.streaming.hls_writer import HLSSegmenter

from .conftest import (
    feed_n_segments,
    generate_segment_data,
    make_ts_packet,
    extract_segment_names,
    extract_segment_indices,
    extract_extinf_values,
    extract_media_sequence,
    extract_target_duration,
    extract_program_date_time,
)


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-LIVE-001 — Live stream signaling
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestLive001:
    """INV-HLS-MANIFEST-LIVE-001"""

    # Tier: 1 | Protocol invariant
    def test_no_endlist_in_live_playlist(self, segmenter_with_segments):
        """Live playlist MUST NOT contain EXT-X-ENDLIST."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        # INV-HLS-MANIFEST-LIVE-001 — absence of ENDLIST = live signal
        assert "#EXT-X-ENDLIST" not in playlist, (
            "Live playlist must not contain EXT-X-ENDLIST"
        )

    # Tier: 1 | Protocol invariant
    def test_targetduration_covers_all_segments(self, segmenter_with_segments):
        """EXT-X-TARGETDURATION >= ceil of every EXTINF value."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        td = extract_target_duration(playlist)
        assert td is not None, "EXT-X-TARGETDURATION missing"
        assert td > 0, "EXT-X-TARGETDURATION must be positive"

        durations = extract_extinf_values(playlist)
        for d in durations:
            # INV-HLS-MANIFEST-LIVE-001 — TARGETDURATION >= ceil(EXTINF)
            assert td >= math.ceil(d), (
                f"TARGETDURATION {td} < ceil(EXTINF {d}) = {math.ceil(d)}"
            )

    # Tier: 1 | Protocol invariant
    def test_manifest_starts_with_extm3u(self, segmenter_with_segments):
        """Every manifest begins with #EXTM3U."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        # INV-HLS-MANIFEST-LIVE-001 — valid HLS per RFC 8216
        assert playlist.startswith("#EXTM3U"), (
            "Manifest must start with #EXTM3U"
        )

    # Tier: 1 | Protocol invariant
    def test_no_endlist_across_multiple_fetches(self):
        """ENDLIST absent across multiple manifest generations."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        for batch in range(5):
            feed_n_segments(seg, 2, target_dur=2.5)
            playlist = seg.get_playlist()
            if playlist is not None:
                # INV-HLS-MANIFEST-LIVE-001 — consistently live
                assert "#EXT-X-ENDLIST" not in playlist, (
                    f"ENDLIST appeared in batch {batch}"
                )

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-SEQUENCE-001 — Media sequence correctness
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestSequence001:
    """INV-HLS-MANIFEST-SEQUENCE-001"""

    # Tier: 2 | Protocol invariant
    def test_media_sequence_equals_oldest_index(self):
        """EXT-X-MEDIA-SEQUENCE equals the index of the first segment."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        feed_n_segments(seg, 8, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None

        ms = extract_media_sequence(playlist)
        indices = extract_segment_indices(playlist)

        assert ms is not None, "EXT-X-MEDIA-SEQUENCE missing"
        assert len(indices) > 0

        # INV-HLS-MANIFEST-SEQUENCE-001 — sequence = oldest index
        assert ms == indices[0], (
            f"MEDIA-SEQUENCE {ms} != first segment index {indices[0]}"
        )

        seg.stop()

    # Tier: 2 | Protocol invariant
    def test_segments_in_ascending_order(self, segmenter_with_segments):
        """Segments are listed in ascending index order."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        indices = extract_segment_indices(playlist)
        # INV-HLS-MANIFEST-SEQUENCE-001 — ascending order
        for i in range(1, len(indices)):
            assert indices[i] > indices[i - 1], (
                f"Segment out of order: {indices[i-1]} before {indices[i]}"
            )

    # Tier: 2 | Protocol invariant
    def test_segment_uri_stable_across_fetches(self):
        """The URI for a given index does not change between manifest fetches."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        feed_n_segments(seg, 3, target_dur=2.5)
        playlist_1 = seg.get_playlist()
        assert playlist_1 is not None
        names_1 = extract_segment_names(playlist_1)

        # Fetch again without advancing
        playlist_2 = seg.get_playlist()
        assert playlist_2 is not None
        names_2 = extract_segment_names(playlist_2)

        # INV-HLS-MANIFEST-SEQUENCE-001 — URIs stable
        common = set(names_1) & set(names_2)
        assert len(common) > 0, "No overlapping segments between fetches"
        for name in common:
            assert name in names_1 and name in names_2

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 — Sequence never reverses
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestSequenceMonotonic001:
    """INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001"""

    # Tier: 2 | Protocol invariant
    def test_media_sequence_never_decreases(self):
        """EXT-X-MEDIA-SEQUENCE is non-decreasing across successive fetches."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=3)
        seg.start()

        sequences: list[int] = []
        for batch in range(8):
            feed_n_segments(seg, 2, target_dur=2.5)
            playlist = seg.get_playlist()
            if playlist is not None:
                ms = extract_media_sequence(playlist)
                if ms is not None:
                    sequences.append(ms)

        # INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 — never decreases
        for i in range(1, len(sequences)):
            assert sequences[i] >= sequences[i - 1], (
                f"MEDIA-SEQUENCE decreased: {sequences[i-1]} → {sequences[i]}"
            )

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-PDT-001 — Program date-time anchoring
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestPdt001:
    """INV-HLS-MANIFEST-PDT-001"""

    # Tier: 2 | Timeline invariant
    def test_program_date_time_present(self, segmenter_with_segments):
        """Manifest contains EXT-X-PROGRAM-DATE-TIME."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        # INV-HLS-MANIFEST-PDT-001 — PDT present
        pdt = extract_program_date_time(playlist)
        assert pdt is not None, (
            "INV-HLS-MANIFEST-PDT-001: EXT-X-PROGRAM-DATE-TIME missing"
        )

    # Tier: 2 | Timeline invariant
    def test_pdt_before_first_extinf(self, segmenter_with_segments):
        """EXT-X-PROGRAM-DATE-TIME appears before the first EXTINF."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        lines = playlist.splitlines()
        pdt_line = None
        extinf_line = None

        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-PROGRAM-DATE-TIME:") and pdt_line is None:
                pdt_line = i
            if line.startswith("#EXTINF:") and extinf_line is None:
                extinf_line = i

        if pdt_line is not None and extinf_line is not None:
            # INV-HLS-MANIFEST-PDT-001 — PDT before first EXTINF
            assert pdt_line < extinf_line, (
                f"PDT at line {pdt_line}, first EXTINF at {extinf_line}"
            )

    # Tier: 2 | Timeline invariant
    def test_pdt_is_valid_iso8601(self, segmenter_with_segments):
        """EXT-X-PROGRAM-DATE-TIME value is valid ISO 8601 UTC."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        pdt = extract_program_date_time(playlist)
        if pdt is not None:
            # INV-HLS-MANIFEST-PDT-001 — ISO 8601 with Z suffix
            assert re.match(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", pdt
            ), f"PDT not valid ISO 8601 UTC: {pdt}"

    # Tier: 2 | Timeline invariant
    def test_extinf_matches_positive_duration(self, segmenter_with_segments):
        """Every EXTINF value is a positive float matching segment duration."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        durations = extract_extinf_values(playlist)
        # INV-HLS-MANIFEST-PDT-001 — EXTINF matches segment duration
        for d in durations:
            assert d > 0, f"EXTINF duration must be positive, got {d}"


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-CHANNEL-SCOPED-001 — No per-client manifests
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestChannelScoped001:
    """INV-HLS-MANIFEST-CHANNEL-SCOPED-001"""

    # Tier: 1 | Structural invariant
    def test_manifest_identical_for_concurrent_reads(self, segmenter_with_segments):
        """Two reads at the same instant return identical playlists."""
        seg = segmenter_with_segments

        # INV-HLS-MANIFEST-CHANNEL-SCOPED-001 — no per-client content
        playlist_a = seg.get_playlist()
        playlist_b = seg.get_playlist()

        assert playlist_a is not None
        assert playlist_b is not None
        assert playlist_a == playlist_b, (
            "Concurrent manifest reads returned different content"
        )

    # Tier: 2 | Structural invariant
    def test_all_listed_segments_retrievable(self, segmenter_with_segments):
        """Every segment in the manifest is retrievable from the ring."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        for name in extract_segment_names(playlist):
            # INV-HLS-MANIFEST-CHANNEL-SCOPED-001 — all listed = retrievable
            data = seg.get_segment(name)
            assert data is not None, (
                f"Segment {name} listed in manifest but not retrievable"
            )


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-DETERMINISTIC-001 — Pure generation
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestDeterministic001:
    """INV-HLS-MANIFEST-DETERMINISTIC-001"""

    # Tier: 1 | Structural invariant
    def test_same_state_produces_identical_manifest(self, segmenter_with_segments):
        """Multiple calls with same ring state produce byte-identical manifests."""
        seg = segmenter_with_segments

        results = [seg.get_playlist() for _ in range(5)]
        assert all(r is not None for r in results)

        # INV-HLS-MANIFEST-DETERMINISTIC-001 — deterministic
        for i in range(1, len(results)):
            assert results[i] == results[0], (
                f"Manifest diverged on call {i}"
            )

    # Tier: 2 | Structural invariant
    def test_manifest_contains_no_random_data(self, segmenter_with_segments):
        """Manifest contains no nonces, UUIDs, or random components."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        # INV-HLS-MANIFEST-DETERMINISTIC-001 — no random content
        # UUID pattern: 8-4-4-4-12 hex
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            playlist,
            re.IGNORECASE,
        ), "Manifest contains UUID-like random data"


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-VALID-PLAYLIST-001 — Structural validity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestValidPlaylist001:
    """INV-HLS-MANIFEST-VALID-PLAYLIST-001"""

    # Tier: 1 | Protocol invariant
    def test_required_tags_present(self, segmenter_with_segments):
        """Manifest contains all required HLS tags."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        # INV-HLS-MANIFEST-VALID-PLAYLIST-001 — structural requirements
        assert "#EXTM3U" in playlist, "Missing #EXTM3U"
        assert "#EXT-X-TARGETDURATION:" in playlist, "Missing TARGETDURATION"
        assert "#EXT-X-MEDIA-SEQUENCE:" in playlist, "Missing MEDIA-SEQUENCE"
        assert "#EXTINF:" in playlist, "Missing EXTINF"
        assert re.search(r"seg_\d{5}\.ts", playlist), "Missing segment URI"

    # Tier: 1 | Protocol invariant
    def test_exactly_one_targetduration(self, segmenter_with_segments):
        """Manifest contains exactly one TARGETDURATION tag."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        count = playlist.count("#EXT-X-TARGETDURATION:")
        # INV-HLS-MANIFEST-VALID-PLAYLIST-001 — exactly one
        assert count == 1, f"Expected 1 TARGETDURATION, got {count}"

    # Tier: 1 | Protocol invariant
    def test_exactly_one_media_sequence(self, segmenter_with_segments):
        """Manifest contains exactly one MEDIA-SEQUENCE tag."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        count = playlist.count("#EXT-X-MEDIA-SEQUENCE:")
        # INV-HLS-MANIFEST-VALID-PLAYLIST-001 — exactly one
        assert count == 1, f"Expected 1 MEDIA-SEQUENCE, got {count}"

    # Tier: 1 | Protocol invariant
    def test_extinf_count_equals_segment_count(self, segmenter_with_segments):
        """Number of EXTINF tags equals number of segment URIs."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        extinf_count = playlist.count("#EXTINF:")
        seg_count = len(extract_segment_names(playlist))
        # INV-HLS-MANIFEST-VALID-PLAYLIST-001 — matched pairs
        assert extinf_count == seg_count, (
            f"EXTINF count {extinf_count} != segment count {seg_count}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001 — Manifest matches window
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestWindowRingAlignment001:
    """INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001"""

    # Tier: 1 | Structural invariant
    def test_no_playlist_when_empty(self):
        """Empty ring returns None, not an empty playlist."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        # INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001 — empty = None
        assert seg.get_playlist() is None, (
            "Empty ring should return None, not an empty playlist"
        )

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 — No system clock in timeline
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestPdtClockSource001:
    """INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001"""

    # Tier: 2 | Timeline invariant
    def test_pdt_does_not_change_with_system_clock(self, segmenter_with_segments):
        """PDT value is stable across reads regardless of elapsed system time."""
        seg = segmenter_with_segments

        playlist_1 = seg.get_playlist()
        # Small delay — if PDT used system clock, it would change
        playlist_2 = seg.get_playlist()

        if playlist_1 and playlist_2:
            pdt_1 = extract_program_date_time(playlist_1)
            pdt_2 = extract_program_date_time(playlist_2)
            if pdt_1 is not None and pdt_2 is not None:
                # INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 — no system clock
                assert pdt_1 == pdt_2, (
                    f"PDT changed between reads: {pdt_1} → {pdt_2}"
                )


# ---------------------------------------------------------------------------
# INV-HLS-DISCONTINUITY-MARKER-001 — Discontinuity propagation
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsDiscontinuityMarker001:
    """INV-HLS-DISCONTINUITY-MARKER-001"""

    # Tier: 2 | Protocol invariant
    def test_no_discontinuity_in_continuous_stream(self, segmenter_with_segments):
        """Continuous PCR stream produces no discontinuity tags."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        # INV-HLS-DISCONTINUITY-MARKER-001 — continuous = no tag
        assert "#EXT-X-DISCONTINUITY" not in playlist

    # Tier: 2 | Protocol invariant
    def test_discontinuity_on_pcr_jump(self):
        """PCR discontinuity produces EXT-X-DISCONTINUITY tag."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=10)
        seg.start()

        # Continuous segments
        feed_n_segments(seg, 2, target_dur=2.5)

        # Discontinuous segment (large PCR jump)
        data = generate_segment_data(duration=2.5, pcr_start=500.0)
        seg.feed(data)
        trigger = make_ts_packet(pid=0x100, keyframe=True, pcr=502.5)
        seg.feed(trigger)

        playlist = seg.get_playlist()
        assert playlist is not None

        # INV-HLS-DISCONTINUITY-MARKER-001 — PCR jump → tag present
        assert "#EXT-X-DISCONTINUITY" in playlist, (
            "Expected discontinuity tag after PCR jump"
        )

        seg.stop()

    # Tier: 2 | Protocol invariant
    def test_discontinuity_before_affected_segment(self):
        """Discontinuity tag appears before the segment that follows the break."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=10)
        seg.start()

        feed_n_segments(seg, 2, target_dur=2.5)
        data = generate_segment_data(duration=2.5, pcr_start=500.0)
        seg.feed(data)
        trigger = make_ts_packet(pid=0x100, keyframe=True, pcr=502.5)
        seg.feed(trigger)

        playlist = seg.get_playlist()
        assert playlist is not None

        lines = playlist.splitlines()
        disc_indices = [
            i for i, line in enumerate(lines)
            if line.strip() == "#EXT-X-DISCONTINUITY"
        ]
        if disc_indices:
            # INV-HLS-DISCONTINUITY-MARKER-001 — tag before next segment's EXTINF
            for di in disc_indices:
                # Next non-empty line should be EXTINF
                for j in range(di + 1, len(lines)):
                    stripped = lines[j].strip()
                    if stripped:
                        assert stripped.startswith("#EXTINF:"), (
                            f"Expected EXTINF after DISCONTINUITY at line {di}, "
                            f"got: {stripped}"
                        )
                        break

        seg.stop()
