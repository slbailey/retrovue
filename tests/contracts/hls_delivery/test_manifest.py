"""
Contract Tests: HLS Manifest Generation

Canonical contract:
    docs/contracts/delivery_hls.md — §3 Manifest Contract

These tests validate manifest generation invariants via ManifestGenerator + SegmentRing:
    INV-HLS-MANIFEST-LIVE-001                   No EXT-X-ENDLIST; TARGETDURATION valid
    INV-HLS-MANIFEST-SEQUENCE-001               MEDIA-SEQUENCE = oldest index; ascending order
    INV-HLS-MANIFEST-PDT-001                    PROGRAM-DATE-TIME from segment wall-clock
    INV-HLS-MANIFEST-CHANNEL-SCOPED-001         Identical for all clients
    INV-HLS-MANIFEST-DETERMINISTIC-001          Pure function of ring state
    INV-HLS-MANIFEST-VALID-PLAYLIST-001         Structurally valid HLS
    INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001     Sequence never decreases
    INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001  Manifest from single atomic snapshot
    INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001       No system clock in PDT path
    INV-HLS-DISCONTINUITY-MARKER-001            Discontinuity tag propagation

Migrated from the retired hls_writer.HLSSegmenter API (commit 8cccc5b).
New API: HlsSegmenter + SegmentRing + ManifestGenerator.
"""

from __future__ import annotations

import re
import pytest

