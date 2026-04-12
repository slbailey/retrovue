"""
Contract tests: Pad As-Run Suppression — INV-PAD-ASRUN-SUPPRESS-001 and related

Validates that pad segments are correctly suppressed from .asrun text output
while being preserved in .asrun.jsonl:

- INV-PAD-ASRUN-SUPPRESS-001: pad SEG_START and terminal not in .asrun text
- INV-PAD-ASRUN-JSONL-PRESERVED-001: pad events preserved in .jsonl
- INV-PAD-ASRUN-SCOPE-001: Option A vs Option B equivalence
- Integration: time continuity with suppressed pads

Tests mock the evidence_server's _process_evidence method using SimpleNamespace
proto-like objects and a MockWriter that captures write_and_flush vs write_jsonl_only
calls.
"""

from __future__ import annotations

import types
from dataclasses import dataclass, field

import pytest

# The evidence_server imports proto stubs dynamically. We need to test
# _process_evidence which operates on proto message objects. We mock these
# with SimpleNamespace.

try:
    from retrovue.runtime.evidence_server import EvidenceServicer, _format_asrun_line
    _HAS_EVIDENCE_SERVER = True
except ImportError:
    _HAS_EVIDENCE_SERVER = False

try:
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
    from retrovue.runtime.traffic_manager import fill_ad_blocks
    from retrovue.runtime.traffic_policy import TrafficPolicy
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not yet implemented",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCK_ID = "BLK-PAD-TEST"
CHANNEL_ID = "test-ch"
SESSION_ID = "sess-001"
BASE_EPOCH_MS = 1_700_000_000_000  # ~2023 epoch for display_time math


# ---------------------------------------------------------------------------
# Mock writer that captures asrun vs jsonl calls
# ---------------------------------------------------------------------------

