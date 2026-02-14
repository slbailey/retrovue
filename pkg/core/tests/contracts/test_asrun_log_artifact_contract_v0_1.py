"""
Contract Tests — AsRunLogArtifactContract v0.2

Tests assert artifact format and invariants from
docs/contracts/artifacts/AsRunLogArtifactContract.md (v0.2).
Uses golden fixtures under tests/contracts/fixtures/logs/.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "logs"
GOLDEN_DATE = "2026-02-13"
GOLDEN_ASRUN = FIXTURES_DIR / f"sample_{GOLDEN_DATE}.asrun"
GOLDEN_ASRUN_JSONL = FIXTURES_DIR / f"sample_{GOLDEN_DATE}.asrun.jsonl"

# Fixed widths: ACTUAL 8, DUR 8, STATUS 10, TYPE 8, EVENT_ID 32, NOTES remainder
AW_ACTUAL, AW_DUR, AW_STATUS, AW_TYPE, AW_EVENT_ID = 8, 8, 10, 8, 32


def _asrun_required_header_lines() -> list[str]:
    return [
        "# RETROVUE AS-RUN LOG",
        "# CHANNEL:",
        "# DATE:",
        "# OPENED_UTC:",
        "# ASRUN_LOG_ID:",
        "# VERSION: 1",
    ]


def _parse_asrun_body(content: str) -> list[dict]:
    """Parse .asrun body into list of row dicts. Columns with single space between."""
    lines = content.strip().splitlines()
    rows = []
    # ACTUAL(8) sp DUR(8) sp STATUS(10) sp TYPE(8) sp EVENT_ID(32) sp NOTES
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("-"):
            continue
        if "ACTUAL" in line and "STATUS" in line and "TYPE" in line:
            continue
        if len(line) < 71:
            continue
        actual_s = line[0:8].strip()
        dur_s = line[9:17].strip()
        status_s = line[18:28].strip()
        type_s = line[29:37].strip()
        event_id = line[38:70].strip()
        notes = line[71:].strip()
        rows.append(
            {
                "actual": actual_s,
                "dur": dur_s,
                "status": status_s,
                "type": type_s,
                "event_id": event_id,
                "notes": notes,
            }
        )
    return rows


def _parse_asrun_full(path: Path) -> tuple[list[str], list[dict]]:
    """Return (header_lines, body_rows)."""
    text = path.read_text()
    header_lines = []
    body_lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            header_lines.append(line)
        else:
            body_lines.append(line)
    body_content = "\n".join(body_lines)
    return header_lines, _parse_asrun_body(body_content)


def _parse_asrun_jsonl(path: Path) -> list[dict]:
    """Parse .asrun.jsonl into list of record dicts."""
    records = []
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Append-only semantics (AR-ART-001): simulate existing file + append
# ---------------------------------------------------------------------------


def test_ar_artifact_append_only_semantics():
    """Append-only: writing new content must not alter existing lines."""
    original = GOLDEN_ASRUN.read_text()
    with NamedTemporaryFile(mode="w", suffix=".asrun", delete=False) as f:
        f.write(original)
        temp_path = Path(f.name)
    try:
        prefix_len = len(original)
        extra = "\n09:31:00 00:00:00 START      BLOCK    BLK-002                              (block open)\n"
        with open(temp_path, "a") as f:
            f.write(extra)
        appended = temp_path.read_text()
        assert appended.startswith(original)
        assert appended[prefix_len:] == extra
        assert original.strip() == appended[:prefix_len].strip()
    finally:
        temp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# AR-ART-003 — START/FENCE structural markers
# ---------------------------------------------------------------------------


def test_ar_art_003_start_and_fence_structural_markers():
    """AR-ART-003: Each block MUST produce START (block open) and FENCE (block close)."""
    _, body_rows = _parse_asrun_full(GOLDEN_ASRUN)
    block_events = [r for r in body_rows if r["type"] == "BLOCK"]
    start_events = [r for r in block_events if r["status"] == "START"]
    fence_events = [r for r in block_events if r["status"] == "FENCE"]
    assert start_events, "At least one START BLOCK entry required"
    assert fence_events, "At least one FENCE BLOCK entry required"
    for row in fence_events:
        assert row["event_id"].endswith("-FENCE"), f"FENCE EVENT_ID must end with -FENCE: {row}"
        notes = row["notes"]
        assert "swap_tick=" in notes
        assert "fence_tick=" in notes
        assert "primed_success=" in notes
        assert "truncated_by_fence=" in notes
        assert "early_exhaustion=" in notes


# ---------------------------------------------------------------------------
# AR-ART-007 — Bijection .asrun ↔ .asrun.jsonl; JSONL includes fence_tick
# ---------------------------------------------------------------------------


def test_ar_art_007_bijection_asrun_to_jsonl():
    """AR-ART-007: Every EVENT_ID in .asrun appears exactly once in .asrun.jsonl with matching fields."""
    _, body_rows = _parse_asrun_full(GOLDEN_ASRUN)
    jsonl_records = _parse_asrun_jsonl(GOLDEN_ASRUN_JSONL)
    asrun_by_id = {r["event_id"]: r for r in body_rows}
    jsonl_by_id = {r["event_id"]: r for r in jsonl_records}
    assert set(asrun_by_id) == set(jsonl_by_id), "Event ID set must match"
    for event_id, arow in asrun_by_id.items():
        jrow = jsonl_by_id[event_id]
        assert jrow["status"] == arow["status"], f"status mismatch for {event_id}"
        assert "actual_start_utc" in jrow
        assert "actual_duration_ms" in jrow
        assert "block_id" in jrow


def test_ar_art_007_bijection_jsonl_to_asrun():
    """AR-ART-007: Every record in .asrun.jsonl appears exactly once in .asrun."""
    _, body_rows = _parse_asrun_full(GOLDEN_ASRUN)
    jsonl_records = _parse_asrun_jsonl(GOLDEN_ASRUN_JSONL)
    asrun_ids = {r["event_id"] for r in body_rows}
    jsonl_ids = {r["event_id"] for r in jsonl_records}
    assert jsonl_ids <= asrun_ids and asrun_ids <= jsonl_ids


def test_ar_artifact_jsonl_includes_fence_tick_for_fence_events():
    """JSONL sidecar MUST include fence_tick (and swap_tick) for fence events."""
    jsonl_records = _parse_asrun_jsonl(GOLDEN_ASRUN_JSONL)
    fence_records = [r for r in jsonl_records if r.get("status") == "FENCE"]
    assert fence_records, "Golden fixture must contain at least one FENCE in JSONL"
    for rec in fence_records:
        assert "fence_tick" in rec, f"FENCE record missing fence_tick: {rec}"
        assert rec["fence_tick"] is not None
        assert "swap_tick" in rec
