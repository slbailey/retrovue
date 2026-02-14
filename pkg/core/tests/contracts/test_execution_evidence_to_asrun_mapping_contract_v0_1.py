"""
Contract Tests — ExecutionEvidenceToAsRunMappingContract_v0.1

Tests assert that synthetic execution evidence is mapped to .asrun and .asrun.jsonl
per docs/contracts/core/ExecutionEvidenceToAsRunMappingContract_v0.1.md.
Verifies exact match to golden fixtures and MAP-FAIL-001 (missing SegmentEnd → TRUNCATED).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "logs"
GOLDEN_DATE = "2026-02-13"
GOLDEN_ASRUN = FIXTURES_DIR / f"sample_{GOLDEN_DATE}.asrun"
GOLDEN_ASRUN_JSONL = FIXTURES_DIR / f"sample_{GOLDEN_DATE}.asrun.jsonl"

# Column widths for .asrun body
AW_ACTUAL, AW_DUR, AW_STATUS, AW_TYPE, AW_EVENT_ID = 8, 8, 10, 8, 32


def _ms_to_hhmmss(ms: int) -> str:
    """Convert milliseconds to HH:MM:SS."""
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _iso_to_display_time(iso_utc: str) -> str:
    """Convert ISO8601 UTC to display HH:MM:SS (contract says display TZ; we use UTC for golden)."""
    from datetime import datetime

    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.strftime("%H:%M:%S")


class EvidenceToAsRunMapper:
    """
    Reference mapper: execution evidence → .asrun lines + .asrun.jsonl lines.
    Contract: ExecutionEvidenceToAsRunMappingContract_v0.1.
    """

    def __init__(self, segment_type_by_event_id: dict[str, str] | None = None):
        self.segment_type_by_event_id = segment_type_by_event_id or {}
        self._pending_starts: dict[str, dict] = {}
        self.asrun_lines: list[str] = []
        self.jsonl_lines: list[dict] = []

    def _emit_line(self, actual: str, dur: str, status: str, type_: str, event_id: str, notes: str):
        # Match golden: fixed-width columns with single space between; NOTES starts at col 71
        line = (
            actual.ljust(AW_ACTUAL)
            + " "
            + dur.ljust(AW_DUR)
            + " "
            + status.ljust(AW_STATUS)
            + " "
            + type_.ljust(AW_TYPE)
            + " "
            + event_id.ljust(AW_EVENT_ID)
            + " "
            + notes
        )
        self.asrun_lines.append(line)

    def _emit_jsonl(
        self,
        event_id: str,
        block_id: str,
        actual_start_utc: str,
        actual_duration_ms: int,
        status: str,
        reason: str | None,
        swap_tick: int | None = None,
        fence_tick: int | None = None,
    ):
        rec = {
            "event_id": event_id,
            "block_id": block_id,
            "actual_start_utc": actual_start_utc,
            "actual_duration_ms": actual_duration_ms,
            "status": status,
            "reason": reason,
            "swap_tick": swap_tick,
            "fence_tick": fence_tick,
        }
        self.jsonl_lines.append(rec)

    def block_start(self, ev: dict):
        """MAP-001: BlockStartEvidence → START entry."""
        block_id = ev["block_id"]
        actual = ev.get("block_start_display_time") or _iso_to_display_time(ev["actual_start_utc"])
        self._emit_line(actual, "00:00:00", "START", "BLOCK", block_id, "(block open)")
        self._emit_jsonl(
            block_id,
            block_id,
            ev["actual_start_utc"],
            0,
            "START",
            None,
            swap_tick=None,
            fence_tick=None,
        )

    def segment_start(self, ev: dict):
        """Store SegmentStartEvidence; no line until SegmentEnd (MAP-002)."""
        self._pending_starts[ev["event_id"]] = ev

    def segment_end(self, ev: dict):
        """MAP-002: SegmentEndEvidence (with paired start) → one segment entry."""
        event_id = ev["event_id"]
        start_ev = self._pending_starts.pop(event_id, None)
        assert start_ev is not None, "SegmentEnd without SegmentStart"
        actual = start_ev.get("display_time") or _iso_to_display_time(start_ev["actual_start_utc"])
        dur_ms = ev["actual_duration_ms"]
        dur = _ms_to_hhmmss(dur_ms)
        status = ev["status"]
        type_ = self.segment_type_by_event_id.get(event_id, "PROGRAM")
        notes = f"ontime=Y fallback={ev.get('fallback_frames_used', 0)}"
        if ev.get("reason"):
            notes += f" reason={ev['reason']}"
        self._emit_line(actual, dur, status, type_, event_id, notes)
        self._emit_jsonl(
            event_id,
            ev["block_id"],
            start_ev["actual_start_utc"],
            dur_ms,
            status,
            ev.get("reason"),
        )

    def block_fence(self, ev: dict):
        """MAP-FAIL-001: Pending segment starts → TRUNCATED FENCE_TERMINATION. Then MAP-003: FENCE."""
        block_id = ev["block_id"]
        for event_id, start_ev in list(self._pending_starts.items()):
            if start_ev.get("block_id") == block_id:
                self._pending_starts.pop(event_id)
                actual = _iso_to_display_time(start_ev["actual_start_utc"])
                type_ = self.segment_type_by_event_id.get(event_id, "PROGRAM")
                self._emit_line(
                    actual,
                    "00:00:00",
                    "TRUNCATED",
                    type_,
                    event_id,
                    "truncated_by_fence=Y reason=FENCE_TERMINATION",
                )
                self._emit_jsonl(
                    event_id,
                    block_id,
                    start_ev["actual_start_utc"],
                    0,
                    "TRUNCATED",
                    "FENCE_TERMINATION",
                )
        actual = ev.get("actual_end_display_time") or _iso_to_display_time(ev["actual_end_utc"])
        notes = (
            f"swap_tick={ev['swap_tick']} fence_tick={ev['fence_tick']} "
            f"primed_success={'Y' if ev.get('primed_success') else 'N'} "
            f"truncated_by_fence={'Y' if ev.get('truncated_by_fence') else 'N'} "
            f"early_exhaustion={'Y' if ev.get('early_exhaustion') else 'N'}"
        )
        self._emit_line(actual, "00:00:00", "FENCE", "BLOCK", f"{block_id}-FENCE", notes)
        self._emit_jsonl(
            f"{block_id}-FENCE",
            block_id,
            ev["actual_end_utc"],
            0,
            "FENCE",
            None,
            swap_tick=ev["swap_tick"],
            fence_tick=ev["fence_tick"],
        )


def _golden_asrun_body_lines() -> list[str]:
    """Return just the body data lines from golden .asrun (no header, no separator)."""
    text = GOLDEN_ASRUN.read_text()
    lines = []
    for line in text.splitlines():
        if line.startswith("#") or line.startswith("-") or "ACTUAL" in line and "STATUS" in line:
            continue
        if line.strip():
            lines.append(line)
    return lines


def _golden_asrun_jsonl_records() -> list[dict]:
    """Return list of JSONL records from golden file."""
    records = []
    for line in GOLDEN_ASRUN_JSONL.read_text().strip().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Feed synthetic evidence → produce .asrun and .jsonl; verify exact match to golden
# ---------------------------------------------------------------------------


def test_map_evidence_to_asrun_matches_golden():
    """Synthetic evidence for one block produces .asrun lines and .jsonl matching golden fixtures."""
    segment_types = {"EVT-0001": "PROGRAM", "EVT-0002": "AD"}
    mapper = EvidenceToAsRunMapper(segment_type_by_event_id=segment_types)

    mapper.block_start(
        {
            "block_id": "BLK-001",
            "actual_start_utc": "2026-02-13T14:00:00Z",
            "swap_tick": 900,
            "fence_tick": 10800,
            "primed_success": True,
            "block_start_display_time": "09:00:00",
        }
    )
    mapper.segment_start(
        {
            "event_id": "EVT-0001",
            "block_id": "BLK-001",
            "actual_start_utc": "2026-02-13T14:00:00Z",
            "display_time": "09:00:00",
        }
    )
    mapper.segment_end(
        {
            "event_id": "EVT-0001",
            "block_id": "BLK-001",
            "actual_duration_ms": 1350000,
            "status": "AIRED",
            "reason": None,
            "fallback_frames_used": 0,
        }
    )
    mapper.segment_start(
        {
            "event_id": "EVT-0002",
            "block_id": "BLK-001",
            "actual_start_utc": "2026-02-13T14:22:30Z",
            "display_time": "09:22:30",
        }
    )
    mapper.segment_end(
        {
            "event_id": "EVT-0002",
            "block_id": "BLK-001",
            "actual_duration_ms": 30000,
            "status": "AIRED",
            "reason": None,
            "fallback_frames_used": 0,
        }
    )
    mapper.block_fence(
        {
            "block_id": "BLK-001",
            "actual_end_utc": "2026-02-13T14:30:00Z",
            "actual_end_display_time": "09:30:00",
            "swap_tick": 900,
            "fence_tick": 10800,
            "truncated_by_fence": False,
            "early_exhaustion": False,
            "primed_success": True,
            "ct_at_fence_ms": 0,
            "total_frames_emitted": 0,
        }
    )

    golden_body = _golden_asrun_body_lines()
    assert len(mapper.asrun_lines) == len(golden_body), (
        f"Line count mismatch: got {len(mapper.asrun_lines)}, golden {len(golden_body)}"
    )
    for i, (got, want) in enumerate(zip(mapper.asrun_lines, golden_body)):
        # Compare by parsed fields (ACTUAL 8, DUR 8, STATUS 10, TYPE 8, EVENT_ID 32, NOTES rest)
        def fields(ln: str) -> tuple:
            ln = ln.strip()
            if len(ln) < 71:
                return (ln,)
            return (
                ln[0:8].strip(),
                ln[9:17].strip(),
                ln[18:28].strip(),
                ln[29:37].strip(),
                ln[38:70].strip(),
                ln[71:].strip(),
            )
        assert fields(got) == fields(want), f"Line {i+1} mismatch:\n  got:  {got!r}\n  want: {want!r}"

    golden_jsonl = _golden_asrun_jsonl_records()
    assert len(mapper.jsonl_lines) == len(golden_jsonl)
    for i, (got, want) in enumerate(zip(mapper.jsonl_lines, golden_jsonl)):
        for key in want:
            assert key in got, f"JSONL record {i+1} missing key {key}"
            assert got[key] == want[key], f"JSONL record {i+1} key {key}: got {got[key]!r} want {want[key]!r}"


# ---------------------------------------------------------------------------
# MAP-FAIL-001 — Missing SegmentEnd before fence → TRUNCATED with reason FENCE_TERMINATION
# ---------------------------------------------------------------------------


def test_map_fail_001_missing_segment_end_before_fence_truncated_fence_termination():
    """MAP-FAIL-001: Segment start without SegmentEnd before fence → TRUNCATED, reason FENCE_TERMINATION."""
    mapper = EvidenceToAsRunMapper(segment_type_by_event_id={"EVT-0001": "PROGRAM", "EVT-OPEN": "PROMO"})

    mapper.block_start(
        {
            "block_id": "BLK-001",
            "actual_start_utc": "2026-02-13T14:00:00Z",
            "swap_tick": 900,
            "fence_tick": 10800,
            "primed_success": True,
            "block_start_display_time": "09:00:00",
        }
    )
    mapper.segment_start(
        {
            "event_id": "EVT-0001",
            "block_id": "BLK-001",
            "actual_start_utc": "2026-02-13T14:00:00Z",
            "display_time": "09:00:00",
        }
    )
    mapper.segment_end(
        {
            "event_id": "EVT-0001",
            "block_id": "BLK-001",
            "actual_duration_ms": 1350000,
            "status": "AIRED",
            "reason": None,
            "fallback_frames_used": 0,
        }
    )
    mapper.segment_start(
        {
            "event_id": "EVT-OPEN",
            "block_id": "BLK-001",
            "actual_start_utc": "2026-02-13T14:22:30Z",
            "display_time": "09:22:30",
        }
    )
    mapper.block_fence(
        {
            "block_id": "BLK-001",
            "actual_end_utc": "2026-02-13T14:30:00Z",
            "swap_tick": 900,
            "fence_tick": 10800,
            "truncated_by_fence": True,
            "early_exhaustion": False,
            "primed_success": True,
            "ct_at_fence_ms": 0,
            "total_frames_emitted": 0,
        }
    )

    asrun_str = "\n".join(mapper.asrun_lines)
    assert "TRUNCATED" in asrun_str
    assert "EVT-OPEN" in asrun_str
    assert "FENCE_TERMINATION" in asrun_str or "truncated_by_fence=Y" in asrun_str

    truncated_jsonl = [r for r in mapper.jsonl_lines if r["status"] == "TRUNCATED"]
    assert len(truncated_jsonl) == 1
    assert truncated_jsonl[0]["event_id"] == "EVT-OPEN"
    assert truncated_jsonl[0]["reason"] == "FENCE_TERMINATION"
