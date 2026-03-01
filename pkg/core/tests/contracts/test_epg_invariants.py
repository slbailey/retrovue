"""
EPG Invariant Contract Tests

Tests the invariants defined in:
    docs/contracts/invariants/core/epg/INV-EPG-*.md

Validates that EPG events derived from ResolvedScheduleDay satisfy
temporal integrity, content integrity, and availability guarantees.

Uses the production ScheduleManager with in-memory stores.
No real-time waits, no media decoding. Deterministic clock only.
"""

import pytest
from datetime import date, datetime, time, timedelta
from dataclasses import field

from retrovue.runtime.schedule_types import (
    EPGEvent,
    Episode,
    Program,
    ProgramEvent,
    ProgramRef,
    ProgramRefType,
    ResolvedAsset,
    ResolvedScheduleDay,
    ResolvedSlot,
    ScheduleManagerConfig,
    ScheduleSlot,
    SequenceState,
)
from retrovue.runtime.schedule_manager import ScheduleManager
from retrovue.runtime.schedule_manager_service import (
    InMemoryResolvedStore,
    InMemorySequenceStore,
)


# =============================================================================
# Constants
# =============================================================================

CHANNEL_ID = "epg-test-ch1"
GRID_MINUTES = 30
GRID_SECONDS = GRID_MINUTES * 60
PROGRAMMING_DAY_START_HOUR = 6
FILLER_PATH = "/media/filler/bars.mp4"

# A representative broadcast day: 2026-03-15
BROADCAST_DATE = date(2026, 3, 15)
RESOLUTION_TIME = datetime(2026, 3, 13, 12, 0, 0)


# =============================================================================
# Test Data Builders
# =============================================================================


def _make_resolved_asset(
    title: str = "Test Show",
    episode_title: str | None = "Pilot",
    episode_id: str | None = "S01E01",
    file_path: str = "/media/shows/test.mp4",
    duration_seconds: float = 1320.0,
) -> ResolvedAsset:
    return ResolvedAsset(
        file_path=file_path,
        asset_id=f"asset-{title.lower().replace(' ', '-')}",
        title=title,
        episode_title=episode_title,
        episode_id=episode_id,
        content_duration_seconds=duration_seconds,
    )


def _make_program_event(
    idx: int,
    slot_time: time,
    asset: ResolvedAsset,
    block_span: int = 1,
    program_id: str = "prog-001",
) -> ProgramEvent:
    """Build a ProgramEvent with consistent IDs."""
    # Compute start_utc_ms from slot_time on BROADCAST_DATE
    dt = datetime.combine(BROADCAST_DATE, slot_time)
    if slot_time.hour < PROGRAMMING_DAY_START_HOUR:
        dt += timedelta(days=1)
    start_utc_ms = int(dt.timestamp() * 1000)

    return ProgramEvent(
        id=f"{CHANNEL_ID}-{BROADCAST_DATE.isoformat()}-evt{idx:04d}",
        program_id=program_id,
        episode_id=asset.episode_id or "",
        start_utc_ms=start_utc_ms,
        duration_ms=int(asset.content_duration_seconds * 1000),
        block_span_count=block_span,
        resolved_asset=asset,
    )


def _make_resolved_slot(
    slot_time: time,
    asset: ResolvedAsset,
    duration_seconds: float | None = None,
) -> ResolvedSlot:
    return ResolvedSlot(
        slot_time=slot_time,
        program_ref=ProgramRef(ProgramRefType.PROGRAM, "prog-001"),
        resolved_asset=asset,
        duration_seconds=duration_seconds or GRID_SECONDS,
    )


def _build_resolved_day(
    program_events: list[ProgramEvent],
    resolved_slots: list[ResolvedSlot],
    programming_day_date: date = BROADCAST_DATE,
) -> ResolvedScheduleDay:
    return ResolvedScheduleDay(
        programming_day_date=programming_day_date,
        resolved_slots=resolved_slots,
        resolution_timestamp=RESOLUTION_TIME,
        sequence_state=SequenceState(positions={}, as_of=RESOLUTION_TIME),
        program_events=program_events,
    )


