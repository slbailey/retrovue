"""
Transmission log artifact writer.

Pure artifact generation: writes .tlog (fixed-width) and .tlog.jsonl (sidecar)
only after transmission log lock. Side-effect free beyond writing files.
Immutable once written (TL-ART-001). Deterministic. Independent of execution.

See: docs/contracts/core/TransmissionLogArtifactContract_v0.1.md
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retrovue.runtime.planning_pipeline import TransmissionLog


# Column widths from contract: TIME 8, DUR 8, TYPE 8, EVENT_ID 32, TITLE_ASSET remainder
W_TIME, W_DUR, W_TYPE, W_EVENT_ID = 8, 8, 8, 32
TLOG_TITLE_HEADER = "TITLE / ASSET"
TLOG_UNDERLINE = (
    "-------- -------- -------- ------------------------------------ "
    "--------------------------------------------"
)


class TransmissionLogArtifactExistsError(Exception):
    """Raised when .tlog already exists (TL-ART-001: no overwrite)."""


def _ms_to_hhmmss(ms: int) -> str:
    """Format duration in ms as HH:MM:SS."""
    if ms < 0:
        ms = 0
    s = ms // 1000
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _ms_to_iso8601_utc(ms: int) -> str:
    """Convert epoch ms to ISO8601 UTC string."""
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _segment_type_to_tlog_type(segment_type: str) -> str:
    """Map pipeline segment_type to contract TYPE (BLOCK/PROGRAM/AD/PROMO/FENCE)."""
    return {
        "episode": "PROGRAM",
        "ad": "AD",
        "promo": "PROMO",
        "filler": "PROMO",
        "pad": "PROGRAM",
    }.get(segment_type, "PROGRAM")


@dataclass
class _ArtifactRow:
    """One logical row for .tlog and .tlog.jsonl."""
    time_str: str
    dur_str: str
    type_str: str
    event_id: str
    title_asset: str
    block_id: str
    scheduled_start_utc: str
    scheduled_duration_ms: int
    asset_uri: str | None


def _build_rows(
    log: "TransmissionLog",
    timezone_display: str,
    generated_utc: datetime,
) -> list[_ArtifactRow]:
    """Build ordered artifact rows from TransmissionLog. Deterministic execution order."""
    tz = ZoneInfo(timezone_display) if timezone_display else timezone.utc
    rows: list[_ArtifactRow] = []

    for entry in log.entries:
        entry_start_ms = entry.start_utc_ms
        entry_end_ms = entry.end_utc_ms
        block_dur_ms = entry_end_ms - entry_start_ms

        # BLOCK line
        block_start_dt = datetime.fromtimestamp(entry_start_ms / 1000.0, tz=timezone.utc)
        block_end_dt = datetime.fromtimestamp(entry_end_ms / 1000.0, tz=timezone.utc)
        local_start = block_start_dt.astimezone(tz)
        time_str = local_start.strftime("%H:%M:%S")
        title_block = (
            f"{entry.block_id} UTC_START={_ms_to_iso8601_utc(entry_start_ms)} "
            f"UTC_END={_ms_to_iso8601_utc(entry_end_ms)}"
        )
        rows.append(
            _ArtifactRow(
                time_str=time_str,
                dur_str=_ms_to_hhmmss(block_dur_ms),
                type_str="BLOCK",
                event_id=entry.block_id,
                title_asset=title_block,
                block_id=entry.block_id,
                scheduled_start_utc=_ms_to_iso8601_utc(entry_start_ms),
                scheduled_duration_ms=block_dur_ms,
                asset_uri=None,
            )
        )

        # Segment lines (execution order). EVENT_ID stable per (block_id, segment_index).
        seg_start_ms = entry_start_ms
        for seg_index, seg in enumerate(entry.segments):
            dur_ms = seg.get("segment_duration_ms", 0)
            seg_type = seg.get("segment_type", "episode")
            tlog_type = _segment_type_to_tlog_type(seg_type)
            asset_uri = seg.get("asset_uri")
            event_id = f"{entry.block_id}-S{seg_index:04d}"

            local_dt = datetime.fromtimestamp(seg_start_ms / 1000.0, tz=timezone.utc).astimezone(tz)
            time_str = local_dt.strftime("%H:%M:%S")
            # TITLE/ASSET: filename only, not full path; hard truncate at 80 (no ellipsis)
            if asset_uri:
                title_asset = Path(asset_uri).name.strip() or "-"
            else:
                title_asset = seg_type.strip() or "-"
            if len(title_asset) > 80:
                title_asset = title_asset[:80]

            rows.append(
                _ArtifactRow(
                    time_str=time_str,
                    dur_str=_ms_to_hhmmss(dur_ms),
                    type_str=tlog_type,
                    event_id=event_id,
                    title_asset=title_asset,
                    block_id=entry.block_id,
                    scheduled_start_utc=_ms_to_iso8601_utc(seg_start_ms),
                    scheduled_duration_ms=dur_ms,
                    asset_uri=asset_uri if asset_uri else None,
                )
            )
            seg_start_ms += dur_ms

        # FENCE line
        fence_dt = datetime.fromtimestamp(entry_end_ms / 1000.0, tz=timezone.utc).astimezone(tz)
        rows.append(
            _ArtifactRow(
                time_str=fence_dt.strftime("%H:%M:%S"),
                dur_str="00:00:00",
                type_str="FENCE",
                event_id=f"{entry.block_id}-FENCE",
                title_asset=f"UTC_END={_ms_to_iso8601_utc(entry_end_ms)}",
                block_id=entry.block_id,
                scheduled_start_utc=_ms_to_iso8601_utc(entry_end_ms),
                scheduled_duration_ms=0,
                asset_uri=None,
            )
        )

    return rows


class TransmissionLogArtifactWriter:
    """
    Writes transmission log artifacts (.tlog + .tlog.jsonl) after lock.
    Pure artifact generation; side-effect free beyond writing files.
    """

    def __init__(self, base_path: Path = Path("/opt/retrovue/data/logs/transmission")) -> None:
        self._base_path = base_path

    def write(
        self,
        channel_id: str,
        broadcast_date: date,
        transmission_log: TransmissionLog,
        timezone_display: str,
        *,
        generated_utc: datetime | None = None,
        transmission_log_id: str | None = None,
    ) -> Path:
        """
        Writes:
            .tlog (fixed-width)
            .tlog.jsonl (machine sidecar)

        Returns:
            Path to .tlog file

        Raises:
            TransmissionLogArtifactExistsError: if .tlog already exists (TL-ART-001).
        """
        channel_dir = self._base_path / channel_id
        date_str = broadcast_date.isoformat()
        tlog_path = channel_dir / f"{date_str}.tlog"
        jsonl_path = channel_dir / f"{date_str}.tlog.jsonl"

        if tlog_path.exists():
            raise TransmissionLogArtifactExistsError(
                f"Transmission log artifact already exists: {tlog_path} (TL-ART-001)"
            )

        channel_dir.mkdir(parents=True, exist_ok=True)

        now = generated_utc or datetime.now(timezone.utc)
        tl_id = transmission_log_id or transmission_log.metadata.get("transmission_log_id") or str(
            uuid.uuid4()
        )
        generated_utc_str = now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        rows = _build_rows(transmission_log, timezone_display, now)

        # Write .tlog to temp then rename (atomic write pattern)
        tlog_tmp = tlog_path.with_suffix(".tlog.tmp")
        try:
            day_start_hour = transmission_log.metadata.get("programming_day_start_hour")
            with open(tlog_tmp, "w") as f:
                f.write("# RETROVUE TRANSMISSION LOG\n")
                f.write(f"# CHANNEL: {channel_id}\n")
                f.write(f"# DATE: {date_str}\n")
                if day_start_hour is not None:
                    h = int(day_start_hour)
                    f.write(f"# BROADCAST_DAY_START: {h:02d}:00:00\n")
                    f.write(f"# BROADCAST_DAY_END: {h:02d}:00:00\n")
                f.write(f"# TIMEZONE_DISPLAY: {timezone_display}\n")
                f.write(f"# GENERATED_UTC: {generated_utc_str}\n")
                f.write(f"# TRANSMISSION_LOG_ID: {tl_id}\n")
                f.write("# VERSION: 1\n")
                f.write("\n")
                f.write(
                    f"{'TIME':<{W_TIME}} {'DUR':<{W_DUR}} {'TYPE':<{W_TYPE}} "
                    f"{'EVENT_ID':<{W_EVENT_ID}} {TLOG_TITLE_HEADER}\n"
                )
                f.write(TLOG_UNDERLINE + "\n")
                for r in rows:
                    event_id_col = (r.event_id[:W_EVENT_ID] if len(r.event_id) > W_EVENT_ID else r.event_id)
                    line = (
                        f"{r.time_str:<{W_TIME}} {r.dur_str:<{W_DUR}} {r.type_str:<{W_TYPE}} "
                        f"{event_id_col:<{W_EVENT_ID}} {r.title_asset}\n"
                    )
                    f.write(line)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tlog_tmp, tlog_path)
        except Exception:
            if tlog_tmp.exists():
                tlog_tmp.unlink(missing_ok=True)
            raise

        # Write .tlog.jsonl to temp then rename (atomic write pattern)
        jsonl_tmp = jsonl_path.with_suffix(".tlog.jsonl.tmp")
        try:
            with open(jsonl_tmp, "w") as f:
                for r in rows:
                    obj = {
                        "event_id": r.event_id,
                        "block_id": r.block_id,
                        "scheduled_start_utc": r.scheduled_start_utc,
                        "scheduled_duration_ms": r.scheduled_duration_ms,
                        "type": r.type_str,
                        "asset_uri": r.asset_uri,
                    }
                    f.write(json.dumps(obj) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.rename(jsonl_tmp, jsonl_path)
        except Exception:
            if jsonl_tmp.exists():
                jsonl_tmp.unlink(missing_ok=True)
            raise

        return tlog_path