class MockWriter:
    """Captures write_and_flush vs write_jsonl_only calls for assertion."""

    def __init__(self):
        self.asrun_lines: list[str] = []
        self.jsonl_records: list[dict] = []
        self._day_start_epoch_ms = BASE_EPOCH_MS

    def display_time(self, epoch_ms: int) -> str:
        offset_s = (epoch_ms - self._day_start_epoch_ms) // 1000
        if offset_s < 0:
            return "00:00:00"
        h, rem = divmod(offset_s, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def write_and_flush(self, asrun_line: str, jsonl_record: dict) -> None:
        self.asrun_lines.append(asrun_line)
        self.jsonl_records.append(jsonl_record)

    def write_jsonl_only(self, jsonl_record: dict) -> None:
        self.jsonl_records.append(jsonl_record)


# ---------------------------------------------------------------------------
# Proto-like mock objects
# ---------------------------------------------------------------------------

def _make_evidence_msg(payload_name: str, **payload_kwargs):
    """Build a fake EvidenceFromAir proto-like message."""
    payload_obj = types.SimpleNamespace(**payload_kwargs)
    msg = types.SimpleNamespace(
        channel_id=CHANNEL_ID,
        playout_session_id=SESSION_ID,
        sequence=1,
        event_uuid="",
    )
    setattr(msg, payload_name, payload_obj)

    def which_oneof(name):
        return payload_name
    msg.WhichOneof = which_oneof
    return msg, payload_name


def _segment_start_msg(
    event_id: str,
    segment_index: int,
    segment_type_name: str,
    actual_start_utc_ms: int,
    asset_uri: str = "",
    segment_title: str = "",
    segment_uuid: str = "",
    asset_uuid: str = "",
    asset_start_frame: int = 0,
    scheduled_duration_ms: int = 30_000,
    join_in_progress: bool = False,
):
    return _make_evidence_msg(
        "segment_start",
        event_id=event_id,
        block_id=BLOCK_ID,
        segment_index=segment_index,
        segment_type_name=segment_type_name,
        segment_title=segment_title,
        asset_uri=asset_uri,
        segment_uuid=segment_uuid,
        asset_uuid=asset_uuid,
        actual_start_utc_ms=actual_start_utc_ms,
        asset_start_frame=asset_start_frame,
        scheduled_duration_ms=scheduled_duration_ms,
        join_in_progress=join_in_progress,
    )


def _segment_end_msg(
    event_id: str,
    actual_start_utc_ms: int,
    actual_end_utc_ms: int,
    computed_duration_ms: int,
    computed_duration_frames: int,
    segment_type_name: str = "",
    asset_uuid: str = "",
    segment_uuid: str = "",
    status: str = "AIRED",
    asset_start_frame: int = 0,
    asset_end_frame: int = 0,
    fallback_frames_used: int = 0,
    reason: str = "",
):
    return _make_evidence_msg(
        "segment_end",
        event_id_ref=event_id,
        block_id=BLOCK_ID,
        status=status,
        actual_start_utc_ms=actual_start_utc_ms,
        actual_end_utc_ms=actual_end_utc_ms,
        computed_duration_ms=computed_duration_ms,
        computed_duration_frames=computed_duration_frames,
        segment_type_name=segment_type_name,
        asset_uuid=asset_uuid,
        segment_uuid=segment_uuid,
        asset_start_frame=asset_start_frame,
        asset_end_frame=asset_end_frame,
        fallback_frames_used=fallback_frames_used,
        reason=reason,
    )


def _block_start_msg(actual_start_utc_ms: int, swap_tick: int = 900, fence_tick: int = 900):
    return _make_evidence_msg(
        "block_start",
        block_id=BLOCK_ID,
        actual_start_utc_ms=actual_start_utc_ms,
        swap_tick=swap_tick,
        fence_tick=fence_tick,
    )


def _block_fence_msg(actual_end_utc_ms: int, swap_tick: int = 10800, fence_tick: int = 10800):
    return _make_evidence_msg(
        "block_fence",
        block_id=BLOCK_ID,
        actual_end_utc_ms=actual_end_utc_ms,
        swap_tick=swap_tick,
        fence_tick=fence_tick,
        total_frames_emitted=10800,
        primed_success=True,
        truncated_by_fence=False,
        early_exhaustion=False,
        frame_budget_remaining=0,
    )


def _process(servicer, writer, msg, payload_name, emitted_terminals,
             last_segment_index, last_block_start_utc_ms,
             last_asset_end_frame, join_in_progress, last_segment_uuid):
    """Call _process_evidence with the standard argument structure."""
    servicer._process_evidence(
        writer, msg, payload_name, emitted_terminals,
        last_segment_index, last_block_start_utc_ms,
        last_asset_end_frame, join_in_progress, last_segment_uuid,
    )


# ---------------------------------------------------------------------------
# Shared test fixture: a typical break sequence with pad
# ---------------------------------------------------------------------------

def _run_evidence_sequence(servicer, writer):
    """Feed a standard evidence sequence: content → filler → pad → filler → pad → fence.

    Returns the shared state objects for further inspection.
    """
    emitted_terminals: set[tuple[str, int]] = set()
    last_seg_idx = [-1]
    last_block_start = [None]
    last_asset_end = {}
    jip_by_event = {}
    last_seg_uuid = [""]

    t0 = BASE_EPOCH_MS

    # Block start
    msg, name = _block_start_msg(t0)
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)

    # Segment 0: content (1200s = 1,200,000ms)
    t_content_start = t0
    t_content_end = t0 + 1_200_000
    msg, name = _segment_start_msg("EVT-001", 0, "content", t_content_start,
                                    asset_uri="show.ts", segment_title="Show")
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)
    msg, name = _segment_end_msg("EVT-001", t_content_start, t_content_end,
                                  1_200_000, 36000, segment_type_name="content",
                                  asset_end_frame=35999)
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)

    # Segment 1: filler (30s)
    t1_start = t_content_end
    t1_end = t1_start + 30_000
    msg, name = _segment_start_msg("EVT-002", 1, "filler", t1_start,
                                    asset_uri="promo_a.ts", segment_title="Promo A")
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)
    msg, name = _segment_end_msg("EVT-002", t1_start, t1_end, 30_000, 900,
                                  segment_type_name="filler", asset_end_frame=899)
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)

    # Segment 2: pad (2s)
    t2_start = t1_end
    t2_end = t2_start + 2_000
    msg, name = _segment_start_msg("EVT-003", 2, "pad", t2_start,
                                    segment_title="BLACK")
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)
    msg, name = _segment_end_msg("EVT-003", t2_start, t2_end, 2_000, 60,
                                  segment_type_name="pad", asset_end_frame=59)
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)

    # Segment 3: filler (30s)
    t3_start = t2_end
    t3_end = t3_start + 30_000
    msg, name = _segment_start_msg("EVT-004", 3, "filler", t3_start,
                                    asset_uri="promo_b.ts", segment_title="Promo B")
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)
    msg, name = _segment_end_msg("EVT-004", t3_start, t3_end, 30_000, 900,
                                  segment_type_name="filler", asset_end_frame=899)
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)

    # Segment 4: pad (2s)
    t4_start = t3_end
    t4_end = t4_start + 2_000
    msg, name = _segment_start_msg("EVT-005", 4, "pad", t4_start,
                                    segment_title="BLACK")
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)
    msg, name = _segment_end_msg("EVT-005", t4_start, t4_end, 2_000, 60,
                                  segment_type_name="pad", asset_end_frame=59)
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)

    # Block fence
    msg, name = _block_fence_msg(t4_end)
    _process(servicer, writer, msg, name, emitted_terminals,
             last_seg_idx, last_block_start, last_asset_end, jip_by_event, last_seg_uuid)

    return {
        "t_content_end": t_content_end,
        "t1_start": t1_start,
        "t1_end": t1_end,
        "t2_start": t2_start,
        "t2_end": t2_end,
        "t3_start": t3_start,
        "t3_end": t3_end,
        "t4_start": t4_start,
        "t4_end": t4_end,
    }