def _make_catalog() -> "InMemoryProgramCatalog":
    return InMemoryProgramCatalog()


class InMemoryProgramCatalog:
    """Minimal ProgramCatalog for tests."""

    def __init__(self):
        self._programs: dict[str, Program] = {}

    def add(self, program: Program) -> None:
        self._programs[program.program_id] = program

    def get_program(self, program_id: str) -> Program | None:
        return self._programs.get(program_id)


def _make_schedule_manager(
    resolved_store: InMemoryResolvedStore | None = None,
) -> ScheduleManager:
    """Build a ScheduleManager with in-memory stores."""
    catalog = _make_catalog()
    seq_store = InMemorySequenceStore()
    rs = resolved_store or InMemoryResolvedStore()
    config = ScheduleManagerConfig(
        grid_minutes=GRID_MINUTES,
        program_catalog=catalog,
        sequence_store=seq_store,
        resolved_store=rs,
        filler_path=FILLER_PATH,
        filler_duration_seconds=30.0,
        programming_day_start_hour=PROGRAMMING_DAY_START_HOUR,
    )
    return ScheduleManager(config)


def _populate_four_program_day(store: InMemoryResolvedStore) -> ResolvedScheduleDay:
    """Build and store a broadcast day with 4 contiguous 30-min programs at 06:00–08:00."""
    assets = [
        _make_resolved_asset("Show A", "Ep1", "S01E01", "/media/a.mp4", 1320.0),
        _make_resolved_asset("Show B", "Ep1", "S01E01", "/media/b.mp4", 1320.0),
        _make_resolved_asset("Show C", "Ep1", "S01E01", "/media/c.mp4", 1320.0),
        _make_resolved_asset("Show D", "Ep1", "S01E01", "/media/d.mp4", 1320.0),
    ]
    times = [time(6, 0), time(6, 30), time(7, 0), time(7, 30)]

    program_events = []
    resolved_slots = []
    for i, (t, asset) in enumerate(zip(times, assets)):
        program_events.append(_make_program_event(i, t, asset, program_id=f"prog-{i}"))
        resolved_slots.append(_make_resolved_slot(t, asset))

    rd = _build_resolved_day(program_events, resolved_slots)
    store.store(CHANNEL_ID, rd)
    return rd


# =============================================================================
# INV-EPG-NO-OVERLAP-001
# =============================================================================


class TestInvEpgNoOverlap001:
    """
    Invariant: INV-EPG-NO-OVERLAP-001
    Derived from: LAW-GRID, LAW-DERIVATION
    Failure class: Planning fault
    """

    def test_single_day_no_overlap(self):
        """TEPG-NO-001: No two EPG events overlap within a single broadcast day."""
        store = InMemoryResolvedStore()
        _populate_four_program_day(store)
        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 6, 0),
            datetime(2026, 3, 15, 8, 0),
        )

        assert len(events) == 4
        sorted_events = sorted(events, key=lambda e: e.start_time)
        for i in range(len(sorted_events) - 1):
            assert sorted_events[i].end_time <= sorted_events[i + 1].start_time, (
                f"Overlap detected: event {i} ends at {sorted_events[i].end_time}, "
                f"event {i+1} starts at {sorted_events[i+1].start_time}"
            )

    def test_cross_day_boundary_no_overlap(self):
        """TEPG-NO-002: No overlap when querying across two broadcast days."""
        store = InMemoryResolvedStore()

        # Day 1: program at 07:00
        asset_d1 = _make_resolved_asset("Day1 Show", "Ep1", "S01E01", "/media/d1.mp4")
        pe_d1 = _make_program_event(0, time(7, 0), asset_d1)
        rs_d1 = _make_resolved_slot(time(7, 0), asset_d1)
        rd1 = _build_resolved_day([pe_d1], [rs_d1], BROADCAST_DATE)
        store.store(CHANNEL_ID, rd1)

        # Day 2: program at 06:00
        day2 = BROADCAST_DATE + timedelta(days=1)
        asset_d2 = _make_resolved_asset("Day2 Show", "Ep1", "S01E01", "/media/d2.mp4")
        pe_d2 = _make_program_event(0, time(6, 0), asset_d2)
        rs_d2 = _make_resolved_slot(time(6, 0), asset_d2)
        rd2 = _build_resolved_day([pe_d2], [rs_d2], day2)
        store.store(CHANNEL_ID, rd2)

        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 6, 0),
            datetime(2026, 3, 16, 7, 0),
        )

        assert len(events) >= 2
        sorted_events = sorted(events, key=lambda e: e.start_time)
        for i in range(len(sorted_events) - 1):
            assert sorted_events[i].end_time <= sorted_events[i + 1].start_time


