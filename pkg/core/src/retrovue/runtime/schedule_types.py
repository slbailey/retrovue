"""
Schedule Manager Contract Types

Canonical data structures for Schedule Manager as defined in:
    docs/contracts/runtime/ScheduleManagerContract.md

These types are the authoritative definitions. Tests and implementations
MUST import from this module, not redefine locally.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from fractions import Fraction
from typing import Literal, Protocol


@dataclass
class PlayoutSegment:
    """
    A single file to play with frame-accurate boundaries.

    A PlayoutSegment represents a **frame-bounded** playback instruction.
    Schedule remains time-based (CT/UTC), but execution is frame-indexed.
    This enables frame-accurate editorial cuts and deterministic padding.

    INV-FRAME-001: Segment boundaries are frame-indexed, not time-derived.
    INV-FRAME-002: Padding is expressed in frames, not duration.

    MIGRATION NOTE: The frame-indexed fields (start_frame, frame_count, fps) have
    defaults for backward compatibility. New code SHOULD use from_time_based()
    which properly computes these values. The defaults (-1, -1, Fraction(30,1))
    indicate "legacy mode" where Air derives frames from time internally.
    """
    # Schedule context (time-based, for Core planning)
    start_utc: datetime       # When this segment starts (wall clock)
    end_utc: datetime         # When this segment ends (wall clock)

    # Execution specification (frame-based, for Air execution)
    file_path: str | None     # Path to the media file (None for padding segments)

    # Segment type and padding control
    segment_type: Literal["content", "filler", "padding"] = "content"
    allows_padding: bool = False  # Whether padding may follow this segment

    # Legacy compatibility
    seek_offset_seconds: float = 0.0  # Deprecated: use start_frame instead

    # Frame-indexed execution (INV-FRAME-001)
    # Defaults provided for backward compatibility - new code uses from_time_based()
    start_frame: int = 0              # First frame index within asset
    frame_count: int = -1             # Exact frames to play (-1 = derive from time)
    fps: Fraction = Fraction(30, 1)   # Frame rate (default 30fps)

    @property
    def duration_seconds(self) -> float:
        """Duration derived from frame_count (not authoritative for execution)."""
        if self.fps.numerator == 0:
            return 0.0
        return float(self.frame_count * self.fps.denominator / self.fps.numerator)

    @classmethod
    def from_time_based(
        cls,
        start_utc: datetime,
        end_utc: datetime,
        file_path: str,
        fps: Fraction,
        seek_offset_seconds: float = 0.0,
        segment_type: Literal["content", "filler", "padding"] = "content",
        allows_padding: bool = False,
    ) -> "PlayoutSegment":
        """
        Create a PlayoutSegment from time-based boundaries.

        Converts time to frame count at construction time (Core).
        Air receives frame_count and never converts from time.
        """
        duration = (end_utc - start_utc).total_seconds()
        frame_count = int(duration * fps)
        start_frame = int(seek_offset_seconds * fps)
        return cls(
            start_utc=start_utc,
            end_utc=end_utc,
            file_path=file_path,
            start_frame=start_frame,
            frame_count=frame_count,
            fps=fps,
            segment_type=segment_type,
            allows_padding=allows_padding,
            seek_offset_seconds=seek_offset_seconds,
        )


@dataclass
class ProgramBlock:
    """
    A complete program unit bounded by grid boundaries, with frame-accurate execution.

    NOTE: ProgramBlock is a Phase 0 abstraction representing one grid slot's
    worth of playout. In later phases, this type may be replaced or wrapped
    by continuous playlog segments that are not grid-bounded. Do not build
    dependencies on grid-bounded semantics beyond Phase 0.

    INV-FRAME-002: padding_frames is computed by Core as grid_frames - content_frames.
    Air executes exactly this many black frames.
    """
    # Schedule boundaries (time-based)
    block_start: datetime     # Grid boundary start (e.g., 9:00:00)
    block_end: datetime       # Grid boundary end (e.g., 9:30:00)

    # Execution specification (frame-based)
    segments: list[PlayoutSegment]  # Ordered list of segments
    fps: Fraction = Fraction(30, 1)  # Channel frame rate (default 30fps)
    padding_frames: int = 0   # Black frames at block end for grid alignment

    @property
    def duration_seconds(self) -> float:
        """Duration of this block in seconds."""
        return (self.block_end - self.block_start).total_seconds()

    @property
    def total_frames(self) -> int:
        """Total frames including content and padding."""
        return sum(s.frame_count for s in self.segments) + self.padding_frames

    @property
    def content_frames(self) -> int:
        """Total content frames (excluding padding)."""
        return sum(s.frame_count for s in self.segments)

    @property
    def grid_frames(self) -> int:
        """Expected frames for this grid slot (computed from time, for validation only)."""
        return int(self.duration_seconds * self.fps)


@dataclass
class SimpleGridConfig:
    """
    Phase 0 configuration: single main show + filler.

    This is a simplified configuration for proving the core scheduling loop.
    Later phases will use richer configuration from SchedulePlan/ScheduleDay.

    INV-FRAME-001: fps is required for frame-indexed segment generation.
    """
    grid_minutes: int              # Grid slot duration (e.g., 30)
    main_show_path: str            # Path to main show file
    main_show_duration_seconds: float  # Duration of main show
    filler_path: str               # Path to filler file
    filler_duration_seconds: float # Duration of filler (must be >= grid - main)
    programming_day_start_hour: int = 6  # Broadcast day start (default 6 AM)
    fps: Fraction = Fraction(30, 1)  # Channel frame rate (default 30fps)


class ScheduleQueryService(Protocol):
    """
    Protocol for schedule manager implementations.

    ScheduleQueryService provides playout instructions to ChannelManager.
    It answers: "What should be playing right now, and what comes next?"

    All time parameters MUST come from MasterClock. Implementations
    MUST NOT access system clock directly.
    """

    def get_program_at(self, channel_id: str, at_time: datetime) -> ProgramBlock:
        """
        Get the program block containing the specified time.

        Args:
            channel_id: The channel identifier
            at_time: The MasterClock-provided UTC time to query

        Returns:
            ProgramBlock where: block_start <= at_time < block_end

        Raises:
            ScheduleError: If no schedule is configured for the channel
        """
        ...

    def get_next_program(self, channel_id: str, after_time: datetime) -> ProgramBlock:
        """
        Get the next program block after the specified time.

        Boundary behavior:
            - after_time is treated as EXCLUSIVE
            - If after_time falls exactly on a grid boundary, that boundary's
              block is returned (the boundary belongs to the NEW block)
            - If after_time is mid-block, the next grid boundary's block is returned

        Args:
            channel_id: The channel identifier
            after_time: The MasterClock-provided UTC time

        Returns:
            The next ProgramBlock where: block_start >= after_time
            AND block_start is the nearest grid boundary >= after_time

        Raises:
            ScheduleError: If no schedule is configured for the channel
        """
        ...


class ScheduleError(Exception):
    """Raised when schedule operations fail."""
    pass


# =============================================================================
# Phase 1 Types: Multiple Programs
# =============================================================================

@dataclass
class ScheduledProgram:
    """
    A program assigned to a specific grid slot.

    Phase 1 data structure representing a single program scheduled
    at a particular time of day.
    """
    slot_time: time           # Grid-aligned time when this program starts
    file_path: str            # Path to the program file
    duration_seconds: float   # Duration of the program content
    label: str = ""           # Optional label for debugging/logging


@dataclass
class DailyScheduleConfig:
    """
    Configuration for a daily repeating schedule with multiple programs.

    Phase 1 configuration that replaces SimpleGridConfig when multiple
    programs are needed throughout the broadcast day.

    Note: DailyScheduleConfig is the concrete runtime config implementing
    the DailySchedule contract from ScheduleManagerContract.md.
    """
    grid_minutes: int                      # Grid slot duration (e.g., 30)
    programs: list[ScheduledProgram]       # Programs throughout the day
    filler_path: str                       # Path to filler content
    filler_duration_seconds: float         # Duration of filler file
    programming_day_start_hour: int = 6    # Broadcast day start


# =============================================================================
# Phase 3 Types: Dynamic Content Selection
# =============================================================================

class ProgramRefType(Enum):
    """
    Type of content reference in a ScheduleSlot.

    Phase 3 introduces dynamic content selection where scheduled slots
    can reference Programs (requiring episode selection), direct Assets,
    or literal file paths (Phase 2 compatibility).
    """
    PROGRAM = "program"   # Requires episode selection via play_mode
    ASSET = "asset"       # Direct asset reference (no selection logic)
    FILE = "file"         # Literal file path (Phase 2 backward compatibility)


@dataclass
class ProgramRef:
    """
    Reference to schedulable content.

    Can reference:
    - A Program (series/collection requiring episode selection)
    - A direct Asset (specific movie or special)
    - A literal file path (backward compatibility with Phase 2)
    """
    ref_type: ProgramRefType
    ref_id: str  # Program ID, Asset ID, or file path


@dataclass
class ScheduleSlot:
    """
    A scheduled program slot within a ScheduleDay.

    Phase 3 data structure that replaces ScheduleEntry. References a Program
    or Asset which is resolved to a specific episode/asset during EPG generation.

    Note: ScheduleSlot replaces ScheduleEntry for Phase 3. ScheduleEntry
    remains for Phase 2 compatibility.
    """
    slot_time: time              # Grid-aligned time when this slot starts
    program_ref: ProgramRef      # Reference to Program, Asset, or direct file
    duration_seconds: float      # Duration of the slot
    label: str = ""              # Optional label for debugging/logging


@dataclass
class Episode:
    """
    An episode within a Program's episode list.

    Represents a single playable content item with metadata for
    EPG display and playout.
    """
    episode_id: str              # Unique identifier for this episode
    title: str                   # Episode title for EPG display
    file_path: str               # Path to the media file
    duration_seconds: float      # Actual content duration


@dataclass
class Program:
    """
    A program with episode selection logic.

    Phase 3 entity representing a series or collection that requires
    episode selection based on play_mode.
    """
    program_id: str              # Unique identifier
    name: str                    # Program name for EPG display
    play_mode: str               # "sequential", "random", or "manual"
    episodes: list[Episode]      # Ordered list of episodes


@dataclass(frozen=True)
class ResolvedAsset:
    """
    A fully resolved asset ready for playout.

    Contains both the physical file path for playout and display metadata
    for EPG presentation. Created during EPG generation; immutable once created.

    INV-SCHEDULEDAY-IMMUTABLE-001: frozen=True prevents field reassignment.
    """
    file_path: str                          # Physical file path for playout
    asset_id: str | None = None             # Asset ID if from catalog
    title: str = ""                         # Display title (e.g., "Cheers")
    episode_title: str | None = None        # Episode title (e.g., "Simon Says")
    episode_id: str | None = None           # Episode identifier (e.g., "S02E05")
    content_duration_seconds: float = 0.0   # Actual duration of content


@dataclass(frozen=True)
class ResolvedSlot:
    """
    A ScheduleSlot with its content fully resolved.

    Created during EPG generation. The resolved_asset is immutable
    once the EPG is published.

    INV-SCHEDULEDAY-IMMUTABLE-001: frozen=True prevents field reassignment.
    """
    slot_time: time              # Grid-aligned time
    program_ref: ProgramRef      # Original reference (for display)
    resolved_asset: ResolvedAsset  # The specific asset that will air
    duration_seconds: float      # Duration of the slot
    label: str = ""              # Display label


@dataclass(frozen=True)
class SequenceState:
    """
    Snapshot of sequential program positions at resolution time.

    Captures which episode each sequential program was at when
    a ScheduleDay was resolved. Used for deterministic replay
    and debugging.

    INV-P3-004: State advances only at resolution time, never during playout.
    INV-SCHEDULEDAY-IMMUTABLE-001: frozen=True prevents field reassignment.
    """
    positions: dict[str, int] = field(default_factory=dict)  # program_id -> episode_index
    as_of: datetime | None = None  # When this state was captured


@dataclass(frozen=True)
class ProgramEvent:
    """A single scheduled airing — the canonical editorial unit.

    Per docs/domains/ProgramEventSchedulingModel_v0.1.md:
    - duration_ms is intrinsic program runtime, not grid occupancy
    - Grid occupancy = block_span_count * grid_block_ms
    - start_utc_ms MUST align to grid block boundaries
    - Episode cursor advances once per ProgramEvent, not per block

    INV-SCHEDULEDAY-IMMUTABLE-001: frozen=True prevents field reassignment.
    """
    id: str
    program_id: str
    episode_id: str
    start_utc_ms: int
    duration_ms: int
    block_span_count: int
    metadata: dict = field(default_factory=dict)
    resolved_asset: ResolvedAsset | None = None


@dataclass(frozen=True)
class ResolvedScheduleDay:
    """
    A ScheduleDay with all content resolved to specific assets.

    Created during EPG generation. Once created, the resolved slots
    are immutable—the same episodes will air regardless of when
    playout is requested.

    INV-P3-002: EPG Identity Immutability - once published, identities cannot change.
    INV-P3-008: Resolution Idempotence - same (channel, day) resolved at most once.
    INV-SCHEDULEDAY-IMMUTABLE-001: frozen=True prevents field reassignment.
    """
    programming_day_date: date
    resolved_slots: list[ResolvedSlot]  # Per-block asset details (from segmentation)
    resolution_timestamp: datetime      # When this day was resolved
    sequence_state: SequenceState       # State snapshot at resolution time
    program_events: list[ProgramEvent] = field(default_factory=list)
    plan_id: str | None = None          # SchedulePlan ID that generated this day
    is_manual_override: bool = False    # True if created by operator override
    supersedes_id: int | None = None    # id() of superseded record, if override


@dataclass
class EPGEvent:
    """
    An event in the Electronic Program Guide.

    Represents a resolved, immutable entry in the EPG that viewers
    can browse. Once published, the identity cannot change.

    INV-P3-003: Resolution Independence - EPG exists even with no viewers.
    """
    channel_id: str
    start_time: datetime         # Absolute start time (UTC)
    end_time: datetime           # Absolute end time (UTC)
    title: str                   # Program title
    episode_title: str | None    # Episode title (if applicable)
    episode_id: str | None       # Episode identifier (if applicable)
    resolved_asset: ResolvedAsset  # The resolved asset
    programming_day_date: date     # Which programming day this belongs to


class ProgramCatalog(Protocol):
    """
    Abstraction that provides Program definitions.

    Implementations may read from a database or in-memory cache.
    """

    def get_program(self, program_id: str) -> Program | None:
        """Get a Program by ID, or None if not found."""
        ...


class SequenceStateStore(Protocol):
    """
    Abstraction for persisting sequential program state.

    INV-P3-004: State advances only at EPG resolution time.
    """

    def get_position(self, channel_id: str, program_id: str) -> int:
        """Get current episode index for a sequential program."""
        ...

    def set_position(self, channel_id: str, program_id: str, index: int) -> None:
        """Set episode index for a sequential program."""
        ...


class ResolvedScheduleStore(Protocol):
    """
    Abstraction for storing resolved schedule days.

    INV-P3-008: Resolution Idempotence - if a day is already resolved,
    return the existing resolution, do not re-resolve.

    INV-SCHEDULEDAY-ONE-PER-DATE-001: store() rejects duplicates.
    Use force_replace() for atomic regeneration.
    """

    def get(self, channel_id: str, programming_day_date: date) -> ResolvedScheduleDay | None:
        """Get a resolved schedule day, or None if not yet resolved."""
        ...

    def store(self, channel_id: str, resolved: ResolvedScheduleDay) -> None:
        """Store a resolved schedule day. Rejects if record already exists."""
        ...

    def exists(self, channel_id: str, programming_day_date: date) -> bool:
        """Check if a day has already been resolved."""
        ...

    def force_replace(self, channel_id: str, resolved: ResolvedScheduleDay) -> None:
        """Atomically replace an existing ResolvedScheduleDay."""
        ...

    def update(
        self, channel_id: str, programming_day_date: date, fields: dict
    ) -> None:
        """INV-SCHEDULEDAY-IMMUTABLE-001: Always rejects. In-place mutation forbidden."""
        ...

    def operator_override(
        self, channel_id: str, resolved: ResolvedScheduleDay
    ) -> ResolvedScheduleDay:
        """Create an operator override record for an existing ScheduleDay."""
        ...


class EPGProvider(Protocol):
    """
    Protocol for EPG query capability.

    Phase 3 adds this interface for EPG consumers (Prevue channel, guide API).
    """

    def get_epg_events(
        self,
        channel_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[EPGEvent]:
        """
        Get EPG events for the specified time range.

        Returns resolved events with episode information.
        Events are immutable once returned.
        """
        ...


@dataclass
class ScheduleManagerConfig:
    """
    Configuration for ScheduleManager.

    Adds dynamic content selection via Programs with episode
    selection logic.
    """
    grid_minutes: int                          # Grid slot duration (e.g., 30)
    program_catalog: ProgramCatalog            # Provider of Program definitions
    sequence_store: SequenceStateStore         # Persistence for sequential state
    resolved_store: ResolvedScheduleStore      # Persistence for resolved schedules
    filler_path: str                           # Path to filler content
    filler_duration_seconds: float = 0.0       # Duration of filler file
    programming_day_start_hour: int = 6        # Broadcast day start


# =============================================================================
# INV-EXEC-NO-STRUCTURE-001: Typed block objects for execution layer
# =============================================================================


@dataclass(frozen=True)
class ScheduledSegment:
    """One segment within a ScheduledBlock. Immutable.

    Produced by the schedule/planning layer.
    Consumed (read-only) by the execution layer.
    """
    segment_type: str           # "content", "filler", "padding", "episode", "pad"
    asset_uri: str              # File path for playback
    asset_start_offset_ms: int  # Seek offset into file
    segment_duration_ms: int    # Duration of this segment
    # Transition fields (INV-TRANSITION-001..005: SegmentTransitionContract.md)
    # Applied only to second-class breakpoints (computed interval division).
    # First-class breakpoints (chapter markers) use TRANSITION_NONE (default).
    transition_in: str = "TRANSITION_NONE"       # "TRANSITION_NONE" | "TRANSITION_FADE"
    transition_in_duration_ms: int = 0           # Duration of fade-in in ms (0 if NONE)
    transition_out: str = "TRANSITION_NONE"      # "TRANSITION_NONE" | "TRANSITION_FADE"
    transition_out_duration_ms: int = 0          # Duration of fade-out in ms (0 if NONE)


@dataclass(frozen=True)
class ScheduledBlock:
    """A fully constructed block from the schedule layer. Immutable.

    Execution consumes this object. Execution NEVER constructs it.
    All timing comes from the schedule/planning layer.

    INV-EXEC-NO-STRUCTURE-001: Execution SHALL NOT define block duration.
    INV-EXEC-NO-BOUNDARY-001: Execution MAY NOT compute block boundaries.
    """
    block_id: str
    start_utc_ms: int
    end_utc_ms: int
    segments: tuple[ScheduledSegment, ...]  # tuple for true immutability

    @property
    def duration_ms(self) -> int:
        return self.end_utc_ms - self.start_utc_ms
