"""
Timeline invariant validators for EPG/XMLTV contract tests.

All functions raise AssertionError with a clear message when the
invariant is violated. Used by EPG and XMLTV contract tests.
"""

from __future__ import annotations


def _programme_intervals(programmes: list) -> list[tuple[int, int]]:
    """Extract (start_parsed, stop_parsed) from programme-like objects."""
    out: list[tuple[int, int]] = []
    for p in programmes:
        if hasattr(p, "start_parsed") and hasattr(p, "stop_parsed"):
            out.append((p.start_parsed, p.stop_parsed))
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            out.append((int(p[0]), int(p[1])))
        elif isinstance(p, dict) and "start_parsed" in p and "stop_parsed" in p:
            out.append((p["start_parsed"], p["stop_parsed"]))
        else:
            raise TypeError(f"Programme entry must have start_parsed/stop_parsed: {p!r}")
    return out


def assert_chronological_order(
    programmes: list,
    *,
    channel_id: str | None = None,
) -> None:
    """EPG/XMLTV chronological ordering invariant: programmes MUST be ordered by start time.

    Raises AssertionError with message if not in order.
    """
    intervals = _programme_intervals(programmes)
    for i in range(1, len(intervals)):
        prev_start = intervals[i - 1][0]
        curr_start = intervals[i][0]
        if curr_start < prev_start:
            ctx = f" channel={channel_id}" if channel_id else ""
            raise AssertionError(
                f"EPG/XMLTV chronological ordering invariant violated: programme at index {i}"
                f" has start {curr_start} before previous start {prev_start}{ctx}"
            )


def assert_no_overlaps(
    programmes: list,
    *,
    channel_id: str | None = None,
) -> None:
    """EPG/XMLTV overlap invariant: programme intervals MUST NOT overlap.

    Adjacent intervals may share boundaries (contiguous). Raises AssertionError if any overlap.
    """
    intervals = _programme_intervals(programmes)
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            a_start, a_stop = intervals[i]
            b_start, b_stop = intervals[j]
            # Overlap if one starts before the other ends (and they're not just touching)
            if a_start < b_stop and b_start < a_stop:
                ctx = f" channel={channel_id}" if channel_id else ""
                raise AssertionError(
                    f"EPG/XMLTV overlap invariant violated: programmes overlap "
                    f"([{a_start}, {a_stop}) vs [{b_start}, {b_stop}]){ctx}"
                )


def assert_no_gaps(
    programmes: list,
    *,
    channel_id: str | None = None,
) -> None:
    """EPG/XMLTV gap invariant: programme intervals MUST be contiguous (no gaps).

    Sorts by start time then checks each adjacent pair: next start must equal prev stop.
    Raises AssertionError if a gap is found.
    """
    intervals = _programme_intervals(programmes)
    if len(intervals) <= 1:
        return
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    for i in range(1, len(sorted_intervals)):
        prev_stop = sorted_intervals[i - 1][1]
        curr_start = sorted_intervals[i][0]
        if curr_start != prev_stop:
            ctx = f" channel={channel_id}" if channel_id else ""
            raise AssertionError(
                f"EPG/XMLTV gap invariant violated: gap between programmes "
                f"(prev stop={prev_stop}, next start={curr_start}){ctx}"
            )


def assert_continuity(
    programmes: list,
    current_time_epoch_seconds: int,
    *,
    channel_id: str | None = None,
) -> None:
    """EPG/XMLTV continuity invariant: exactly one programme MUST cover current time.

    Raises AssertionError if zero or more than one programme covers current_time_epoch_seconds.
    """
    intervals = _programme_intervals(programmes)
    covering = [
        (s, e)
        for s, e in intervals
        if s <= current_time_epoch_seconds < e
    ]
    if len(covering) == 0:
        ctx = f" channel={channel_id}" if channel_id else ""
        raise AssertionError(
            f"EPG/XMLTV continuity invariant violated: no programme covers current time "
            f"({current_time_epoch_seconds}){ctx}"
        )
    if len(covering) > 1:
        ctx = f" channel={channel_id}" if channel_id else ""
        raise AssertionError(
            f"EPG/XMLTV continuity invariant violated: multiple programmes ({len(covering)}) "
            f"cover current time ({current_time_epoch_seconds}){ctx}"
        )
