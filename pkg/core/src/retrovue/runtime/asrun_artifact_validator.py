"""As-Run Artifact Validator — AsRunLogArtifactContract v0.2

Validates .asrun text content and parsed rows against v0.2 invariants.
Pure artifact validation. No AIR dependencies. No side effects.

See: docs/contracts/artifacts/AsRunLogArtifactContract.md
"""

from __future__ import annotations

import re
from collections import defaultdict


class AsRunArtifactError(Exception):
    """Raised when as-run artifact violates contract invariants."""

    pass


TERMINAL_STATUSES = frozenset(
    {"AIRED", "TRUNCATED", "SHORT", "SKIPPED", "SUBSTITUTED", "ERROR"}
)

SCHEDULED_FIELDS_FORBIDDEN_IN_TEXT = [
    "scheduled_duration_ms",
    "scheduled_start_utc",
    "planned_duration_ms",
    "planned_start_utc",
]


def validate_single_terminal_event(rows: list[dict]) -> None:
    """AR-ART-008: Each non-BLOCK EVENT_ID must have exactly one terminal status."""
    events_by_id: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        if row["type"] == "BLOCK":
            continue
        events_by_id[row["event_id"]].append(row)

    for event_id, event_rows in events_by_id.items():
        terminal_rows = [r for r in event_rows if r["status"] in TERMINAL_STATUSES]
        seg_starts = [r for r in event_rows if r["status"] == "SEG_START"]

        if len(terminal_rows) > 1:
            raise AsRunArtifactError(
                f"AR-ART-008 violated: EVENT_ID {event_id} has "
                f"{len(terminal_rows)} terminal events (must be exactly 1)"
            )

        if seg_starts and not terminal_rows:
            raise AsRunArtifactError(
                f"AR-ART-008 violated: EVENT_ID {event_id} has SEG_START "
                f"but no terminal status"
            )


def validate_no_zero_frame_terminal(rows: list[dict]) -> None:
    """AR-ART-008: AIRED and TRUNCATED must have frames > 0."""
    for row in rows:
        if row["type"] == "BLOCK":
            continue
        if row["status"] not in ("AIRED", "TRUNCATED"):
            continue
        notes = row.get("notes", "")
        frames_match = re.search(r"frames=(\d+)", notes)
        if frames_match:
            frames = int(frames_match.group(1))
            if frames == 0:
                raise AsRunArtifactError(
                    f"AR-ART-008 violated: EVENT_ID {row['event_id']} has "
                    f"{row['status']} with frames=0 (zero-frame terminal forbidden)"
                )


def validate_seg_start_requires_terminal(rows: list[dict]) -> None:
    """SEG_START must precede exactly one terminal status for the same EVENT_ID."""
    events_by_id: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        if row["type"] == "BLOCK":
            continue
        events_by_id[row["event_id"]].append(row)

    for event_id, event_rows in events_by_id.items():
        seg_starts = [r for r in event_rows if r["status"] == "SEG_START"]
        terminal_rows = [r for r in event_rows if r["status"] in TERMINAL_STATUSES]

        if seg_starts and not terminal_rows:
            raise AsRunArtifactError(
                f"SEG_START without terminal: EVENT_ID {event_id} has "
                f"{len(seg_starts)} SEG_START(s) but no terminal status"
            )


