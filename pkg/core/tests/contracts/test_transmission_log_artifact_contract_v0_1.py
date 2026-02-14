"""
Contract Tests — TransmissionLogArtifactContract_v0.1

Tests assert artifact format and invariants from
docs/contracts/core/TransmissionLogArtifactContract_v0.1.md.
Uses golden fixtures under tests/contracts/fixtures/logs/.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "logs"
GOLDEN_DATE = "2026-02-13"
GOLDEN_TLOG = FIXTURES_DIR / f"sample_{GOLDEN_DATE}.tlog"
GOLDEN_TLOG_JSONL = FIXTURES_DIR / f"sample_{GOLDEN_DATE}.tlog.jsonl"

# Fixed widths from contract: TIME 8, DUR 8, TYPE 8, EVENT_ID 32, TITLE_ASSET remainder
TW_TIME, TW_DUR, TW_TYPE, TW_EVENT_ID = 8, 8, 8, 32


def _tlog_required_header_lines() -> list[str]:
    return [
        "# RETROVUE TRANSMISSION LOG",
        "# CHANNEL:",
        "# DATE:",
        "# TIMEZONE_DISPLAY:",
        "# GENERATED_UTC:",
        "# TRANSMISSION_LOG_ID:",
        "# VERSION: 1",
    ]


def _parse_tlog_body(content: str) -> list[dict]:
    """Parse .tlog body into list of row dicts (time, dur, type, event_id, title_asset)."""
    lines = content.strip().splitlines()
    rows = []
    # Column positions with single space between: TIME(8) sp DUR(8) sp TYPE(8) sp EVENT_ID(32) sp TITLE
    off_time, off_dur, off_type, off_ev, off_title = 0, 9, 18, 27, 60
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("-"):
            continue
        if "TIME" in line and "DUR" in line and "TYPE" in line:
            continue
        if len(line) < off_title:
            continue
        time_s = line[0:8].strip()
        dur_s = line[9:17].strip()
        type_s = line[18:26].strip()
        event_id = line[27:59].strip()
        title_asset = line[60:].strip()
        rows.append(
            {
                "time": time_s,
                "dur": dur_s,
                "type": type_s,
                "event_id": event_id,
                "title_asset": title_asset,
            }
        )
    return rows


def _parse_tlog_full(path: Path) -> tuple[list[str], list[dict]]:
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
    return header_lines, _parse_tlog_body(body_content)


def _parse_tlog_jsonl(path: Path) -> list[dict]:
    """Parse .tlog.jsonl into list of record dicts."""
    records = []
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Fixed-width header + required columns (contract §3)
# ---------------------------------------------------------------------------


def test_tl_artifact_fixed_width_header_and_required_columns():
    """Fixed-width format: required header lines and body column structure."""
    header_lines, body_rows = _parse_tlog_full(GOLDEN_TLOG)
    required = _tlog_required_header_lines()
    for req in required:
        matching = [h for h in header_lines if h.strip().startswith(req.strip())]
        assert len(matching) == 1, f"Missing or duplicate header line starting with {req!r}"
    assert len(body_rows) >= 1
    valid_types = {"BLOCK", "PROGRAM", "AD", "PROMO", "FENCE"}
    for row in body_rows:
        assert row["event_id"], f"Empty event_id in row {row}"
        assert row["type"] in valid_types, f"Invalid TYPE in row {row}"
        assert len(row["time"]) <= TW_TIME and ":" in row["time"]
        assert len(row["dur"]) <= TW_DUR and ":" in row["dur"]


# ---------------------------------------------------------------------------
# TL-ART-004 — UTC_START/UTC_END on BLOCK line and fence
# ---------------------------------------------------------------------------


def test_tl_art_004_block_line_has_utc_start_and_utc_end():
    """TL-ART-004: TYPE=BLOCK line MUST include UTC_START and UTC_END in TITLE_ASSET."""
    _, body_rows = _parse_tlog_full(GOLDEN_TLOG)
    block_rows = [r for r in body_rows if r["type"] == "BLOCK" and not r["event_id"].endswith("-FENCE")]
    assert block_rows, "Golden fixture must contain at least one BLOCK line"
    for row in block_rows:
        notes = row["title_asset"]
        assert "UTC_START=" in notes, f"BLOCK line missing UTC_START: {row}"
        assert "UTC_END=" in notes, f"BLOCK line missing UTC_END: {row}"
        assert re.search(r"UTC_START=\d{4}-\d{2}-\d{2}T[\d:]+Z", notes), "UTC_START must be ISO8601-like"
        assert re.search(r"UTC_END=\d{4}-\d{2}-\d{2}T[\d:]+Z", notes), "UTC_END must be ISO8601-like"


def test_tl_art_004_fence_line_has_utc_end():
    """TL-ART-004: FENCE line MUST include UTC_END in TITLE_ASSET."""
    _, body_rows = _parse_tlog_full(GOLDEN_TLOG)
    fence_rows = [r for r in body_rows if r["type"] == "FENCE"]
    assert fence_rows, "Golden fixture must contain at least one FENCE line"
    for row in fence_rows:
        assert "UTC_END=" in row["title_asset"], f"FENCE line missing UTC_END: {row}"
        assert re.search(r"UTC_END=\d{4}-\d{2}-\d{2}T[\d:]+Z", row["title_asset"])


# ---------------------------------------------------------------------------
# TL-ART-006 — Bijection .tlog ↔ .tlog.jsonl
# ---------------------------------------------------------------------------


def test_tl_art_006_bijection_tlog_to_jsonl():
    """TL-ART-006: Every EVENT_ID in .tlog appears exactly once in .tlog.jsonl with matching type/timing."""
    _, body_rows = _parse_tlog_full(GOLDEN_TLOG)
    jsonl_records = _parse_tlog_jsonl(GOLDEN_TLOG_JSONL)
    tlog_by_id = {r["event_id"]: r for r in body_rows}
    jsonl_by_id = {r["event_id"]: r for r in jsonl_records}
    assert set(tlog_by_id) == set(jsonl_by_id), "Event ID set must match between .tlog and .tlog.jsonl"
    for event_id, trow in tlog_by_id.items():
        jrow = jsonl_by_id[event_id]
        assert jrow["type"] == trow["type"], f"type mismatch for {event_id}"
        assert "scheduled_start_utc" in jrow
        assert "scheduled_duration_ms" in jrow
        assert "block_id" in jrow


def test_tl_art_006_bijection_jsonl_to_tlog():
    """TL-ART-006: Every record in .tlog.jsonl appears exactly once in .tlog (vice versa)."""
    _, body_rows = _parse_tlog_full(GOLDEN_TLOG)
    jsonl_records = _parse_tlog_jsonl(GOLDEN_TLOG_JSONL)
    tlog_ids = {r["event_id"] for r in body_rows}
    jsonl_ids = {r["event_id"] for r in jsonl_records}
    assert jsonl_ids <= tlog_ids, "Every JSONL event_id must appear in .tlog"
    assert tlog_ids <= jsonl_ids, "Every .tlog event_id must appear in JSONL"