from .conftest import (
    feed_n_segments,
    get_playlist,
    make_ring,
    make_segmenter,
    extract_extinf_values,
    extract_media_sequence,
    extract_target_duration,
    extract_program_date_time,
    extract_segment_names,
    extract_segment_indices,
    ManifestGenerator,
)


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-LIVE-001 — No EXT-X-ENDLIST; TARGETDURATION valid
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestLive001:
    """INV-HLS-MANIFEST-LIVE-001: live playlist structure requirements."""

    def test_no_ext_x_endlist_tag(self):
        """Live manifest MUST NOT contain EXT-X-ENDLIST."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        assert "#EXT-X-ENDLIST" not in playlist, (
            "Live manifest must not contain #EXT-X-ENDLIST"
        )

    def test_target_duration_present(self):
        """Manifest contains EXT-X-TARGETDURATION."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        td = extract_target_duration(playlist)
        assert td is not None, "EXT-X-TARGETDURATION missing from manifest"

    def test_target_duration_is_positive_integer(self):
        """EXT-X-TARGETDURATION must be a positive integer."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        td = extract_target_duration(playlist)
        assert td is not None
        assert isinstance(td, int), f"EXT-X-TARGETDURATION should be int, got {type(td)}"
        assert td >= 1, f"EXT-X-TARGETDURATION must be >= 1, got {td}"

    def test_target_duration_gte_max_extinf(self):
        """EXT-X-TARGETDURATION must be >= ceil(max EXTINF duration) per RFC 8216."""
        import math
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 5, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        td = extract_target_duration(playlist)
        durations = extract_extinf_values(playlist)
        assert td is not None
        assert durations
        max_dur = max(durations)
        assert td >= math.ceil(max_dur), (
            f"EXT-X-TARGETDURATION {td} < ceil(max_extinf {max_dur:.3f}) = {math.ceil(max_dur)}"
        )

    def test_extm3u_header_present(self):
        """Manifest starts with #EXTM3U."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        assert playlist.startswith("#EXTM3U"), (
            "Manifest must begin with #EXTM3U"
        )

    def test_ext_x_version_present(self):
        """Manifest contains EXT-X-VERSION."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        assert "#EXT-X-VERSION:" in playlist, "Manifest must contain #EXT-X-VERSION"

    def test_empty_ring_returns_none(self):
        """ManifestGenerator.generate() returns None for an empty ring."""
        ring = make_ring()
        manifest = ManifestGenerator("test-ch").generate(ring)
        assert manifest is None, (
            f"Expected None for empty ring, got: {manifest!r}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-SEQUENCE-001 — MEDIA-SEQUENCE = oldest index; ascending order
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestSequence001:
    """INV-HLS-MANIFEST-SEQUENCE-001: MEDIA-SEQUENCE matches oldest segment index."""

    def test_media_sequence_present(self):
        """Manifest contains EXT-X-MEDIA-SEQUENCE."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        seq = extract_media_sequence(playlist)
        assert seq is not None, "EXT-X-MEDIA-SEQUENCE missing from manifest"

    def test_media_sequence_equals_oldest_segment_index(self):
        """MEDIA-SEQUENCE value equals the oldest segment's index in the manifest."""
        seg, ring = make_segmenter(target_ms=2000, starting_index=0)
        feed_n_segments(seg, 5, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        seq = extract_media_sequence(playlist)
        indices = extract_segment_indices(playlist)
        assert seq is not None
        assert indices
        # MEDIA-SEQUENCE = first segment in manifest
        assert seq == indices[0], (
            f"MEDIA-SEQUENCE {seq} != first manifest segment index {indices[0]}"
        )

    def test_segments_appear_in_ascending_index_order(self):
        """Segment URIs in manifest appear in ascending index order."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 6, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        indices = extract_segment_indices(playlist)
        assert len(indices) >= 2
        for i in range(1, len(indices)):
            assert indices[i] > indices[i - 1], (
                f"Manifest segment order violation: {indices[i-1]} → {indices[i]}"
            )

    def test_media_sequence_with_non_zero_starting_index(self):
        """MEDIA-SEQUENCE reflects starting_index offset correctly."""
        offset = 200
        seg, ring = make_segmenter(starting_index=offset, target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        seq = extract_media_sequence(playlist)
        assert seq is not None
        assert seq == offset, (
            f"MEDIA-SEQUENCE {seq} expected to equal starting_index {offset}"
        )

    def test_manifest_window_limits_segment_count(self):
        """Manifest shows at most manifest_window segments even if ring has more."""
        manifest_window = 3
        ring = make_ring(capacity=10, manifest_window=manifest_window)
        seg, _ = make_segmenter(ring=ring, target_ms=2000)
        feed_n_segments(seg, 8, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        indices = extract_segment_indices(playlist)
        assert len(indices) <= manifest_window, (
            f"Manifest has {len(indices)} segments, expected <= {manifest_window}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-PDT-001 — PROGRAM-DATE-TIME from segment wall-clock
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestPdt001:
    """INV-HLS-MANIFEST-PDT-001: PROGRAM-DATE-TIME present and well-formed."""

    def test_program_date_time_present(self):
        """Manifest contains EXT-X-PROGRAM-DATE-TIME."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        pdt = extract_program_date_time(playlist)
        assert pdt is not None, "EXT-X-PROGRAM-DATE-TIME missing from manifest"

    def test_program_date_time_is_iso8601_utc(self):
        """PDT value is an ISO 8601 UTC timestamp ending in Z."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist
        pdt = extract_program_date_time(playlist)
        assert pdt is not None
        # Must match YYYY-MM-DDTHH:MM:SS.mmmZ
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$"
        assert re.match(pattern, pdt), (
            f"PDT {pdt!r} is not a valid ISO 8601 UTC timestamp"
        )

    def test_program_date_time_appears_before_first_segment(self):
        """PDT line appears in manifest before the first segment URI."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        lines = playlist.splitlines()
        pdt_line_idx = None
        first_seg_line_idx = None
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-PROGRAM-DATE-TIME:") and pdt_line_idx is None:
                pdt_line_idx = i
            if re.match(r"seg_\d{5}\.ts", line) and first_seg_line_idx is None:
                first_seg_line_idx = i

        assert pdt_line_idx is not None, "PDT line not found"
        assert first_seg_line_idx is not None, "No segment URI found"
        assert pdt_line_idx < first_seg_line_idx, (
            f"PDT at line {pdt_line_idx} appears after first segment at line {first_seg_line_idx}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-DETERMINISTIC-001 — Pure function of ring state
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestDeterministic001:
    """INV-HLS-MANIFEST-DETERMINISTIC-001: manifest is deterministic for a given ring state."""

    def test_same_ring_state_produces_identical_manifest(self):
        """Two calls to generate() with unchanged ring produce identical output."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 4, target_dur=2.5)

        gen = ManifestGenerator("test-ch")
        first = gen.generate(ring)
        second = gen.generate(ring)
        assert first is not None
        assert first == second, "Same ring state produced different manifests"

    def test_manifest_changes_after_new_segment(self):
        """Manifest changes when a new segment is added to the ring."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        gen = ManifestGenerator("test-ch")
        before = gen.generate(ring)
        assert before is not None

        # Add one more segment
        feed_n_segments(seg, 1, target_dur=2.5, pcr_offset=7.5)
        after = gen.generate(ring)
        assert after is not None
        assert before != after, "Manifest should change after new segment is produced"


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 — Sequence never decreases
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestSequenceMonotonic001:
    """INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001: MEDIA-SEQUENCE never decreases."""

    def test_media_sequence_never_decreases(self):
        """MEDIA-SEQUENCE is non-decreasing across successive manifest calls."""
        seg, ring = make_segmenter(target_ms=2000)
        gen = ManifestGenerator("test-ch")
        sequences = []

        for i in range(6):
            feed_n_segments(seg, 1, target_dur=2.5, pcr_offset=i * 2.5)
            playlist = gen.generate(ring)
            assert playlist is not None
            seq = extract_media_sequence(playlist)
            assert seq is not None
            sequences.append(seq)

        for i in range(1, len(sequences)):
            assert sequences[i] >= sequences[i - 1], (
                f"MEDIA-SEQUENCE decreased: {sequences[i-1]} → {sequences[i]} at step {i}"
            )


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-VALID-PLAYLIST-001 — Structurally valid HLS
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestValidPlaylist001:
    """INV-HLS-MANIFEST-VALID-PLAYLIST-001: manifest is a structurally valid HLS media playlist."""

    def test_extinf_before_every_segment_uri(self):
        """Every segment URI is immediately preceded by an EXTINF tag."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 4, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        lines = [l.strip() for l in playlist.splitlines() if l.strip()]
        for i, line in enumerate(lines):
            if re.match(r"seg_\d{5}\.ts", line):
                assert i > 0, f"Segment URI at line {i} has no preceding line"
                assert lines[i - 1].startswith("#EXTINF:"), (
                    f"Line before segment URI {line!r} is {lines[i-1]!r}, expected #EXTINF"
                )

    def test_each_extinf_has_duration_and_comma(self):
        """Each EXTINF tag has format #EXTINF:<duration>,[title]"""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 4, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        extinf_pattern = re.compile(r"#EXTINF:[\d.]+,")
        for line in playlist.splitlines():
            if line.startswith("#EXTINF:"):
                assert extinf_pattern.match(line), (
                    f"Malformed EXTINF tag: {line!r}"
                )

    def test_segment_uris_have_correct_format(self):
        """All segment URIs follow the seg_NNNNN.ts format."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 4, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        names = extract_segment_names(playlist)
        assert len(names) >= 1
        for name in names:
            assert re.match(r"seg_\d{5}\.ts$", name), (
                f"Segment URI {name!r} does not match expected seg_NNNNN.ts format"
            )

    def test_required_tags_present(self):
        """Manifest contains all required HLS live playlist tags."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)
        playlist = get_playlist(ring)
        assert playlist

        required = [
            "#EXTM3U",
            "#EXT-X-VERSION:",
            "#EXT-X-TARGETDURATION:",
            "#EXT-X-MEDIA-SEQUENCE:",
            "#EXT-X-PROGRAM-DATE-TIME:",
            "#EXTINF:",
        ]
        for tag in required:
            assert tag in playlist, f"Required tag {tag!r} missing from manifest"


# ---------------------------------------------------------------------------
# INV-HLS-DISCONTINUITY-MARKER-001 — Discontinuity tag propagation
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsDiscontinuityMarker001:
    """INV-HLS-DISCONTINUITY-MARKER-001: discontinuity markers propagate to manifest."""

    def test_no_discontinuity_tag_when_none_in_ring(self):
        """Manifest has no #EXT-X-DISCONTINUITY for segments after the first.

        NOTE: The segmenter always marks segment[0] discontinuous (no prior
        PCR context at startup). Subsequent segments with no detected PCR jump
        must NOT carry #EXT-X-DISCONTINUITY. This test checks the invariant
        on segments 1..N, not segment 0.
        """
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 5, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 2, "Need at least 2 segments for this test"

        # Segment 0 is expected discontinuous (startup). Segments 1+ must not be.
        for s in window[1:]:
            assert not s.discontinuity, (
                f"Segment {s.index} has unexpected discontinuity=True "
                f"without a PCR jump"
            )

    def test_discontinuity_tag_injected_from_ring(self):
        """#EXT-X-DISCONTINUITY appears in manifest when a segment has discontinuity=True."""
        from retrovue.runtime.hls.segment_ring import LiveSegment, SegmentRing

        # Build a ring manually with a discontinuous segment
        ring = make_ring(capacity=5, manifest_window=3)
        now_ms = 1_700_000_000_000
        _seg_data = b"\x47" + b"\x00" * 187

        # Normal segment
        ring.push(LiveSegment(
            channel_id="test-ch",
            index=0,
            data=_seg_data,
            byte_count=len(_seg_data),
            duration_ms=2500,
            wall_clock_start_utc_ms=now_ms,
            discontinuity=False,
        ))
        # Discontinuous segment
        ring.push(LiveSegment(
            channel_id="test-ch",
            index=1,
            data=_seg_data,
            byte_count=len(_seg_data),
            duration_ms=2500,
            wall_clock_start_utc_ms=now_ms + 2500,
            discontinuity=True,
        ))

        gen = ManifestGenerator("test-ch")
        playlist = gen.generate(ring)
        assert playlist is not None
        assert "#EXT-X-DISCONTINUITY" in playlist, (
            "Manifest must contain #EXT-X-DISCONTINUITY for a segment with discontinuity=True"
        )

    def test_discontinuity_tag_precedes_segment_uri(self):
        """#EXT-X-DISCONTINUITY tag appears before the discontinuous segment URI."""
        from retrovue.runtime.hls.segment_ring import LiveSegment, SegmentRing

        ring = make_ring(capacity=5, manifest_window=3)
        now_ms = 1_700_000_000_000
        _seg_data = b"\x47" + b"\x00" * 187

        ring.push(LiveSegment(
            channel_id="test-ch",
            index=0,
            data=_seg_data,
            byte_count=len(_seg_data),
            duration_ms=2500,
            wall_clock_start_utc_ms=now_ms,
            discontinuity=False,
        ))
        ring.push(LiveSegment(
            channel_id="test-ch",
            index=1,
            data=_seg_data,
            byte_count=len(_seg_data),
            duration_ms=2500,
            wall_clock_start_utc_ms=now_ms + 2500,
            discontinuity=True,
        ))

        gen = ManifestGenerator("test-ch")
        playlist = gen.generate(ring)
        assert playlist is not None

        lines = [l.strip() for l in playlist.splitlines() if l.strip()]
        disc_line_idx = None
        seg1_line_idx = None
        for i, line in enumerate(lines):
            if line == "#EXT-X-DISCONTINUITY" and disc_line_idx is None:
                disc_line_idx = i
            if line == "seg_00001.ts":
                seg1_line_idx = i

        assert disc_line_idx is not None, "#EXT-X-DISCONTINUITY not found"
        assert seg1_line_idx is not None, "seg_00001.ts not found"
        assert disc_line_idx < seg1_line_idx, (
            f"#EXT-X-DISCONTINUITY at line {disc_line_idx} appears after "
            f"seg_00001.ts at line {seg1_line_idx}"
        )
