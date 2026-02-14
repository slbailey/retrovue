"""
Integration tests for TransmissionLogArtifactWriter.

Covers: file format, immutability (TL-ART-001), deterministic regeneration,
JSONL bijection with .tlog, BLOCK UTC boundaries, FENCE UTC_END only.

See: docs/contracts/core/TransmissionLogArtifactContract_v0.1.md
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from retrovue.planning.transmission_log_artifact_writer import (
    TransmissionLogArtifactExistsError,
    TransmissionLogArtifactWriter,
)
from retrovue.runtime.planning_pipeline import TransmissionLog, TransmissionLogEntry


def _make_minimal_log(
    channel_id: str = "test-ch",
    broadcast_date: date | None = None,
    one_block_with_segments: bool = True,
) -> TransmissionLog:
    """Build a minimal TransmissionLog for artifact tests."""
    d = broadcast_date or date(2026, 2, 13)
    base_ms = int(datetime(d.year, d.month, d.day, 14, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    block_dur_ms = 30 * 60 * 1000
    segments = []
    if one_block_with_segments:
        segments = [
            {
                "segment_index": 0,
                "asset_uri": "/media/cheers/s01e01.mp4",
                "segment_duration_ms": 22 * 60 * 1000 + 30 * 1000,
                "segment_type": "episode",
            },
            {
                "segment_index": 1,
                "asset_uri": None,
                "segment_duration_ms": 30 * 1000,
                "segment_type": "ad",
            },
        ]
    entries = [
        TransmissionLogEntry(
            block_id=f"{channel_id}-{d.isoformat()}-0000",
            block_index=0,
            start_utc_ms=base_ms,
            end_utc_ms=base_ms + block_dur_ms,
            segments=segments,
        ),
    ]
    return TransmissionLog(
        channel_id=channel_id,
        broadcast_date=d,
        entries=entries,
        is_locked=True,
        metadata={"grid_block_minutes": 30, "transmission_log_id": "tl-test-001"},
    )


def _parse_tlog_headers(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    return [ln for ln in lines if ln.startswith("#")]


def _parse_tlog_body_rows(path: Path) -> list[dict]:
    """Parse .tlog body into list of row dicts (time, dur, type, event_id, title_asset)."""
    content = path.read_text()
    lines = content.strip().splitlines()
    rows = []
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("-"):
            continue
        if "TIME" in line and "DUR" in line and "TYPE" in line:
            continue
        if len(line) < 60:
            continue
        rows.append({
            "time": line[0:8].strip(),
            "dur": line[9:17].strip(),
            "type": line[18:26].strip(),
            "event_id": line[27:59].strip(),
            "title_asset": line[60:].strip(),
        })
    return rows


def _parse_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().strip().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# 1) File written correctly
# ---------------------------------------------------------------------------


def test_file_written_correctly(tmp_path: Path) -> None:
    """Artifact writer produces .tlog and .tlog.jsonl with correct structure."""
    log = _make_minimal_log(channel_id="ch-A", broadcast_date=date(2026, 2, 13))
    writer = TransmissionLogArtifactWriter(base_path=tmp_path)
    tlog_path = writer.write(
        channel_id=log.channel_id,
        broadcast_date=log.broadcast_date,
        transmission_log=log,
        timezone_display="UTC",
        generated_utc=datetime(2026, 2, 13, 14, 0, 0, tzinfo=timezone.utc),
        transmission_log_id="tl-ch-A-20260213",
    )

    assert tlog_path == tmp_path / "ch-A" / "2026-02-13.tlog"
    assert tlog_path.exists()
    jsonl_path = tlog_path.with_suffix(".tlog.jsonl")
    assert jsonl_path.exists()

    headers = _parse_tlog_headers(tlog_path)
    assert any("# RETROVUE TRANSMISSION LOG" in h for h in headers)
    assert any("CHANNEL: ch-A" in h for h in headers)
    assert any("DATE: 2026-02-13" in h for h in headers)
    assert any("TIMEZONE_DISPLAY: UTC" in h for h in headers)
    assert any("GENERATED_UTC:" in h for h in headers)
    assert any("TRANSMISSION_LOG_ID:" in h for h in headers)
    assert any("VERSION: 1" in h for h in headers)

    rows = _parse_tlog_body_rows(tlog_path)
    assert len(rows) >= 1
    valid_types = {"BLOCK", "PROGRAM", "AD", "PROMO", "FENCE"}
    for row in rows:
        assert row["event_id"], f"Empty event_id in {row}"
        assert row["type"] in valid_types, f"Invalid TYPE in {row}"


# ---------------------------------------------------------------------------
# 2) Immutability enforced (TL-ART-001)
# ---------------------------------------------------------------------------


def test_immutability_enforced(tmp_path: Path) -> None:
    """If .tlog already exists, writer raises TransmissionLogArtifactExistsError."""
    log = _make_minimal_log(channel_id="ch-B", broadcast_date=date(2026, 2, 14))
    writer = TransmissionLogArtifactWriter(base_path=tmp_path)
    writer.write(
        channel_id=log.channel_id,
        broadcast_date=log.broadcast_date,
        transmission_log=log,
        timezone_display="UTC",
    )
    with pytest.raises(TransmissionLogArtifactExistsError) as exc_info:
        writer.write(
            channel_id=log.channel_id,
            broadcast_date=log.broadcast_date,
            transmission_log=log,
            timezone_display="UTC",
        )
    assert "TL-ART-001" in str(exc_info.value) or "already exists" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 3) Deterministic regeneration produces identical file
# ---------------------------------------------------------------------------


def test_deterministic_regeneration_produces_identical_file(tmp_path: Path) -> None:
    """Same inputs and fixed generated_utc/transmission_log_id produce identical .tlog body."""
    log = _make_minimal_log(channel_id="ch-C", broadcast_date=date(2026, 2, 15))
    fixed_utc = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
    fixed_id = "tl-deterministic-001"
    writer = TransmissionLogArtifactWriter(base_path=tmp_path)

    path1 = tmp_path / "ch-C" / "2026-02-15.tlog"
    path1.parent.mkdir(parents=True, exist_ok=True)
    # First write to a different channel/date so we can write twice
    writer.write(
        channel_id="ch-C",
        broadcast_date=date(2026, 2, 15),
        transmission_log=log,
        timezone_display="UTC",
        generated_utc=fixed_utc,
        transmission_log_id=fixed_id,
    )
    content1 = path1.read_text()
    body1 = "\n".join(ln for ln in content1.splitlines() if not ln.startswith("#") and ln.strip())

    # Second run: use a new channel/date so we don't hit immutability
    log2 = _make_minimal_log(channel_id="ch-C2", broadcast_date=date(2026, 2, 16))
    writer.write(
        channel_id="ch-C2",
        broadcast_date=date(2026, 2, 16),
        transmission_log=log2,
        timezone_display="UTC",
        generated_utc=fixed_utc,
        transmission_log_id="tl-deterministic-002",
    )
    path2 = tmp_path / "ch-C2" / "2026-02-16.tlog"
    content2 = path2.read_text()
    body2 = "\n".join(ln for ln in content2.splitlines() if not ln.startswith("#") and ln.strip())

    # Same structure: BLOCK, PROGRAM, AD, FENCE rows; event_id and type order match
    rows1 = _parse_tlog_body_rows(path1)
    rows2 = _parse_tlog_body_rows(path2)
    assert len(rows1) == len(rows2)
    for r1, r2 in zip(rows1, rows2):
        assert r1["type"] == r2["type"]
        assert r1["dur"] == r2["dur"]


# ---------------------------------------------------------------------------
# 4) JSONL bijection with .tlog event_ids (TL-ART-006)
# ---------------------------------------------------------------------------


def test_jsonl_bijection_with_tlog_event_ids(tmp_path: Path) -> None:
    """Every EVENT_ID in .tlog appears exactly once in .tlog.jsonl and vice versa."""
    log = _make_minimal_log(channel_id="ch-D", broadcast_date=date(2026, 2, 17))
    writer = TransmissionLogArtifactWriter(base_path=tmp_path)
    tlog_path = writer.write(
        channel_id=log.channel_id,
        broadcast_date=log.broadcast_date,
        transmission_log=log,
        timezone_display="UTC",
    )
    jsonl_path = tlog_path.with_suffix(".tlog.jsonl")

    rows = _parse_tlog_body_rows(tlog_path)
    records = _parse_jsonl(jsonl_path)
    tlog_ids = {r["event_id"] for r in rows}
    jsonl_ids = {r["event_id"] for r in records}
    assert tlog_ids == jsonl_ids
    for event_id in tlog_ids:
        trow = next(r for r in rows if r["event_id"] == event_id)
        jrow = next(r for r in records if r["event_id"] == event_id)
        assert jrow["type"] == trow["type"]
        assert "scheduled_start_utc" in jrow
        assert "scheduled_duration_ms" in jrow
        assert "block_id" in jrow


# ---------------------------------------------------------------------------
# 5) BLOCK includes UTC_START and UTC_END (TL-ART-004)
# ---------------------------------------------------------------------------


def test_block_includes_utc_start_and_utc_end(tmp_path: Path) -> None:
    """TYPE=BLOCK line MUST include UTC_START= and UTC_END= in TITLE_ASSET."""
    log = _make_minimal_log(channel_id="ch-E", broadcast_date=date(2026, 2, 18))
    writer = TransmissionLogArtifactWriter(base_path=tmp_path)
    tlog_path = writer.write(
        channel_id=log.channel_id,
        broadcast_date=log.broadcast_date,
        transmission_log=log,
        timezone_display="UTC",
    )
    rows = _parse_tlog_body_rows(tlog_path)
    block_rows = [r for r in rows if r["type"] == "BLOCK"]
    assert block_rows
    for row in block_rows:
        notes = row["title_asset"]
        assert "UTC_START=" in notes, f"BLOCK missing UTC_START: {row}"
        assert "UTC_END=" in notes, f"BLOCK missing UTC_END: {row}"
        assert re.search(r"UTC_START=\d{4}-\d{2}-\d{2}T[\d:]+Z", notes)
        assert re.search(r"UTC_END=\d{4}-\d{2}-\d{2}T[\d:]+Z", notes)


# ---------------------------------------------------------------------------
# 6) FENCE includes UTC_END only (TL-ART-004)
# ---------------------------------------------------------------------------


def test_fence_includes_utc_end_only(tmp_path: Path) -> None:
    """FENCE line MUST include UTC_END= in TITLE_ASSET (no UTC_START)."""
    log = _make_minimal_log(channel_id="ch-F", broadcast_date=date(2026, 2, 19))
    writer = TransmissionLogArtifactWriter(base_path=tmp_path)
    tlog_path = writer.write(
        channel_id=log.channel_id,
        broadcast_date=log.broadcast_date,
        transmission_log=log,
        timezone_display="UTC",
    )
    rows = _parse_tlog_body_rows(tlog_path)
    fence_rows = [r for r in rows if r["type"] == "FENCE"]
    assert fence_rows
    for row in fence_rows:
        assert "UTC_END=" in row["title_asset"], f"FENCE missing UTC_END: {row}"
        assert re.search(r"UTC_END=\d{4}-\d{2}-\d{2}T[\d:]+Z", row["title_asset"])