def validate_fence_absolute_ticks(rows: list[dict]) -> None:
    """AR-ART-003 v0.2: Fence swap_tick and fence_tick, when present, must be > 0
    and equal.  Both may be omitted (zero ticks are not written).

    frame_budget_remaining must be 0.
    """
    for row in rows:
        if row["status"] != "FENCE" or row["type"] != "BLOCK":
            continue
        notes = row.get("notes", "")

        swap_match = re.search(r"swap_tick=(\d+)", notes)
        fence_match = re.search(r"fence_tick=(\d+)", notes)

        # Both absent is valid (zero ticks are omitted by the writer).
        # If one is present the other must be too.
        if bool(swap_match) != bool(fence_match):
            present = "swap_tick" if swap_match else "fence_tick"
            missing = "fence_tick" if swap_match else "swap_tick"
            raise AsRunArtifactError(
                f"AR-ART-003 violated: FENCE {row['event_id']}: "
                f"{present} present but {missing} missing"
            )

        if swap_match and fence_match:
            swap = int(swap_match.group(1))
            fence = int(fence_match.group(1))

            if swap <= 0:
                raise AsRunArtifactError(
                    f"AR-ART-003 violated: FENCE {row['event_id']}: "
                    f"swap_tick ({swap}) must be > 0"
                )
            if fence <= 0:
                raise AsRunArtifactError(
                    f"AR-ART-003 violated: FENCE {row['event_id']}: "
                    f"fence_tick ({fence}) must be > 0"
                )
            if swap != fence:
                raise AsRunArtifactError(
                    f"AR-ART-003 violated: FENCE {row['event_id']}: "
                    f"swap_tick ({swap}) != fence_tick ({fence})"
                )

        budget_match = re.search(r"frame_budget_remaining=(\d+)", notes)
        if not budget_match:
            raise AsRunArtifactError(
                f"AR-ART-003 violated: FENCE {row['event_id']} "
                f"missing frame_budget_remaining"
            )
        budget = int(budget_match.group(1))
        if budget != 0:
            raise AsRunArtifactError(
                f"AR-ART-003 violated: FENCE {row['event_id']}: "
                f"frame_budget_remaining ({budget}) must be 0"
            )


def validate_no_scheduled_fields_in_text(asrun_text: str) -> None:
    """AR-ART-004 v0.2: Scheduled/planned metadata must not appear in .asrun text."""
    for field in SCHEDULED_FIELDS_FORBIDDEN_IN_TEXT:
        if field in asrun_text:
            raise AsRunArtifactError(
                f"AR-ART-004 violated: forbidden planned/scheduled field "
                f"'{field}' found in .asrun text file"
            )


def validate_aired_includes_segment_index(rows: list[dict]) -> None:
    """Every AIRED row must include segment_index=<int> in its notes."""
    for row in rows:
        if row["status"] != "AIRED":
            continue
        notes = row.get("notes", "")
        if not re.search(r"segment_index=-?\d+", notes):
            raise AsRunArtifactError(
                f"AIRED missing segment_index: EVENT_ID {row.get('event_id', '?')}"
            )


def validate_fence_no_zero_ticks(rows: list[dict]) -> None:
    """FENCE must not contain swap_tick=0 or fence_tick=0."""
    for row in rows:
        if row["status"] != "FENCE" or row["type"] != "BLOCK":
            continue
        notes = row.get("notes", "")
        if re.search(r"swap_tick=0\b", notes):
            raise AsRunArtifactError(
                f"FENCE contains swap_tick=0: {row.get('event_id', '?')}"
            )
        if re.search(r"fence_tick=0\b", notes):
            raise AsRunArtifactError(
                f"FENCE contains fence_tick=0: {row.get('event_id', '?')}"
            )


def validate_broadcast_day_time_format(rows: list[dict]) -> None:
    """Broadcast-day time validation: ACTUAL > 23:59:59 is allowed.

    Hours may exceed 23 for broadcast-day rollover (e.g., 24:30:00).
    Minutes and seconds must be 0-59.
    """
    time_pattern = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")

    for row in rows:
        actual = row.get("actual", "")
        if not actual:
            continue
        m = time_pattern.match(actual)
        if not m:
            raise AsRunArtifactError(
                f"Invalid ACTUAL time format: {actual!r} "
                f"for EVENT_ID {row.get('event_id', '?')}"
            )
        minutes = int(m.group(2))
        seconds = int(m.group(3))
        if minutes > 59 or seconds > 59:
            raise AsRunArtifactError(
                f"Invalid ACTUAL time: minutes/seconds out of range: {actual!r}"
            )