# =============================================================================
# INV-EPG-NO-GAP-001
# =============================================================================


class TestInvEpgNoGap001:
    """
    Invariant: INV-EPG-NO-GAP-001
    Derived from: LAW-GRID, LAW-LIVENESS
    Failure class: Planning fault
    """

    def test_full_day_no_gaps(self):
        """TEPG-NG-001: Consecutive EPG events are temporally adjacent."""
        store = InMemoryResolvedStore()
        _populate_four_program_day(store)
        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 6, 0),
            datetime(2026, 3, 15, 8, 0),
        )

        assert len(events) == 4
        sorted_events = sorted(events, key=lambda e: e.start_time)
        for i in range(len(sorted_events) - 1):
            assert sorted_events[i].end_time == sorted_events[i + 1].start_time, (
                f"Gap detected: event {i} ends at {sorted_events[i].end_time}, "
                f"event {i+1} starts at {sorted_events[i+1].start_time}"
            )

    def test_partial_query_no_gaps(self):
        """TEPG-NG-002: Partial query still returns gap-free events."""
        store = InMemoryResolvedStore()
        _populate_four_program_day(store)
        sm = _make_schedule_manager(store)

        # Query only the middle two programs (06:30–07:30)
        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 6, 30),
            datetime(2026, 3, 15, 7, 30),
        )

        assert len(events) == 2
        sorted_events = sorted(events, key=lambda e: e.start_time)
        assert sorted_events[0].end_time == sorted_events[1].start_time


# =============================================================================
# INV-EPG-BROADCAST-DAY-BOUNDED-001
# =============================================================================


class TestInvEpgBroadcastDayBounded001:
    """
    Invariant: INV-EPG-BROADCAST-DAY-BOUNDED-001
    Derived from: LAW-GRID, LAW-DERIVATION
    Failure class: Planning fault
    """

    def test_events_within_broadcast_day(self):
        """TEPG-BD-001: Daytime events fall within broadcast day window."""
        store = InMemoryResolvedStore()
        _populate_four_program_day(store)
        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 6, 0),
            datetime(2026, 3, 15, 8, 0),
        )

        # Broadcast day window: 2026-03-15 06:00 to 2026-03-16 06:00
        window_start = datetime(2026, 3, 15, 6, 0)
        window_end = datetime(2026, 3, 16, 6, 0)

        for event in events:
            assert event.programming_day_date == BROADCAST_DATE
            assert event.start_time >= window_start, (
                f"Event starts before broadcast day: {event.start_time}"
            )
            assert event.end_time <= window_end, (
                f"Event ends after broadcast day: {event.end_time}"
            )

    def test_late_night_within_broadcast_day(self):
        """TEPG-BD-002: Late-night programs (after midnight) belong to prior broadcast day."""
        store = InMemoryResolvedStore()

        # Program at 01:00 (after midnight) — belongs to BROADCAST_DATE, not next day
        asset = _make_resolved_asset("Late Night", "Ep1", "S01E01", "/media/ln.mp4")
        pe = _make_program_event(0, time(1, 0), asset)
        rs = _make_resolved_slot(time(1, 0), asset)
        rd = _build_resolved_day([pe], [rs], BROADCAST_DATE)
        store.store(CHANNEL_ID, rd)

        sm = _make_schedule_manager(store)

        # Query the after-midnight window
        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 16, 0, 0),
            datetime(2026, 3, 16, 2, 0),
        )

        assert len(events) == 1
        event = events[0]
        # The event at 01:00 on 3/16 belongs to broadcast day 3/15
        assert event.programming_day_date == BROADCAST_DATE

        # Event must be within broadcast day window: 3/15 06:00 to 3/16 06:00
        window_start = datetime(2026, 3, 15, 6, 0)
        window_end = datetime(2026, 3, 16, 6, 0)
        assert event.start_time >= window_start
        assert event.end_time <= window_end


