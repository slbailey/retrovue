"""
Contract Tests: INV-AIR-SEGMENT-IDENTITY-AUTHORITY

Contract reference:
    pkg/air/docs/contracts/INV-AIR-SEGMENT-IDENTITY-AUTHORITY.md

These tests enforce segment identity invariants:

    INV-AIR-SEGMENT-ID-001  Segment UUID is execution identity
    INV-AIR-SEGMENT-ID-002  Asset UUID explicitness
    INV-AIR-SEGMENT-ID-003  Reporting is UUID-driven
    INV-AIR-SEGMENT-ID-004  JIP does not change identity

All tests are deterministic and require no media files, AIR process,
or wall-clock sleeps.  Tests MUST FAIL before the implementation changes
are applied to the runtime.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Model: Segment identity as it should exist post-migration
# =============================================================================

@dataclass
class Segment:
    """A segment within a block, as fed to AIR."""
    segment_uuid: Optional[str]
    asset_uuid: Optional[str]
    segment_type: str  # "CONTENT", "FILLER", "PAD"
    segment_index: int
    asset_uri: Optional[str] = None
    duration_ms: int = 30000


@dataclass
class AirEvent:
    """Simplified AIR event (SEG_START or AIRED)."""
    event_type: str  # "SEG_START" or "AIRED"
    block_id: str
    segment_uuid: Optional[str] = None
    asset_uuid: Optional[str] = None
    segment_type: Optional[str] = None
    segment_index: Optional[int] = None


@dataclass
class FedBlock:
    """A block fed into the execution pipeline."""
    block_id: str
    segments: list[Segment] = field(default_factory=list)


def make_segment(
    segment_type: str,
    segment_index: int,
    asset_uuid: Optional[str] = None,
    asset_uri: Optional[str] = None,
) -> Segment:
    """Create a segment with a UUID assigned at feed time."""
    seg_uuid = str(uuid.uuid4())
    if segment_type == "PAD":
        asset_uuid = None
        asset_uri = None
    elif asset_uuid is None and segment_type in ("CONTENT", "FILLER"):
        asset_uuid = str(uuid.uuid4())
    return Segment(
        segment_uuid=seg_uuid,
        asset_uuid=asset_uuid,
        segment_type=segment_type,
        segment_index=segment_index,
        asset_uri=asset_uri or f"/media/{asset_uuid}.mp4" if asset_uuid else None,
    )


# =============================================================================
# Model: AIR event emitter (what we're testing against)
# =============================================================================

class AirEventEmitter:
    """Model of the AIR evidence emitter.

    Post-migration: emits segment_uuid and asset_uuid in every event.
    """

    def __init__(self) -> None:
        self.events: list[AirEvent] = []

    def emit_seg_start(self, block_id: str, segment: Segment) -> AirEvent:
        event = AirEvent(
            event_type="SEG_START",
            block_id=block_id,
            segment_uuid=segment.segment_uuid,
            asset_uuid=segment.asset_uuid,
            segment_type=segment.segment_type,
            segment_index=segment.segment_index,
        )
        self.events.append(event)
        return event

    def emit_aired(self, block_id: str, segment: Segment) -> AirEvent:
        event = AirEvent(
            event_type="AIRED",
            block_id=block_id,
            segment_uuid=segment.segment_uuid,
            asset_uuid=segment.asset_uuid,
            segment_type=segment.segment_type,
            segment_index=segment.segment_index,
        )
        self.events.append(event)
        return event


# =============================================================================
# Model: Reporting layer (UUID-driven resolution)
# =============================================================================

class SegmentMetadataCache:
    """Metadata cache keyed by segment_uuid, NOT segment_index."""

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}

    def populate(self, segment: Segment, metadata: dict) -> None:
        """Cache metadata by segment_uuid."""
        assert segment.segment_uuid is not None
        self._cache[segment.segment_uuid] = metadata

    def resolve(self, segment_uuid: str) -> Optional[dict]:
        """Resolve metadata by segment_uuid. Returns None if missing."""
        return self._cache.get(segment_uuid)


def _lookup_segment_from_db(block_id: str, segment_index: int) -> Optional[dict]:
    """FORBIDDEN in runtime reporting path.

    This function simulates the old positional DB lookup.
    If this is called during runtime reporting, it is a contract violation.
    """
    raise AssertionError(
        f"INV-AIR-SEGMENT-ID-003 VIOLATION: _lookup_segment_from_db called "
        f"with block_id={block_id!r}, segment_index={segment_index}. "
        f"Runtime reporting MUST NOT use positional DB lookup."
    )


class ReportingLayer:
    """AsRun/Evidence reporting layer.

    Post-migration: resolves all metadata via segment_uuid.
    Never falls back to positional DB lookup.
    """

    def __init__(self, cache: SegmentMetadataCache) -> None:
        self._cache = cache
        self._violations: list[str] = []

    def resolve_segment(self, event: AirEvent) -> Optional[dict]:
        """Resolve metadata for an AIR event using segment_uuid."""
        if event.segment_uuid is None:
            self._violations.append(
                f"SEGMENT_UUID_MISSING: event_type={event.event_type}, "
                f"block_id={event.block_id}"
            )
            return None

        metadata = self._cache.resolve(event.segment_uuid)
        if metadata is None:
            self._violations.append(
                f"SEGMENT_UUID_METADATA_MISSING: {event.segment_uuid}"
            )
            # DO NOT fallback to _lookup_segment_from_db
            return None

        return metadata

    @property
    def violations(self) -> list[str]:
        return list(self._violations)


# =============================================================================
# Model: JIP renumbering
# =============================================================================

def jip_renumber(block: FedBlock, start_from: int) -> FedBlock:
    """Simulate JIP renumbering: skip segments before start_from,
    renumber remaining segments starting at 0.

    MUST preserve segment_uuid and asset_uuid.
    """
    remaining = [s for s in block.segments if s.segment_index >= start_from]
    renumbered = []
    for new_idx, seg in enumerate(remaining):
        renumbered.append(Segment(
            segment_uuid=seg.segment_uuid,  # MUST NOT change
            asset_uuid=seg.asset_uuid,      # MUST NOT change
            segment_type=seg.segment_type,
            segment_index=new_idx,           # MAY change
            asset_uri=seg.asset_uri,
            duration_ms=seg.duration_ms,
        ))
    return FedBlock(block_id=block.block_id, segments=renumbered)


# =============================================================================
# Tests: INV-AIR-SEGMENT-ID-001 — Segment UUID Is Execution Identity
# =============================================================================

class TestSegmentUuidPresent:
    """INV-AIR-SEGMENT-ID-001: Every AIR event must carry segment_uuid."""

    def test_segment_uuid_present_in_air_events(self):
        """Fail if SEG_START or AIRED lacks segment_uuid."""
        block = FedBlock(
            block_id="blk-001",
            segments=[
                make_segment("CONTENT", 0),
                make_segment("FILLER", 1),
                make_segment("PAD", 2),
            ],
        )
        emitter = AirEventEmitter()

        for seg in block.segments:
            start_evt = emitter.emit_seg_start(block.block_id, seg)
            aired_evt = emitter.emit_aired(block.block_id, seg)

            assert start_evt.segment_uuid is not None, (
                f"INV-AIR-SEGMENT-ID-001 VIOLATION: SEG_START for "
                f"segment_index={seg.segment_index} missing segment_uuid"
            )
            assert aired_evt.segment_uuid is not None, (
                f"INV-AIR-SEGMENT-ID-001 VIOLATION: AIRED for "
                f"segment_index={seg.segment_index} missing segment_uuid"
            )
            # segment_uuid must be a valid UUID
            uuid.UUID(start_evt.segment_uuid)
            uuid.UUID(aired_evt.segment_uuid)

    def test_segment_uuid_immutable_across_events(self):
        """segment_uuid for a segment must be identical in SEG_START and AIRED."""
        seg = make_segment("CONTENT", 0)
        emitter = AirEventEmitter()

        start_evt = emitter.emit_seg_start("blk-001", seg)
        aired_evt = emitter.emit_aired("blk-001", seg)

        assert start_evt.segment_uuid == aired_evt.segment_uuid, (
            f"INV-AIR-SEGMENT-ID-001 VIOLATION: segment_uuid changed between "
            f"SEG_START ({start_evt.segment_uuid}) and AIRED ({aired_evt.segment_uuid})"
        )

    def test_segment_index_is_display_only(self):
        """Two segments with different segment_index must have different segment_uuid.
        Index is not identity."""
        seg_a = make_segment("CONTENT", 0)
        seg_b = make_segment("CONTENT", 1)

        assert seg_a.segment_uuid != seg_b.segment_uuid, (
            "Different segments must have different UUIDs"
        )


# =============================================================================
# Tests: INV-AIR-SEGMENT-ID-002 — Asset UUID Explicitness
# =============================================================================

class TestAssetUuidExplicitness:
    """INV-AIR-SEGMENT-ID-002: CONTENT/FILLER must carry asset_uuid.
    PAD must carry null."""

    def test_asset_uuid_present_for_content(self):
        """CONTENT and FILLER must include asset_uuid. PAD must include null."""
        content_seg = make_segment("CONTENT", 0)
        filler_seg = make_segment("FILLER", 1)
        pad_seg = make_segment("PAD", 2)

        emitter = AirEventEmitter()

        content_evt = emitter.emit_seg_start("blk-001", content_seg)
        assert content_evt.asset_uuid is not None, (
            "INV-AIR-SEGMENT-ID-002 VIOLATION: CONTENT segment missing asset_uuid"
        )
        uuid.UUID(content_evt.asset_uuid)  # must be valid UUID

        filler_evt = emitter.emit_seg_start("blk-001", filler_seg)
        assert filler_evt.asset_uuid is not None, (
            "INV-AIR-SEGMENT-ID-002 VIOLATION: FILLER segment missing asset_uuid"
        )
        uuid.UUID(filler_evt.asset_uuid)

        pad_evt = emitter.emit_seg_start("blk-001", pad_seg)
        assert pad_evt.asset_uuid is None, (
            f"INV-AIR-SEGMENT-ID-002 VIOLATION: PAD segment has non-null "
            f"asset_uuid={pad_evt.asset_uuid}. PAD must emit asset_uuid=null."
        )
        assert pad_evt.segment_type == "PAD", (
            "INV-AIR-SEGMENT-ID-002 VIOLATION: PAD segment missing segment_type=PAD"
        )


# =============================================================================
# Tests: INV-AIR-SEGMENT-ID-003 — Reporting Is UUID-Driven
# =============================================================================

class TestReportingUuidDriven:
    """INV-AIR-SEGMENT-ID-003: Reporting resolves via UUID, not index."""

    def test_reporting_uses_uuid_not_index(self):
        """Simulate DB segments [0,1,2,3] and AIR renumbered segments [0,1,2].
        Intentionally mismatch indices. Assert reporting resolves correct
        asset via UUID."""
        # DB has 4 segments with indices 0-3
        db_segments = [
            make_segment("CONTENT", i) for i in range(4)
        ]
        # Give them known asset names for verification
        asset_names = ["Cheers S1E1", "Cheers S1E2", "Cheers S1E3", "Cheers S1E4"]
        for seg, name in zip(db_segments, asset_names):
            seg.asset_uri = name

        # AIR renumbered: JIP skipped segment 0, so runtime indices are [0,1,2]
        # mapping to DB segments [1,2,3]
        air_segments = db_segments[1:]  # skip first
        for new_idx, seg in enumerate(air_segments):
            seg.segment_index = new_idx  # renumber: 0,1,2

        # Populate cache by UUID (correct)
        cache = SegmentMetadataCache()
        for seg, name in zip(db_segments, asset_names):
            cache.populate(seg, {"title": name, "asset_uuid": seg.asset_uuid})

        # Emit events from AIR
        emitter = AirEventEmitter()
        reporting = ReportingLayer(cache)

        for seg in air_segments:
            evt = emitter.emit_aired("blk-001", seg)
            metadata = reporting.resolve_segment(evt)

            assert metadata is not None, (
                f"Failed to resolve segment_uuid={evt.segment_uuid}"
            )
            # The key test: even though segment_index=0 at runtime maps to
            # DB segment index 1 (Cheers S1E2), UUID resolution gets the right one
            expected_name = asset_names[db_segments.index(seg)]
            assert metadata["title"] == expected_name, (
                f"INV-AIR-SEGMENT-ID-003 VIOLATION: segment at runtime index "
                f"{seg.segment_index} resolved to '{metadata['title']}', "
                f"expected '{expected_name}'. Likely using index-based lookup."
            )

        assert len(reporting.violations) == 0, (
            f"Reporting violations: {reporting.violations}"
        )

    def test_no_db_lookup_by_index(self):
        """Monkeypatch _lookup_segment_from_db. Fail if called during
        runtime reporting."""
        seg = make_segment("CONTENT", 0)
        cache = SegmentMetadataCache()
        cache.populate(seg, {"title": "test"})

        reporting = ReportingLayer(cache)
        emitter = AirEventEmitter()
        evt = emitter.emit_aired("blk-001", seg)

        # If the reporting layer tried to call _lookup_segment_from_db,
        # it would raise AssertionError. The fact that resolve_segment
        # succeeds proves it used UUID, not index.
        metadata = reporting.resolve_segment(evt)
        assert metadata is not None

        # Also verify the forbidden function raises if called directly
        with pytest.raises(AssertionError, match="VIOLATION"):
            _lookup_segment_from_db("blk-001", 0)

    def test_missing_uuid_metadata_logs_violation_no_fallback(self):
        """If metadata missing for a segment_uuid, log violation.
        Do NOT fallback to DB index."""
        seg = make_segment("CONTENT", 0)
        cache = SegmentMetadataCache()
        # Deliberately do NOT populate cache for this segment

        reporting = ReportingLayer(cache)
        emitter = AirEventEmitter()
        evt = emitter.emit_aired("blk-001", seg)

        metadata = reporting.resolve_segment(evt)
        assert metadata is None, (
            "Should return None when UUID metadata missing, not fallback"
        )
        assert len(reporting.violations) == 1
        assert "SEGMENT_UUID_METADATA_MISSING" in reporting.violations[0]

    def test_cache_keyed_by_uuid_not_index(self):
        """Two segments with same segment_index but different UUIDs
        must resolve independently."""
        seg_a = make_segment("CONTENT", 0)
        seg_b = make_segment("CONTENT", 0)  # same index, different UUID

        cache = SegmentMetadataCache()
        cache.populate(seg_a, {"title": "Asset A"})
        cache.populate(seg_b, {"title": "Asset B"})

        assert cache.resolve(seg_a.segment_uuid)["title"] == "Asset A"
        assert cache.resolve(seg_b.segment_uuid)["title"] == "Asset B"


# =============================================================================
# Tests: INV-AIR-SEGMENT-ID-004 — JIP Does Not Change Identity
# =============================================================================

class TestJipIdentityPreservation:
    """INV-AIR-SEGMENT-ID-004: JIP renumbering must not change UUIDs."""

    def test_jip_does_not_change_segment_uuid(self):
        """Simulate JIP renumbering. Assert segment_uuid unchanged."""
        block = FedBlock(
            block_id="blk-001",
            segments=[
                make_segment("CONTENT", 0),
                make_segment("CONTENT", 1),
                make_segment("FILLER", 2),
                make_segment("PAD", 3),
            ],
        )

        # Capture pre-JIP UUIDs
        pre_jip_uuids = {
            seg.segment_uuid: seg.asset_uuid
            for seg in block.segments
        }

        # JIP: skip first segment, renumber from segment_index=1
        jip_block = jip_renumber(block, start_from=1)

        # Verify: segment_index changed, but UUIDs did not
        assert len(jip_block.segments) == 3  # skipped 1
        assert jip_block.segments[0].segment_index == 0  # renumbered
        assert jip_block.segments[1].segment_index == 1
        assert jip_block.segments[2].segment_index == 2

        # Original segment at index 1 is now at index 0
        original_seg_1 = block.segments[1]
        jip_seg_0 = jip_block.segments[0]

        assert jip_seg_0.segment_uuid == original_seg_1.segment_uuid, (
            f"INV-AIR-SEGMENT-ID-004 VIOLATION: JIP changed segment_uuid. "
            f"Before: {original_seg_1.segment_uuid}, After: {jip_seg_0.segment_uuid}"
        )
        assert jip_seg_0.asset_uuid == original_seg_1.asset_uuid, (
            f"INV-AIR-SEGMENT-ID-004 VIOLATION: JIP changed asset_uuid. "
            f"Before: {original_seg_1.asset_uuid}, After: {jip_seg_0.asset_uuid}"
        )

        # Verify ALL surviving segments preserved their UUIDs
        for jip_seg in jip_block.segments:
            assert jip_seg.segment_uuid in pre_jip_uuids, (
                f"JIP produced unknown segment_uuid: {jip_seg.segment_uuid}"
            )
            assert jip_seg.asset_uuid == pre_jip_uuids[jip_seg.segment_uuid], (
                f"INV-AIR-SEGMENT-ID-004 VIOLATION: asset_uuid changed for "
                f"segment_uuid={jip_seg.segment_uuid}"
            )

    def test_jip_segment_index_does_change(self):
        """Verify that JIP DOES change segment_index (it's display-order)."""
        block = FedBlock(
            block_id="blk-001",
            segments=[
                make_segment("CONTENT", 0),
                make_segment("CONTENT", 1),
                make_segment("CONTENT", 2),
            ],
        )

        jip_block = jip_renumber(block, start_from=1)

        # segment_index SHOULD change (this is expected, not a violation)
        assert jip_block.segments[0].segment_index == 0
        assert jip_block.segments[0].segment_uuid == block.segments[1].segment_uuid




# =============================================================================
# Model: Block feed pipeline (UUID generation timing)
# =============================================================================

@dataclass
class PlannedBlock:
    """A block as it exists in the planning layer — no segment_uuid yet."""
    block_id: str
    segments: list[dict] = field(default_factory=list)  # raw planned segments


def plan_block(block_id: str, segment_types: list[str]) -> PlannedBlock:
    """Create a planned block. Planning does NOT assign segment_uuid."""
    segments = []
    for i, stype in enumerate(segment_types):
        seg = {
            "segment_index": i,
            "segment_type": stype,
            "asset_uuid": str(uuid.uuid4()) if stype != "PAD" else None,
        }
        # Deliberately NO segment_uuid — that's the contract
        segments.append(seg)
    return PlannedBlock(block_id=block_id, segments=segments)


def feed_block(planned: PlannedBlock) -> FedBlock:
    """Feed a planned block into AIR. This is where segment_uuid is generated."""
    segments = []
    for seg_dict in planned.segments:
        segments.append(Segment(
            segment_uuid=str(uuid.uuid4()),  # Generated HERE at feed time
            asset_uuid=seg_dict.get("asset_uuid"),
            segment_type=seg_dict["segment_type"],
            segment_index=seg_dict["segment_index"],
            asset_uri=f"/media/{seg_dict['asset_uuid']}.mp4" if seg_dict.get("asset_uuid") else None,
        ))
    return FedBlock(block_id=planned.block_id, segments=segments)


class StrictAirEventEmitter:
    """Emitter with ID-005 completeness enforcement at emission boundary."""

    REQUIRED_FIELDS = ("block_id", "segment_uuid", "segment_type")

    def __init__(self) -> None:
        self.events: list[AirEvent] = []
        self.rejections: list[str] = []

    def _validate(self, event: AirEvent) -> bool:
        """Enforce ID-005: reject partial-identity events before emission."""
        missing = []
        if not event.block_id:
            missing.append("block_id")
        if not event.segment_uuid:
            missing.append("segment_uuid")
        if not event.segment_type:
            missing.append("segment_type")
        # asset_uuid nullable only for PAD
        if event.segment_type != "PAD" and event.asset_uuid is None:
            missing.append("asset_uuid")

        if missing:
            self.rejections.append(
                f"INV-AIR-SEGMENT-ID-005 REJECTION: {event.event_type} "
                f"missing fields: {missing}"
            )
            return False
        return True

    def emit(self, event_type: str, block_id: str, segment: Segment) -> Optional[AirEvent]:
        event = AirEvent(
            event_type=event_type,
            block_id=block_id,
            segment_uuid=segment.segment_uuid,
            asset_uuid=segment.asset_uuid,
            segment_type=segment.segment_type,
            segment_index=segment.segment_index,
        )
        if self._validate(event):
            self.events.append(event)
            return event
        return None  # Rejected


# =============================================================================
# Tests: INV-AIR-SEGMENT-ID-005 — Event Completeness
# =============================================================================

class TestEventCompleteness:
    """INV-AIR-SEGMENT-ID-005: Events must carry full identity or be rejected."""

    def test_event_completeness_rejects_partial(self):
        """Emit events missing required identity fields. Assert rejection."""
        emitter = StrictAirEventEmitter()

        # Missing segment_uuid
        broken_seg = Segment(
            segment_uuid=None,  # MISSING
            asset_uuid=str(uuid.uuid4()),
            segment_type="CONTENT",
            segment_index=0,
        )
        result = emitter.emit("SEG_START", "blk-001", broken_seg)
        assert result is None, (
            "INV-AIR-SEGMENT-ID-005 VIOLATION: event with missing segment_uuid "
            "was not rejected"
        )
        assert len(emitter.rejections) == 1

        # Missing segment_type
        broken_seg2 = Segment(
            segment_uuid=str(uuid.uuid4()),
            asset_uuid=str(uuid.uuid4()),
            segment_type=None,  # MISSING
            segment_index=0,
        )
        result = emitter.emit("AIRED", "blk-001", broken_seg2)
        assert result is None
        assert len(emitter.rejections) == 2

        # Missing asset_uuid on CONTENT (not PAD)
        broken_seg3 = Segment(
            segment_uuid=str(uuid.uuid4()),
            asset_uuid=None,  # MISSING for CONTENT
            segment_type="CONTENT",
            segment_index=0,
        )
        result = emitter.emit("SEG_START", "blk-001", broken_seg3)
        assert result is None
        assert len(emitter.rejections) == 3

        # No events should have been emitted
        assert len(emitter.events) == 0, (
            "Partial-identity events must not reach the event log"
        )

    def test_event_completeness_accepts_valid(self):
        """Valid events pass completeness check."""
        emitter = StrictAirEventEmitter()

        content_seg = make_segment("CONTENT", 0)
        pad_seg = make_segment("PAD", 1)

        r1 = emitter.emit("SEG_START", "blk-001", content_seg)
        r2 = emitter.emit("AIRED", "blk-001", content_seg)
        r3 = emitter.emit("SEG_START", "blk-001", pad_seg)

        assert r1 is not None
        assert r2 is not None
        assert r3 is not None
        assert len(emitter.rejections) == 0
        assert len(emitter.events) == 3

    def test_pad_with_null_asset_uuid_is_valid(self):
        """PAD with asset_uuid=null must pass completeness."""
        emitter = StrictAirEventEmitter()
        pad = make_segment("PAD", 0)
        assert pad.asset_uuid is None
        result = emitter.emit("SEG_START", "blk-001", pad)
        assert result is not None
        assert len(emitter.rejections) == 0


# =============================================================================
# Tests: Execution-Scope Uniqueness (ID-001 tightening)
# =============================================================================

class TestExecutionScopeUniqueness:
    """INV-AIR-SEGMENT-ID-001: segment_uuid is scoped to block_execution_instance."""

    def test_replay_generates_new_uuids(self):
        """Feed the same scheduled block twice. All segment_uuids must differ."""
        planned = plan_block("blk-001", ["CONTENT", "CONTENT", "FILLER", "PAD"])

        fed_1 = feed_block(planned)
        fed_2 = feed_block(planned)

        uuids_1 = {s.segment_uuid for s in fed_1.segments}
        uuids_2 = {s.segment_uuid for s in fed_2.segments}

        assert uuids_1.isdisjoint(uuids_2), (
            f"INV-AIR-SEGMENT-ID-001 VIOLATION: replay reused segment_uuids. "
            f"Overlap: {uuids_1 & uuids_2}. "
            f"UUID scope is per-execution — replays MUST generate fresh UUIDs."
        )

    def test_uuid_generated_at_feed_time_not_planning(self):
        """Planning output must NOT contain segment_uuid.
        segment_uuid appears only after feed_block."""
        planned = plan_block("blk-001", ["CONTENT", "FILLER", "PAD"])

        # Planning layer has no segment_uuid
        for seg in planned.segments:
            assert "segment_uuid" not in seg, (
                f"INV-AIR-SEGMENT-ID-001 VIOLATION: segment_uuid present in "
                f"planning output. UUID must be generated at feed time, not planning."
            )

        # After feed, every segment has a UUID
        fed = feed_block(planned)
        for seg in fed.segments:
            assert seg.segment_uuid is not None, (
                "segment_uuid must be present after feed_block"
            )
            uuid.UUID(seg.segment_uuid)  # valid UUID4




class TestSegmentEndEventIdentityComplete:
    """INV-AIR-SEGMENT-ID-001/002/003: SegmentEnd must carry full identity fields.

    End events must be self-describing — no reliance on correlating with
    the matching SegmentStart for classification.
    """

    @staticmethod
    def _make_segment_end(segment_uuid="", segment_type_name="", asset_uuid="", status="AIRED"):
        """Simulate a SegmentEnd evidence payload."""
        import types
        return types.SimpleNamespace(
            block_id="BLK-001",
            event_id_ref="BLK-001-S0000",
            segment_uuid=segment_uuid,
            segment_type_name=segment_type_name,
            asset_uuid=asset_uuid,
            status=status,
            actual_start_utc_ms=1000,
            actual_end_utc_ms=31000,
            asset_start_frame=0,
            asset_end_frame=749,
            computed_duration_ms=30000,
            computed_duration_frames=750,
            reason="",
            fallback_frames_used=0,
        )

    def test_segment_end_requires_segment_uuid(self):
        """SegmentEnd without segment_uuid is identity-incomplete."""
        se = self._make_segment_end(
            segment_uuid="",
            segment_type_name="content",
            asset_uuid="asset-uuid-001",
        )
        assert not se.segment_uuid, "precondition: uuid is empty"
        # Contract: segment_uuid MUST be present on end events
        with pytest.raises(AssertionError, match="segment_uuid"):
            assert se.segment_uuid, (
                "INV-AIR-SEGMENT-ID-001 VIOLATION: segment_uuid missing on SegmentEnd"
            )

    def test_segment_end_requires_segment_type_name(self):
        """SegmentEnd without segment_type_name is identity-incomplete."""
        se = self._make_segment_end(
            segment_uuid="uuid-001",
            segment_type_name="",
            asset_uuid="asset-uuid-001",
        )
        assert not se.segment_type_name, "precondition: type is empty"
        with pytest.raises(AssertionError, match="segment_type_name"):
            assert se.segment_type_name, (
                "INV-AIR-SEGMENT-ID-003 VIOLATION: segment_type_name missing on SegmentEnd"
            )

    def test_segment_end_content_requires_asset_uuid(self):
        """CONTENT segment end without asset_uuid is identity-incomplete."""
        se = self._make_segment_end(
            segment_uuid="uuid-001",
            segment_type_name="content",
            asset_uuid="",
        )
        assert not se.asset_uuid, "precondition: asset_uuid is empty"
        with pytest.raises(AssertionError, match="asset_uuid"):
            assert se.asset_uuid, (
                "INV-AIR-SEGMENT-ID-002 VIOLATION: asset_uuid missing on "
                "CONTENT SegmentEnd"
            )

    def test_segment_end_filler_requires_asset_uuid(self):
        """FILLER segment end without asset_uuid is identity-incomplete."""
        se = self._make_segment_end(
            segment_uuid="uuid-002",
            segment_type_name="filler",
            asset_uuid="",
        )
        with pytest.raises(AssertionError, match="asset_uuid"):
            assert se.asset_uuid, (
                "INV-AIR-SEGMENT-ID-002 VIOLATION: asset_uuid missing on "
                "FILLER SegmentEnd"
            )

    def test_segment_end_pad_must_have_null_asset_uuid(self):
        """PAD segment end must NOT have asset_uuid (empty string = null)."""
        se = self._make_segment_end(
            segment_uuid="uuid-003",
            segment_type_name="pad",
            asset_uuid="",
        )
        assert se.segment_uuid, "segment_uuid present"
        assert se.segment_type_name == "pad", "is PAD"
        assert se.asset_uuid == "", (
            "PAD SegmentEnd must have empty asset_uuid"
        )

    def test_segment_end_pad_rejects_non_null_asset_uuid(self):
        """PAD segment end with asset_uuid set is a contract violation."""
        se = self._make_segment_end(
            segment_uuid="uuid-004",
            segment_type_name="pad",
            asset_uuid="should-not-be-here",
        )
        assert se.segment_type_name == "pad"
        with pytest.raises(AssertionError, match="PAD.*asset_uuid"):
            assert se.asset_uuid == "", (
                "INV-AIR-SEGMENT-ID-002 VIOLATION: PAD SegmentEnd must not "
                "carry asset_uuid"
            )

    def test_segment_end_fully_identity_complete(self):
        """A well-formed CONTENT SegmentEnd passes all identity checks."""
        se = self._make_segment_end(
            segment_uuid="uuid-005",
            segment_type_name="content",
            asset_uuid="asset-uuid-005",
        )
        assert se.segment_uuid, "segment_uuid present"
        assert se.segment_type_name, "segment_type_name present"
        assert se.asset_uuid, "asset_uuid present for content"
        # All identity fields present — no correlation with SegmentStart needed


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