# ===========================================================================
# INV-PAD-ASRUN-SUPPRESS-001
# ===========================================================================


@pytest.mark.skipif(not _HAS_EVIDENCE_SERVER, reason="evidence_server not importable")
class TestPadAsRunSuppress:
    """INV-PAD-ASRUN-SUPPRESS-001: pad not in .asrun text."""

    def _make_servicer(self):
        return EvidenceServicer.__new__(EvidenceServicer)

    def test_pad_segment_start_not_in_asrun_text(self):
        """No PAD lines in .asrun text; content and filler are present."""
        servicer = self._make_servicer()
        writer = MockWriter()
        _run_evidence_sequence(servicer, writer)

        # asrun_lines should NOT contain any PAD type entries
        for line in writer.asrun_lines:
            assert "PAD" not in line.split(), (
                f"INV-PAD-ASRUN-SUPPRESS-001: PAD found in .asrun: {line}"
            )

        # Content and filler lines should be present
        asrun_text = "\n".join(writer.asrun_lines)
        # Should have: START (block), SEG_START (content), AIRED (content),
        # SEG_START (filler1), AIRED (filler1), SEG_START (filler2), AIRED (filler2), FENCE
        # That's 8 lines. No pad lines.
        statuses_in_asrun = []
        for line in writer.asrun_lines:
            parts = line.split()
            if len(parts) >= 3:
                statuses_in_asrun.append(parts[2])
        assert "SEG_START" in statuses_in_asrun
        assert "AIRED" in statuses_in_asrun

    def test_pad_suppression_does_not_affect_adjacent_segments(self):
        """Filler segments have correct timing despite pad suppression."""
        servicer = self._make_servicer()
        writer = MockWriter()
        times = _run_evidence_sequence(servicer, writer)

        # Find filler AIRED records in jsonl
        filler_aired = [
            r for r in writer.jsonl_records
            if r.get("status") == "AIRED" and "filler" in r.get("segment_type_name", r.get("segment_type", ""))
        ]
        # Should be 2 filler AIRED records
        assert len(filler_aired) >= 2

        # The second filler should start after the pad gap
        # (its actual_start_utc_ms should account for pad time)
        second_filler_start = [
            r for r in writer.jsonl_records
            if r.get("status") == "SEG_START" and r.get("segment_index") == 3
        ]
        if second_filler_start:
            assert second_filler_start[0]["actual_start_utc_ms"] == times["t3_start"]

    def test_multiple_pads_all_suppressed(self):
        """Both pad segments suppressed from .asrun text."""
        servicer = self._make_servicer()
        writer = MockWriter()
        _run_evidence_sequence(servicer, writer)

        pad_asrun_lines = [
            line for line in writer.asrun_lines
            if "BLACK" in line or "PAD" in line.split()
        ]
        assert len(pad_asrun_lines) == 0, (
            f"Found {len(pad_asrun_lines)} pad lines in .asrun text"
        )


# ===========================================================================
# INV-PAD-ASRUN-JSONL-PRESERVED-001
# ===========================================================================


@pytest.mark.skipif(not _HAS_EVIDENCE_SERVER, reason="evidence_server not importable")
class TestPadAsRunJsonlPreserved:
    """INV-PAD-ASRUN-JSONL-PRESERVED-001: pad events in .jsonl."""

    def _make_servicer(self):
        return EvidenceServicer.__new__(EvidenceServicer)

    def test_pad_events_written_to_jsonl(self):
        """Both pad events (SEG_START + AIRED) present in jsonl."""
        servicer = self._make_servicer()
        writer = MockWriter()
        _run_evidence_sequence(servicer, writer)

        pad_jsonl = [
            r for r in writer.jsonl_records
            if r.get("segment_type") == "pad" or r.get("segment_type_name") == "pad"
        ]
        # 2 pads × (SEG_START + AIRED) = 4 records
        assert len(pad_jsonl) == 4, (
            f"Expected 4 pad jsonl records, got {len(pad_jsonl)}"
        )

    def test_jsonl_pad_record_has_segment_type(self):
        """Pad jsonl records include segment_type identifying them as pad."""
        servicer = self._make_servicer()
        writer = MockWriter()
        _run_evidence_sequence(servicer, writer)

        pad_jsonl = [
            r for r in writer.jsonl_records
            if r.get("segment_type") == "pad" or r.get("segment_type_name") == "pad"
        ]
        for rec in pad_jsonl:
            seg_type = rec.get("segment_type") or rec.get("segment_type_name")
            assert seg_type == "pad", (
                f"Pad jsonl record missing segment_type: {rec}"
            )