# =============================================================================
# INV-EPG-FILLER-INVISIBLE-001
# =============================================================================


class TestInvEpgFillerInvisible001:
    """
    Invariant: INV-EPG-FILLER-INVISIBLE-001
    Derived from: LAW-CONTENT-AUTHORITY, LAW-DERIVATION
    Failure class: Planning fault
    """

    def test_filler_not_in_epg(self):
        """TEPG-FI-001: No EPG event references filler content.

        ProgramEvents represent editorial content. Even when a program's
        content is shorter than its grid occupancy (requiring filler at
        playout time), the EPG event represents the editorial program,
        not the padding. Filler is a playout artifact, not an EPG entry.
        """
        store = InMemoryResolvedStore()

        # A program with content shorter than grid block — filler needed at playout
        asset = _make_resolved_asset(
            "Short Show", "Ep1", "S01E01", "/media/short.mp4", 900.0
        )
        pe = _make_program_event(0, time(8, 0), asset)
        rs = _make_resolved_slot(time(8, 0), asset)
        rd = _build_resolved_day([pe], [rs])
        store.store(CHANNEL_ID, rd)

        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 8, 0),
            datetime(2026, 3, 15, 8, 30),
        )

        assert len(events) == 1
        for event in events:
            assert event.resolved_asset.file_path != FILLER_PATH, (
                f"Filler asset appeared in EPG: {event.resolved_asset.file_path}"
            )
            assert event.title != "", "EPG event has empty title (likely filler)"


# =============================================================================
# INV-EPG-IDENTITY-STABLE-001
# =============================================================================


class TestInvEpgIdentityStable001:
    """
    Invariant: INV-EPG-IDENTITY-STABLE-001
    Derived from: LAW-IMMUTABILITY, LAW-DERIVATION
    Failure class: Planning fault
    """

    def test_identity_stable_across_queries(self):
        """TEPG-IS-001: Repeated queries return identical identity fields."""
        store = InMemoryResolvedStore()
        _populate_four_program_day(store)
        sm = _make_schedule_manager(store)

        query_start = datetime(2026, 3, 15, 6, 0)
        query_end = datetime(2026, 3, 15, 8, 0)

        events1 = sm.get_epg_events(CHANNEL_ID, query_start, query_end)
        events2 = sm.get_epg_events(CHANNEL_ID, query_start, query_end)

        assert len(events1) == len(events2)
        for e1, e2 in zip(
            sorted(events1, key=lambda e: e.start_time),
            sorted(events2, key=lambda e: e.start_time),
        ):
            assert e1.title == e2.title
            assert e1.episode_id == e2.episode_id
            assert e1.episode_title == e2.episode_title
            assert e1.start_time == e2.start_time
            assert e1.end_time == e2.end_time
            assert e1.resolved_asset.file_path == e2.resolved_asset.file_path


# =============================================================================
# INV-EPG-DERIVATION-TRACEABLE-001
# =============================================================================


