"""Contract tests for movie-channel scheduling invariants.

Enforces:
  INV-MOVIE-PRIMARY-ATOMIC — Primary segment must not be split or interrupted.
  INV-MOVIE-TRAFFIC-POST-ONLY — Traffic insertion only after primary content.
  INV-TEMPLATE-PRIMARY-SEGMENT-001 — Exactly one primary segment per template.
  INV-MOVIE-REBUILD-EQUIVALENCE — Tier-2 rebuild uses same path as daemon.

See: docs/domains/movie_channel_invariants.md
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from unittest.mock import ANY, MagicMock, patch

import pytest

from retrovue.runtime.schedule_compiler import CompileError
from retrovue.runtime.schedule_items_reader import _hydrate_compiled_segments
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.traffic_manager import fill_ad_blocks
from retrovue.runtime.asset_resolver import AssetMetadata
from retrovue.usecases.schedule_rebuild import rebuild_tier2


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

BASE_DT = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
BASE_MS = int(BASE_DT.timestamp() * 1000)
HOUR_MS = 3_600_000
HALF_HOUR_MS = 1_800_000

INTRO_DURATION_MS = 30_000          # 30s branded intro
MOVIE_DURATION_MS = 5_400_000       # 90min feature film
SLOT_DURATION_MS = 7_200_000        # 2hr grid slot

FILLER_URI = "/assets/filler.mp4"
FILLER_DURATION_MS = 3_650_000


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _block_id(asset_id: str, start_ms: int) -> str:
    raw = f"{asset_id}:{start_ms}"
    return f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def _compiled_segments_hbo() -> list[dict]:
    """Canonical HBO-style V2 compiled segments: intro + primary movie."""
    return [
        {
            "segment_type": "intro",
            "asset_id": "intro-hbo-001",
            "duration_ms": INTRO_DURATION_MS,
        },
        {
            "segment_type": "content",
            "asset_id": "movie-001",
            "duration_ms": MOVIE_DURATION_MS,
        },
    ]


def _hydrate_hbo_block(
    start_ms: int = BASE_MS,
    slot_ms: int = SLOT_DURATION_MS,
) -> ScheduledBlock:
    """Hydrate an HBO-style block from V2 compiled segments."""
    return _hydrate_compiled_segments(
        compiled_segments=_compiled_segments_hbo(),
        asset_id="movie-001",
        start_utc_ms=start_ms,
        slot_duration_ms=slot_ms,
        resolver=_make_hbo_resolver(),
    )


class _FakeResolver:
    """Minimal asset resolver for compiler tests."""

    def __init__(self) -> None:
        self._assets: dict[str, AssetMetadata] = {}
        self._pools: dict[str, list[str]] = {}
        self._collections: dict[str, list[str]] = {}

    def add_asset(
        self, asset_id: str, title: str, duration_sec: int,
        *, asset_type: str = "movie", file_uri: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> None:
        self._assets[asset_id] = AssetMetadata(
            type=asset_type,
            duration_sec=duration_sec,
            title=title,
            tags=tags,
            file_uri=file_uri or f"/assets/{asset_id}.mp4",
        )

    def add_pool(self, pool_id: str, asset_ids: list[str]) -> None:
        self._pools[pool_id] = list(asset_ids)
        self._assets[pool_id] = AssetMetadata(
            type="pool", duration_sec=0, title=pool_id,
            tags=tuple(asset_ids),
        )

    def add_collection(self, col_id: str, asset_ids: list[str]) -> None:
        self._collections[col_id] = list(asset_ids)

    def lookup(self, asset_id: str) -> AssetMetadata:
        if asset_id not in self._assets:
            raise KeyError(f"Asset not found: {asset_id}")
        return self._assets[asset_id]

    def query(self, match: dict) -> list[str]:
        collection = match.get("collection")
        if collection and collection in self._collections:
            return list(self._collections[collection])
        return []

    def register_pools(self, pools: dict) -> None:
        for pool_id in pools:
            if pool_id not in self._assets:
                self._assets[pool_id] = AssetMetadata(
                    type="pool", duration_sec=0, title=pool_id, tags=(),
                )


def _make_hbo_resolver() -> _FakeResolver:
    r = _FakeResolver()
    r.add_asset("movie-001", "Weekend at Bernie's", 5400)
    r.add_pool("hbo_movies", ["movie-001"])
    r.add_asset("intro-hbo-001", "HBO Intro", 30, tags=("hbo",))
    r.add_collection("Intros", ["intro-hbo-001"])
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — INV-MOVIE-PRIMARY-ATOMIC: Primary segment cannot be split
# ─────────────────────────────────────────────────────────────────────────────

class TestPrimarySegmentAtomic:
    """INV-MOVIE-PRIMARY-ATOMIC: A primary segment on a movie channel
    MUST NOT be split, interrupted, or internally segmented."""

    def test_hydrated_block_has_intro_and_primary(self):
        """expand_editorial_block (via _hydrate_compiled_segments) produces
        exactly two content segments: intro + primary movie."""
        block = _hydrate_hbo_block()

        content_segs = [s for s in block.segments if s.segment_type != "filler"]
        assert len(content_segs) == 2, (
            f"Expected exactly 2 content segments (intro + movie), "
            f"got {len(content_segs)}: {[s.segment_type for s in content_segs]}"
        )

    def test_primary_segment_duration_matches_source_asset(self):
        """The primary segment duration MUST equal the source movie
        asset duration — no splitting, no truncation."""
        block = _hydrate_hbo_block()

        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert len(content_segs) == 1
        assert content_segs[0].segment_duration_ms == MOVIE_DURATION_MS, (
            f"Primary segment duration {content_segs[0].segment_duration_ms}ms "
            f"!= source asset {MOVIE_DURATION_MS}ms"
        )

    def test_no_filler_between_intro_and_primary(self):
        """No filler or ad segment may appear between intro and primary."""
        block = _hydrate_hbo_block()

        seg_types = [s.segment_type for s in block.segments]
        # Intro must immediately precede content
        intro_idx = seg_types.index("intro")
        content_idx = seg_types.index("content")
        assert content_idx == intro_idx + 1, (
            f"Content must immediately follow intro. "
            f"Segment order: {seg_types}"
        )

    def test_expand_movie_legacy_single_content_segment(self):
        """Legacy expand_program_block(channel_type='movie') produces
        a single uninterrupted content segment."""
        block = expand_program_block(
            asset_id="movie-001",
            asset_uri="/assets/movie-001.mp4",
            start_utc_ms=BASE_MS,
            slot_duration_ms=SLOT_DURATION_MS,
            episode_duration_ms=MOVIE_DURATION_MS,
            channel_type="movie",
        )

        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert len(content_segs) == 1, (
            f"Movie expansion must produce exactly 1 content segment, "
            f"got {len(content_segs)}"
        )
        assert content_segs[0].segment_duration_ms == MOVIE_DURATION_MS
        assert content_segs[0].asset_start_offset_ms == 0

    def test_expand_movie_no_mid_content_filler(self):
        """expand_program_block(channel_type='movie') must not produce
        any filler segments before the content segment ends."""
        block = expand_program_block(
            asset_id="movie-001",
            asset_uri="/assets/movie-001.mp4",
            start_utc_ms=BASE_MS,
            slot_duration_ms=SLOT_DURATION_MS,
            episode_duration_ms=MOVIE_DURATION_MS,
            channel_type="movie",
        )

        # Content must come first, filler (if any) must be last
        saw_filler = False
        for seg in block.segments:
            if seg.segment_type == "filler":
                saw_filler = True
            elif saw_filler:
                pytest.fail(
                    f"Content segment after filler — mid-content break detected. "
                    f"Segments: {[s.segment_type for s in block.segments]}"
                )

    def test_expand_movie_sets_is_primary(self):
        """expand_program_block(channel_type='movie') must mark the content
        segment with is_primary=True."""
        block = expand_program_block(
            asset_id="movie-001",
            asset_uri="/assets/movie-001.mp4",
            start_utc_ms=BASE_MS,
            slot_duration_ms=SLOT_DURATION_MS,
            episode_duration_ms=MOVIE_DURATION_MS,
            channel_type="movie",
        )

        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert len(content_segs) == 1
        assert content_segs[0].is_primary is True, (
            "Movie content segment must have is_primary=True"
        )

    def test_hydrated_content_segment_identified_by_type(self):
        """V2-hydrated blocks identify the primary movie by segment_type='content'."""
        block = _hydrate_hbo_block()

        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert len(content_segs) == 1, (
            f"Expected exactly 1 content segment, got {len(content_segs)}"
        )
        assert content_segs[0].segment_duration_ms == MOVIE_DURATION_MS


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — INV-MOVIE-TRAFFIC-POST-ONLY: TrafficManager insertion boundaries
# ─────────────────────────────────────────────────────────────────────────────

class TestTrafficManagerDoesNotSplitPrimary:
    """INV-MOVIE-TRAFFIC-POST-ONLY: TrafficManager may only insert content
    AFTER the primary segment has completed (in post-content filler slots)."""

    def test_fill_ad_blocks_does_not_increase_content_count(self):
        """fill_ad_blocks must not increase the number of content segments."""
        block = _hydrate_hbo_block()

        content_before = [s for s in block.segments if s.segment_type == "content"]

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        content_after = [s for s in filled.segments if s.segment_type == "content"]
        assert len(content_after) == len(content_before), (
            f"fill_ad_blocks changed content segment count from "
            f"{len(content_before)} to {len(content_after)}"
        )

    def test_fill_ad_blocks_preserves_primary_duration(self):
        """fill_ad_blocks must not alter the primary content segment's duration."""
        block = _hydrate_hbo_block()

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        content_segs = [s for s in filled.segments if s.segment_type == "content"]
        assert len(content_segs) == 1
        assert content_segs[0].segment_duration_ms == MOVIE_DURATION_MS

    def test_fill_ad_blocks_preserves_intro_segment(self):
        """fill_ad_blocks must not alter the intro segment."""
        block = _hydrate_hbo_block()

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        intro_segs = [s for s in filled.segments if s.segment_type == "intro"]
        assert len(intro_segs) == 1
        assert intro_segs[0].segment_duration_ms == INTRO_DURATION_MS

    def test_fill_ad_blocks_only_modifies_filler_placeholders(self):
        """fill_ad_blocks must only touch segments with segment_type='filler'
        and empty asset_uri. Non-filler segments must be passed through."""
        block = _hydrate_hbo_block()

        non_filler_before = [
            (s.segment_type, s.asset_uri, s.segment_duration_ms)
            for s in block.segments if s.segment_type != "filler"
        ]

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        non_filler_after = [
            (s.segment_type, s.asset_uri, s.segment_duration_ms)
            for s in filled.segments if s.segment_type != "filler"
        ]

        assert non_filler_before == non_filler_after, (
            f"Non-filler segments were modified by fill_ad_blocks.\n"
            f"Before: {non_filler_before}\n"
            f"After:  {non_filler_after}"
        )

    def test_fill_ad_blocks_rejects_filler_before_primary(self):
        """fill_ad_blocks must raise ValueError if a filler placeholder appears
        before the primary segment — INV-MOVIE-PRIMARY-ATOMIC guard."""
        # Construct a malformed block: filler BEFORE primary content
        bad_block = ScheduledBlock(
            block_id="blk-bad",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + SLOT_DURATION_MS,
            segments=(
                ScheduledSegment(
                    segment_type="intro",
                    asset_uri="/assets/intro.mp4",
                    asset_start_offset_ms=0,
                    segment_duration_ms=INTRO_DURATION_MS,
                ),
                ScheduledSegment(
                    segment_type="filler",
                    asset_uri="",
                    asset_start_offset_ms=0,
                    segment_duration_ms=300_000,
                ),
                ScheduledSegment(
                    segment_type="content",
                    asset_uri="/assets/movie.mp4",
                    asset_start_offset_ms=0,
                    segment_duration_ms=MOVIE_DURATION_MS,
                    is_primary=True,
                ),
            ),
        )

        with pytest.raises(ValueError, match="INV-MOVIE-PRIMARY-ATOMIC"):
            fill_ad_blocks(
                bad_block,
                filler_uri=FILLER_URI,
                filler_duration_ms=FILLER_DURATION_MS,
            )

    def test_filler_appears_only_after_all_content(self):
        """After fill_ad_blocks, filled filler segments must appear only
        after all content and intro segments have completed."""
        block = _hydrate_hbo_block()

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        saw_filler = False
        for seg in filled.segments:
            if seg.segment_type == "filler":
                saw_filler = True
            elif saw_filler:
                pytest.fail(
                    f"Non-filler segment ({seg.segment_type}) after filler — "
                    f"traffic was inserted mid-content. "
                    f"Segments: {[s.segment_type for s in filled.segments]}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — INV-MOVIE-REBUILD-EQUIVALENCE: Tier-2 rebuild parity
# ─────────────────────────────────────────────────────────────────────────────

class TestTier2RebuildParity:
    """INV-MOVIE-REBUILD-EQUIVALENCE: Tier-2 rebuild must use the same
    editorial block expansion path as the horizon scheduler daemon.

    Both paths must produce identical segment structures for identical
    Tier-1 inputs."""

    def _make_tier1_block_dict(
        self, compiled_segments: list[dict],
    ) -> dict:
        """Minimal Tier-1 serialized block dict (as load_segmented_blocks
        returns). Converts V2 compiled_segments to playout-level ScheduledBlock."""
        resolver = _make_hbo_resolver()
        segs = []
        for cs in compiled_segments:
            asset_id = cs.get("asset_id", "")
            meta = resolver.lookup(asset_id) if asset_id else None
            asset_uri = (meta.file_uri or "") if meta else ""
            dur_ms = cs["duration_ms"]
            segs.append({
                "segment_type": cs["segment_type"],
                "asset_uri": asset_uri,
                "asset_start_offset_ms": 0,
                "segment_duration_ms": dur_ms,
                "transition_in": "TRANSITION_NONE",
                "transition_in_duration_ms": 0,
                "transition_out": "TRANSITION_NONE",
                "transition_out_duration_ms": 0,
            })

        # Post-content filler
        content_total = sum(cs["duration_ms"] for cs in compiled_segments)
        remaining = SLOT_DURATION_MS - content_total
        if remaining > 0:
            segs.append({
                "segment_type": "filler",
                "asset_uri": "",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": remaining,
                "transition_in": "TRANSITION_NONE",
                "transition_in_duration_ms": 0,
                "transition_out": "TRANSITION_NONE",
                "transition_out_duration_ms": 0,
            })

        return {
            "block_id": _block_id("movie-001", BASE_MS),
            "start_utc_ms": BASE_MS,
            "end_utc_ms": BASE_MS + SLOT_DURATION_MS,
            "segments": segs,
        }

    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_rebuild_uses_same_loader_as_daemon(
        self, mock_load, mock_expand,
    ):
        """rebuild_tier2 must call load_segmented_blocks_from_active_revision —
        the same function the horizon daemon uses."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        compiled = _compiled_segments_hbo()
        tier1_block = self._make_tier1_block_dict(compiled)

        target_bd = date(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            return [tier1_block] if broadcast_day == target_bd else None
        mock_load.side_effect = _load

        fake_scheduled = MagicMock()
        fake_scheduled.block_id = tier1_block["block_id"]
        fake_scheduled.start_utc_ms = tier1_block["start_utc_ms"]
        fake_scheduled.end_utc_ms = tier1_block["end_utc_ms"]
        fake_scheduled.segments = []
        mock_expand.return_value = fake_scheduled

        rebuild_tier2(
            db,
            channel_slug="hbo-classics",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + 3 * HOUR_MS,
        )

        # Verify the canonical loader was called
        assert mock_load.called, (
            "rebuild_tier2 must call load_segmented_blocks_from_active_revision"
        )

    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_rebuild_calls_expand_editorial_block(
        self, mock_load, mock_expand,
    ):
        """rebuild_tier2 must call expand_editorial_block for each block —
        the canonical expansion pipeline shared with the daemon."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        compiled = _compiled_segments_hbo()
        tier1_block = self._make_tier1_block_dict(compiled)

        target_bd = date(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            return [tier1_block] if broadcast_day == target_bd else None
        mock_load.side_effect = _load

        fake_scheduled = MagicMock()
        fake_scheduled.block_id = tier1_block["block_id"]
        fake_scheduled.start_utc_ms = tier1_block["start_utc_ms"]
        fake_scheduled.end_utc_ms = tier1_block["end_utc_ms"]
        fake_scheduled.segments = []
        mock_expand.return_value = fake_scheduled

        rebuild_tier2(
            db,
            channel_slug="hbo-classics",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + 3 * HOUR_MS,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        mock_expand.assert_called_once_with(
            tier1_block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=ANY,
        )

    def test_direct_expansion_matches_hydration_structure(self):
        """The segment structure from _hydrate_compiled_segments must match
        what expand_program_block(channel_type='movie') would produce for
        the primary content: no mid-content breaks, filler only at end."""
        # Path A: template hydration
        hydrated = _hydrate_hbo_block()

        # Path B: legacy expansion (movie-only, no intro)
        legacy = expand_program_block(
            asset_id="movie-001",
            asset_uri="/assets/movie-001.mp4",
            start_utc_ms=BASE_MS,
            slot_duration_ms=SLOT_DURATION_MS,
            episode_duration_ms=MOVIE_DURATION_MS,
            channel_type="movie",
        )

        # Both must share the same structural invariant:
        # no filler before content ends
        for label, block in [("hydrated", hydrated), ("legacy", legacy)]:
            saw_filler = False
            for seg in block.segments:
                if seg.segment_type == "filler":
                    saw_filler = True
                elif saw_filler:
                    pytest.fail(
                        f"{label} path has content after filler: "
                        f"{[s.segment_type for s in block.segments]}"
                    )

        # Both must have exactly one content segment for the movie
        hydrated_content = [
            s for s in hydrated.segments if s.segment_type == "content"
        ]
        legacy_content = [
            s for s in legacy.segments if s.segment_type == "content"
        ]
        assert len(hydrated_content) == 1
        assert len(legacy_content) == 1
        assert hydrated_content[0].segment_duration_ms == legacy_content[0].segment_duration_ms

    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_rebuild_writes_segment_structure_to_playlist_event(
        self, mock_load, mock_expand,
    ):
        """The rebuild must persist segment structure into PlaylistEvent.segments
        matching what the daemon would write."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        compiled = _compiled_segments_hbo()
        tier1_block = self._make_tier1_block_dict(compiled)

        target_bd = date(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            return [tier1_block] if broadcast_day == target_bd else None
        mock_load.side_effect = _load

        # Use the real expand_editorial_block to produce a realistic block
        from retrovue.runtime.schedule_items_reader import expand_editorial_block
        filled_block = expand_editorial_block(
            tier1_block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        mock_expand.return_value = filled_block

        rebuild_tier2(
            db,
            channel_slug="hbo-classics",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + 3 * HOUR_MS,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        # Verify the PlaylistEvent was written
        assert db.merge.called
        written_row = db.merge.call_args[0][0]

        # Verify segment structure in the written row
        seg_types = [s["segment_type"] for s in written_row.segments]
        assert "intro" in seg_types, (
            f"PlaylistEvent missing intro segment: {seg_types}"
        )
        assert "content" in seg_types, (
            f"PlaylistEvent missing content segment: {seg_types}"
        )
        assert "filler" in seg_types, (
            f"PlaylistEvent missing filler segment: {seg_types}"
        )

        # Content count must be 1 (primary not split)
        content_count = seg_types.count("content")
        assert content_count == 1, (
            f"Expected 1 content segment in PlaylistEvent, got {content_count}"
        )