# ===========================================================================
# INV-PAD-ASRUN-SCOPE-001
# ===========================================================================


class TestPadAsRunScope:
    """INV-PAD-ASRUN-SCOPE-001: Option A vs Option B equivalence."""

    @dataclass
    class FakeFillerAsset:
        asset_uri: str
        asset_type: str
        duration_ms: int

    def _make_library(self, *specs):
        class Lib:
            def __init__(self, assets):
                self._assets = assets
            def get_filler_assets(self, max_duration_ms=0, count=5):
                return [a for a in self._assets if a.duration_ms <= max_duration_ms][:count]
        return Lib([self.FakeFillerAsset(*s) for s in specs])

    def _policy(self):
        return TrafficPolicy(
            allowed_types=["commercial", "promo", "filler"],
            default_cooldown_seconds=0,
            type_cooldowns_seconds={},
            max_plays_per_day=0,
        )

    def test_all_current_pad_origins_are_traffic(self):
        """All pads from fill_ad_blocks have spot_index != None."""
        lib = self._make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        break_ms = 100_000
        content_ms = 1_800_000 - break_ms
        block = ScheduledBlock(
            block_id="blk-scope",
            start_utc_ms=10_000_000_000,
            end_utc_ms=10_000_000_000 + 1_800_000,
            segments=(
                ScheduledSegment(
                    segment_type="episode", asset_uri="show.ts",
                    asset_start_offset_ms=0, segment_duration_ms=content_ms,
                    is_primary=True,
                ),
                ScheduledSegment(
                    segment_type="filler", asset_uri="",
                    asset_start_offset_ms=0, segment_duration_ms=break_ms,
                ),
            ),
        )
        result = fill_ad_blocks(
            block,
            filler_uri="/media/filler/bars.ts",
            filler_duration_ms=30_000,
            asset_library=lib,
            policy=self._policy(),
            play_history=[],
            now_ms=10_000_000_000,
            day_start_ms=9_900_000_000,
        )
        pads = [s for s in result.segments if s.segment_type == "pad"]
        for p in pads:
            assert p.spot_index is not None, (
                "INV-PAD-ASRUN-SCOPE-001: traffic pad with spot_index=None "
                "would be incorrectly preserved under Option B"
            )

    def test_non_traffic_pad_not_suppressed_in_option_b(self):
        """Option B: a pad with spot_index=None would NOT be suppressed.

        Documents the future behavior when DSL explicit pad is introduced.
        """
        # Simulate Option B decision logic
        def option_b_suppress(segment_type_name: str, spot_index) -> bool:
            return segment_type_name == "pad" and spot_index is not None

        # DSL pad: spot_index=None → NOT suppressed
        assert not option_b_suppress("pad", None)

    def test_traffic_pad_suppressed_in_option_b(self):
        """Option B: a traffic pad (spot_index != None) IS suppressed."""
        def option_b_suppress(segment_type_name: str, spot_index) -> bool:
            return segment_type_name == "pad" and spot_index is not None

        assert option_b_suppress("pad", 0)
        assert option_b_suppress("pad", 5)

    def test_option_a_and_option_b_equivalent_for_current_system(self):
        """Option A (all pad) and Option B (traffic pad only) produce
        identical suppression decisions for all pads from fill_ad_blocks."""
        lib = self._make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
        )
        break_ms = 62_000
        content_ms = 1_800_000 - break_ms
        block = ScheduledBlock(
            block_id="blk-equiv",
            start_utc_ms=10_000_000_000,
            end_utc_ms=10_000_000_000 + 1_800_000,
            segments=(
                ScheduledSegment(
                    segment_type="episode", asset_uri="show.ts",
                    asset_start_offset_ms=0, segment_duration_ms=content_ms,
                    is_primary=True,
                ),
                ScheduledSegment(
                    segment_type="filler", asset_uri="",
                    asset_start_offset_ms=0, segment_duration_ms=break_ms,
                ),
            ),
        )
        result = fill_ad_blocks(
            block,
            filler_uri="/media/filler/bars.ts",
            filler_duration_ms=30_000,
            asset_library=lib,
            policy=self._policy(),
            play_history=[],
            now_ms=10_000_000_000,
            day_start_ms=9_900_000_000,
        )

        def option_a(seg):
            return seg.segment_type == "pad"

        def option_b(seg):
            return seg.segment_type == "pad" and seg.spot_index is not None

        for seg in result.segments:
            assert option_a(seg) == option_b(seg), (
                f"Option A/B diverge on segment type={seg.segment_type} "
                f"spot_index={seg.spot_index}"
            )