class TestInvEpgDerivationTraceable001:
    """
    Invariant: INV-EPG-DERIVATION-TRACEABLE-001
    Derived from: LAW-DERIVATION
    Failure class: Planning fault
    """

    def test_every_event_traces_to_resolved_day(self):
        """TEPG-DT-001: Every EPG event's programming_day_date maps to an existing ResolvedScheduleDay."""
        store = InMemoryResolvedStore()
        rd = _populate_four_program_day(store)
        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 6, 0),
            datetime(2026, 3, 15, 8, 0),
        )

        for event in events:
            source = store.get(CHANNEL_ID, event.programming_day_date)
            assert source is not None, (
                f"EPG event programming_day_date={event.programming_day_date} "
                f"has no corresponding ResolvedScheduleDay"
            )

    def test_event_fields_match_source(self):
        """TEPG-DT-002: EPG event fields match the source ProgramEvent."""
        store = InMemoryResolvedStore()

        asset = _make_resolved_asset(
            "Cheers", "Coach Returns", "S02E05", "/media/cheers/s02e05.mp4", 1320.0
        )
        pe = _make_program_event(0, time(9, 0), asset, program_id="cheers")
        rs = _make_resolved_slot(time(9, 0), asset)
        rd = _build_resolved_day([pe], [rs])
        store.store(CHANNEL_ID, rd)

        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 9, 0),
            datetime(2026, 3, 15, 10, 0),
        )

        assert len(events) == 1
        event = events[0]

        # Fields must trace to the source ProgramEvent
        assert event.title == asset.title
        assert event.episode_id == asset.episode_id
        assert event.episode_title == asset.episode_title
        assert event.resolved_asset.file_path == asset.file_path
        assert event.programming_day_date == BROADCAST_DATE


# =============================================================================
# INV-EPG-VIEWER-INDEPENDENT-001
# =============================================================================


class TestInvEpgViewerIndependent001:
    """
    Invariant: INV-EPG-VIEWER-INDEPENDENT-001
    Derived from: LAW-DERIVATION, LAW-CONTENT-AUTHORITY
    Failure class: Runtime fault
    """

    def test_epg_available_without_viewers(self):
        """TEPG-VI-001: EPG is queryable for resolved days with no active viewers.

        No playout session is started. No viewer connections exist.
        EPG data is available purely from the resolved store.
        """
        store = InMemoryResolvedStore()

        # Resolve a future day — no viewers tuned in
        future_date = date(2026, 3, 20)
        asset = _make_resolved_asset("Future Show", "Ep1", "S01E01", "/media/f.mp4")
        pe = _make_program_event(0, time(10, 0), asset)
        rs = _make_resolved_slot(time(10, 0), asset)
        rd = _build_resolved_day([pe], [rs], future_date)
        store.store(CHANNEL_ID, rd)

        sm = _make_schedule_manager(store)

        # Query without any viewer/playout infrastructure
        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 20, 10, 0),
            datetime(2026, 3, 20, 11, 0),
        )

        assert len(events) >= 1
        assert events[0].title == "Future Show"


# =============================================================================
# INV-EPG-PROGRAM-CONTINUITY-001
# =============================================================================


