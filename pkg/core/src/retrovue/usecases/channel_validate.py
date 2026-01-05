from __future__ import annotations

import re
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import Channel

ALLOWED_GRID_SIZES: set[int] = {15, 30, 60}


@dataclass
class Finding:
    code: str
    field: str
    message: str
    id: str


def _is_kebab(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value or ""))


def _validate_row(row: Channel, slug_counts: dict[str, int]) -> tuple[list[Finding], list[Finding]]:
    violations: list[Finding] = []
    warnings: list[Finding] = []
    rid = str(row.id)

    # CHN-003: grid in allowed
    if row.grid_block_minutes not in ALLOWED_GRID_SIZES:
        violations.append(Finding("CHN-003", "grid_block_minutes", "Grid must be 15, 30, or 60", rid))

    # CHN-004: offsets array, non-empty, ints 0..59, sorted + unique
    offsets = row.block_start_offsets_minutes if isinstance(row.block_start_offsets_minutes, list) else None
    if not isinstance(offsets, list) or len(offsets) == 0:
        violations.append(Finding("CHN-004", "block_start_offsets_minutes", "Offsets must be a non-empty array", rid))
        offsets = []
    else:
        # Type & range
        bad = [o for o in offsets if not isinstance(o, int) or o < 0 or o > 59]
        if bad:
            violations.append(Finding("CHN-004", "block_start_offsets_minutes", "Offsets must be integers in 0–59", rid))
        # Sorted unique
        if offsets != sorted(offsets) or len(offsets) != len(set(offsets)):
            violations.append(Finding("CHN-004", "block_start_offsets_minutes", "Offsets must be sorted and unique", rid))

    # CHN-005: every offset divisible by grid
    if offsets:
        if any((o % max(1, row.grid_block_minutes)) != 0 for o in offsets):
            violations.append(Finding("CHN-005", "block_start_offsets_minutes", "Every offset must be divisible by grid size", rid))

    # CHN-006: anchor seconds==00 and minute in offsets
    try:
        sec_ok = getattr(row.programming_day_start, "second", 0) == 0
        minute_ok = getattr(row.programming_day_start, "minute", 0) in (offsets or [])
        if not (sec_ok and minute_ok):
            violations.append(Finding("CHN-006", "programming_day_start", "Minute must be in allowed offsets and seconds must be 00", rid))
    except Exception:
        violations.append(Finding("CHN-006", "programming_day_start", "Invalid time value", rid))

    # CHN-001: slug/title shape and uniqueness (case-insensitive)
    if not _is_kebab(row.slug or ""):
        violations.append(Finding("CHN-001", "slug", "Slug must be lowercase kebab", rid))
    if not row.title:
        violations.append(Finding("CHN-001", "title", "Title must be non-empty", rid))
    if slug_counts.get((row.slug or "").lower(), 0) > 1:
        violations.append(Finding("CHN-001", "slug", "Slug must be unique (case-insensitive)", rid))

    # CHN-014: warn when grid=60 and offsets include non-zero
    if row.grid_block_minutes == 60 and any(o != 0 for o in (offsets or [])):
        warnings.append(Finding("CHN-014", "block_start_offsets_minutes", "Grid 60 with non-zero offsets is unusual", rid))

    # CHN-015: warn on singleton non-zero offset
    if offsets and len(offsets) == 1 and offsets[0] != 0:
        warnings.append(Finding("CHN-015", "block_start_offsets_minutes", "Singleton non-zero offset is unusual", rid))

    return violations, warnings


def validate(db: Session, *, identifier: str | None = None, strict: bool = False) -> dict[str, Any]:
    # Fetch channels (single or all)
    if identifier:
        ch: Channel | None = None
        try:
            _ = _uuid.UUID(identifier)
            ch = db.query(Channel).filter(Channel.id == identifier).first()
        except Exception:
            ch = (
                db.query(Channel)
                .filter(func.lower(Channel.slug) == identifier.lower())
                .first()
            )
        if ch is None:
            return {"status": "error", "violations": [], "warnings": [], "error": f"Channel '{identifier}' not found"}
        rows: list[Channel] = [ch]
    else:
        rows = db.query(Channel).all()

    # Precompute slug counts for uniqueness checks
    slug_counts: dict[str, int] = {}
    for r in rows if identifier else db.query(Channel).all():
        key = (r.slug or "").lower()
        slug_counts[key] = slug_counts.get(key, 0) + 1

    all_violations: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    channels_summary: list[dict[str, Any]] = []

    for r in rows:
        v, w = _validate_row(r, slug_counts)
        channels_summary.append({"id": str(r.id), "status": "ok" if not v and not (strict and w) else "error"})
        for f in v:
            all_violations.append({"code": f.code, "field": f.field, "message": f.message, "id": f.id})
        for f in w:
            all_warnings.append({"code": f.code, "field": f.field, "message": f.message, "id": f.id})

    status = "ok"
    if all_violations or (strict and all_warnings):
        status = "error"

    result: dict[str, Any] = {
        "status": status,
        "violations": all_violations,
        "warnings": all_warnings,
        "totals": {"violations": len(all_violations), "warnings": len(all_warnings)},
    }
    if not identifier:
        result["channels"] = channels_summary

    return result