# ===========================================================================
# Integration: as-run pipeline with time continuity
# ===========================================================================


@pytest.mark.skipif(not _HAS_EVIDENCE_SERVER, reason="evidence_server not importable")
class TestIntegrationAsRunPadSuppressionTimeContinuity:
    """Integration test: full evidence pipeline with pad suppression."""

    def _make_servicer(self):
        return EvidenceServicer.__new__(EvidenceServicer)

    def test_integration_asrun_pad_suppression_time_continuity(self):
        """Full evidence sequence: suppression, jsonl, time continuity, AR-ART-008."""
        servicer = self._make_servicer()
        writer = MockWriter()
        times = _run_evidence_sequence(servicer, writer)

        # --- Suppression: no PAD in asrun text ---
        for line in writer.asrun_lines:
            fields = line.split()
            # The type field is at position 3 (ACTUAL DUR STATUS TYPE ...)
            if len(fields) >= 4:
                assert fields[3] != "PAD", (
                    f"PAD found in .asrun text: {line}"
                )

        # --- Count: exactly 3 segment lines in asrun text ---
        # (content SEG_START + AIRED, filler1 SEG_START + AIRED,
        #  filler2 SEG_START + AIRED) = 6 segment lines
        # + 1 START (block) + 1 FENCE = 8 total
        seg_start_lines = [l for l in writer.asrun_lines if "SEG_START" in l]
        aired_lines = [l for l in writer.asrun_lines if "AIRED" in l.split()]
        assert len(seg_start_lines) == 3, f"Expected 3 SEG_START, got {len(seg_start_lines)}"
        assert len(aired_lines) == 3, f"Expected 3 AIRED, got {len(aired_lines)}"

        # --- JSONL preserved: all 5 segments present ---
        seg_start_jsonl = [
            r for r in writer.jsonl_records if r.get("status") == "SEG_START"
        ]
        aired_jsonl = [
            r for r in writer.jsonl_records if r.get("status") == "AIRED"
        ]
        # 5 segments total (content + 2 filler + 2 pad)
        assert len(seg_start_jsonl) == 5, f"Expected 5 SEG_START in jsonl, got {len(seg_start_jsonl)}"
        assert len(aired_jsonl) == 5, f"Expected 5 AIRED in jsonl, got {len(aired_jsonl)}"

        # --- Pad event IDs in jsonl but not in asrun ---
        pad_event_ids = {"EVT-003", "EVT-005"}
        asrun_event_ids = set()
        for line in writer.asrun_lines:
            for eid in ["EVT-001", "EVT-002", "EVT-003", "EVT-004", "EVT-005"]:
                if eid in line:
                    asrun_event_ids.add(eid)
        jsonl_event_ids = {r.get("event_id") for r in writer.jsonl_records}

        for pid in pad_event_ids:
            assert pid not in asrun_event_ids, (
                f"Pad event {pid} found in .asrun text"
            )
            assert pid in jsonl_event_ids, (
                f"Pad event {pid} missing from .jsonl"
            )

        # --- Time continuity: filler2 starts after pad1 ---
        filler2_starts = [
            r for r in writer.jsonl_records
            if r.get("status") == "SEG_START" and r.get("segment_index") == 3
        ]
        assert len(filler2_starts) == 1
        assert filler2_starts[0]["actual_start_utc_ms"] == times["t3_start"]
        # This proves time advanced through the suppressed pad

        # --- AR-ART-008: each non-BLOCK event_id has exactly one terminal ---
        from collections import Counter
        terminal_counts: Counter[str] = Counter()
        for r in writer.jsonl_records:
            if r.get("status") in ("AIRED", "TRUNCATED", "SHORT", "SKIPPED", "ERROR"):
                terminal_counts[r["event_id"]] += 1
        for eid, count in terminal_counts.items():
            assert count == 1, (
                f"AR-ART-008: event {eid} has {count} terminal statuses"
            )