class TestInvEpgProgramContinuity001:
    """
    Invariant: INV-EPG-PROGRAM-CONTINUITY-001
    Derived from: LAW-GRID, LAW-DERIVATION
    Failure class: Planning fault
    """

    def test_multiblock_program_single_entry(self):
        """TEPG-PC-001: 90-min movie spanning 3 blocks produces single EPG event."""
        store = InMemoryResolvedStore()

        # 90-min movie at 20:00 in 30-min grid → 3 blocks
        movie_asset = _make_resolved_asset(
            "Big Movie", "Feature", "mov01", "/media/movie.mp4", 5400.0
        )
        pe = _make_program_event(
            0, time(20, 0), movie_asset, block_span=3, program_id="movie-night"
        )

        # 3 resolved slots for the 3 blocks
        resolved_slots = [
            _make_resolved_slot(time(20, 0), movie_asset, GRID_SECONDS * 3),
            _make_resolved_slot(time(20, 30), movie_asset, GRID_SECONDS * 3),
            _make_resolved_slot(time(21, 0), movie_asset, GRID_SECONDS * 3),
        ]

        rd = _build_resolved_day([pe], resolved_slots)
        store.store(CHANNEL_ID, rd)

        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 20, 0),
            datetime(2026, 3, 15, 22, 0),
        )

        # Exactly one EPG event for the single ProgramEvent
        assert len(events) == 1
        event = events[0]
        assert event.title == "Big Movie"

        # Duration = 3 blocks * 30 min = 90 min = 5400 seconds
        duration = (event.end_time - event.start_time).total_seconds()
        assert duration == 5400.0

    def test_two_block_span_single_event(self):
        """TEPG-PC-002: 45-min program spanning 2 blocks produces single EPG event."""
        store = InMemoryResolvedStore()

        asset = _make_resolved_asset(
            "Drama Hour", "Ep3", "S01E03", "/media/drama.mp4", 2700.0
        )
        pe = _make_program_event(
            0, time(14, 0), asset, block_span=2, program_id="drama"
        )

        resolved_slots = [
            _make_resolved_slot(time(14, 0), asset, GRID_SECONDS * 2),
            _make_resolved_slot(time(14, 30), asset, GRID_SECONDS * 2),
        ]

        rd = _build_resolved_day([pe], resolved_slots)
        store.store(CHANNEL_ID, rd)

        sm = _make_schedule_manager(store)

        events = sm.get_epg_events(
            CHANNEL_ID,
            datetime(2026, 3, 15, 14, 0),
            datetime(2026, 3, 15, 16, 0),
        )

        assert len(events) == 1
        event = events[0]
        assert event.title == "Drama Hour"

        # Duration = 2 blocks * 30 min = 60 min = 3600 seconds
        duration = (event.end_time - event.start_time).total_seconds()
        assert duration == 3600.0


# =============================================================================
# INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001 (operational non-interference)
# =============================================================================


class TestEpgEndpointNonBlocking:
    """
    Invariant: INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001
    Derived from: LAW-RUNTIME-AUTHORITY, LAW-DERIVATION
    Failure class: Runtime fault
    Scenario: EPG HTTP handlers must not block the asyncio event loop.

    FastAPI runs `async def` handlers directly on the event loop thread.
    EPG handlers perform blocking I/O (database, file reads, schedule
    compilation). If declared `async def`, they block the event loop and
    starve concurrent MPEG-TS streaming generators, causing video pause.

    Plain `def` handlers are run in a thread pool by FastAPI, preventing
    event loop starvation.
    """

    def test_epg_handlers_not_async_program_director(self):
        """EPG handlers in ProgramDirector must be plain def, not async def."""
        import ast
        from pathlib import Path

        source_path = Path(__file__).resolve().parents[2] / "src" / "retrovue" / "runtime" / "program_director.py"
        tree = ast.parse(source_path.read_text())

        epg_handler_names = {"get_epg", "get_epg_all", "epg_guide_html"}
        async_epg_handlers = []

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in epg_handler_names:
                async_epg_handlers.append(f"{node.name} (line {node.lineno})")

        assert not async_epg_handlers, (
            f"INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001-VIOLATED: "
            f"EPG handlers declared async def will block the event loop "
            f"during streaming, causing video pause. "
            f"Change to plain def. Violations: {async_epg_handlers}"
        )

    def test_epg_handler_not_async_web_api(self):
        """EPG handler in web/api/epg.py must be plain def, not async def."""
        import ast
        from pathlib import Path

        source_path = Path(__file__).resolve().parents[2] / "src" / "retrovue" / "web" / "api" / "epg.py"
        tree = ast.parse(source_path.read_text())

        async_epg_handlers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_epg":
                async_epg_handlers.append(f"{node.name} (line {node.lineno})")

        assert not async_epg_handlers, (
            f"INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001-VIOLATED: "
            f"EPG handler declared async def will block the event loop. "
            f"Change to plain def. Violations: {async_epg_handlers}"
        )
