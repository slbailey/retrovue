"""Planning Pipeline

Headless, artifact-producing pipeline that transforms editorial intent into
execution-ready transmission logs. Directive → SchedulePlan → ScheduleDay →
EPG → SegmentedBlocks → FilledBlocks → TransmissionLog (optionally locked).

Testable with no database, no filesystem, no AIR.

Contract authorities:
  ScheduleManagerPlanningAuthority v0.1
  ProgramSegmentationAndAdAvail v0.1
  ScheduleExecutionInterface v0.1
  ScheduleHorizonManagement v0.1
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from retrovue.runtime.schedule_manager import ScheduleManager
from retrovue.runtime.schedule_types import (
    EPGEvent,
    ScheduleManagerConfig,
    ProgramEvent,
    ProgramRef,
    ProgramRefType,
    ResolvedScheduleDay,
    ResolvedSlot,
    ScheduleSlot,
)


# =============================================================================
# Support Types
# =============================================================================


@dataclass
class MarkerInfo:
    """Lightweight marker data (no SQLAlchemy dependency)."""
    kind: str           # e.g. "chapter"
    offset_ms: int      # Offset from asset start in milliseconds
    label: str = ""


@dataclass
class FillerAsset:
    """Filler item resolved from AssetLibrary."""
    asset_uri: str
    duration_ms: int
    asset_type: str = "filler"   # "filler", "promo", "ad"


# =============================================================================
# Protocols
# =============================================================================


class AssetLibrary(Protocol):
    """Read-only interface for markers, durations, filler resolution.

    ALL material (including filler) is resolved through this protocol.
    Duration always comes from the catalog, never hardcoded.
    """

    def get_markers(self, asset_uri: str) -> list[MarkerInfo]: ...

    def get_duration_ms(self, asset_uri: str) -> int: ...

    def get_filler_assets(
        self, max_duration_ms: int, count: int = 1
    ) -> list[FillerAsset]: ...


# =============================================================================
# Policy Types
# =============================================================================


@dataclass
class SyntheticBreakProfile:
    """Policy for synthetic break insertion.

    Expressed in terms of the block slot model, not content duration.
    A half-hour block with an ~22-minute episode uses the same profile
    as a half-hour block with a ~28-minute episode.
    """
    half_hour_block_segments: int = 3   # → 2 inserted breaks
    hour_block_segments: int = 6        # → 5 inserted breaks


@dataclass
class BreakFillPolicy:
    """Policy controls for break filling."""
    allow_repeat_within_break: bool = True
    preferred_filler_type: str = "filler"


# =============================================================================
# Editorial Intent (date-independent)
# =============================================================================


@dataclass
class ZoneDirective:
    """One zone: time window + ordered program references."""
    start_time: time
    end_time: time
    programs: list[ProgramRef]
    label: str = ""
    day_filter: list[str] | None = None   # e.g. ["mon","tue"] or None=all


@dataclass
class PlanningDirective:
    """Date-independent editorial input: channel config + zones.

    Contains NO broadcast_date — this is a reusable template.
    """
    channel_id: str
    grid_block_minutes: int
    programming_day_start_hour: int
    zones: list[ZoneDirective]


@dataclass
class SchedulePlanArtifact:
    """Editorial intent, date-independent template.

    Carries NO broadcast_date. Reusable across any date for resolution.
    """
    channel_id: str
    grid_block_minutes: int
    programming_day_start_hour: int
    zones: list[ZoneDirective]
    all_program_refs: list[ProgramRef]


# =============================================================================
# Schedule Day
# =============================================================================


@dataclass
class PlanningRunRequest:
    """Date-scoped invocation: directive + broadcast_date + resolution_time.

    Binds a PlanningDirective to a specific date for execution.
    """
    directive: PlanningDirective
    broadcast_date: date
    resolution_time: datetime


@dataclass
class ScheduleDayArtifact:
    """Frozen snapshot of what airs when for one channel/date.

    Wraps the internal ResolvedScheduleDay to present the contract-named artifact.
    """
    resolved_day: ResolvedScheduleDay
    slots_generated: int


# =============================================================================
# Segmentation (per-block, no wall-clock)
# =============================================================================


@dataclass
class ContentSegmentSpec:
    """Contiguous content between inserted breakpoints.

    All offsets are asset-relative, in milliseconds. No wall-clock times.
    """
    asset_uri: str
    asset_start_offset_ms: int
    duration_ms: int


@dataclass
class BreakSpec:
    """Inserted break opportunity with allocated duration."""
    break_index: int
    duration_ms: int


@dataclass
class SegmentedBlock:
    """Per block: content segments + inserted breaks.

    All offsets relative to block start (ms). No wall-clock times.
    Identity derived from ProgramEvent per Grid Block Model
    (docs/domains/ProgramEventSchedulingModel_v0.1.md).
    """
    slot_index: int
    resolved_slot: ResolvedSlot
    content_segments: list[ContentSegmentSpec]
    breaks: list[BreakSpec]
    content_duration_ms: int
    block_duration_ms: int
    pad_ms: int
    program_event_id: str = ""
    block_index_within_event: int = 0


# =============================================================================
# Playlist (filled breaks)
# =============================================================================


@dataclass
class BreakItem:
    """One filler/promo/ad item within a filled break."""
    asset_uri: str
    duration_ms: int
    asset_type: str = "filler"   # "filler", "promo", "ad"


@dataclass
class FilledBreak:
    """Break with resolved filler items."""
    break_index: int
    allocated_ms: int
    items: list[BreakItem] = field(default_factory=list)

    @property
    def filled_ms(self) -> int:
        return sum(item.duration_ms for item in self.items)


@dataclass
class FilledBlock:
    """Content + filled breaks (Playlist)."""
    slot_index: int
    resolved_slot: ResolvedSlot
    content_segments: list[ContentSegmentSpec]
    filled_breaks: list[FilledBreak]
    content_duration_ms: int
    block_duration_ms: int
    pad_ms: int
    program_event_id: str = ""
    block_index_within_event: int = 0


# =============================================================================
# Transmission Log (wall-clock aligned)
# =============================================================================


@dataclass
class TransmissionLogEntry:
    """One block's execution-ready segments (wall-clock aligned)."""
    block_id: str
    block_index: int
    start_utc_ms: int
    end_utc_ms: int
    segments: list[dict[str, Any]]


@dataclass
class TransmissionLog:
    """Full day of entries. is_locked marks execution eligibility."""
    channel_id: str
    broadcast_date: date
    entries: list[TransmissionLogEntry]
    is_locked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Directive → Schedule Plan
# =============================================================================


def build_schedule_plan(
    directive: PlanningDirective,
) -> SchedulePlanArtifact:
    """Capture editorial intent as a date-independent plan.

    Does NOT:
    - Perform grid expansion or produce ScheduleSlots
    - Do any grid math, duration calculation, or date-specific logic
    - Query the Asset Library or resolve episodes
    """
    all_refs: list[ProgramRef] = []
    seen: set[tuple[str, str]] = set()
    for zone in directive.zones:
        for ref in zone.programs:
            key = (ref.ref_type.value, ref.ref_id)
            if key not in seen:
                all_refs.append(ref)
                seen.add(key)

    return SchedulePlanArtifact(
        channel_id=directive.channel_id,
        grid_block_minutes=directive.grid_block_minutes,
        programming_day_start_hour=directive.programming_day_start_hour,
        zones=list(directive.zones),
        all_program_refs=all_refs,
    )


# =============================================================================
# Schedule Plan + Date → Schedule Day
# =============================================================================


def _zone_to_slots(
    zone: ZoneDirective,
    grid_block_minutes: int,
    programming_day_start_hour: int,
    broadcast_date: date,
) -> list[ScheduleSlot]:
    """Expand a zone directive into grid-aligned ScheduleSlots for one date."""
    grid_seconds = grid_block_minutes * 60

    # Convert zone start/end to absolute datetimes
    zone_start_dt = datetime.combine(broadcast_date, zone.start_time)
    if zone.start_time.hour < programming_day_start_hour:
        zone_start_dt += timedelta(days=1)

    zone_end_dt = datetime.combine(broadcast_date, zone.end_time)
    if zone.end_time.hour < programming_day_start_hour:
        zone_end_dt += timedelta(days=1)
    # Handle midnight-wrapping zones (e.g. 22:00–02:00)
    if zone_end_dt <= zone_start_dt:
        zone_end_dt += timedelta(days=1)

    zone_duration_seconds = (zone_end_dt - zone_start_dt).total_seconds()
    num_slots = int(zone_duration_seconds / grid_seconds)

    slots: list[ScheduleSlot] = []
    program_idx = 0
    for i in range(num_slots):
        slot_dt = zone_start_dt + timedelta(seconds=i * grid_seconds)
        ref = zone.programs[program_idx % len(zone.programs)]
        slots.append(ScheduleSlot(
            slot_time=slot_dt.time(),
            program_ref=ref,
            duration_seconds=float(grid_seconds),
            label=zone.label or ref.ref_id,
        ))
        program_idx += 1

    return slots


def resolve_schedule_day(
    plan: SchedulePlanArtifact,
    run_request: PlanningRunRequest,
    config: ScheduleManagerConfig,
) -> ScheduleDayArtifact:
    """Expand zones into grid-aligned slots, then resolve episodes.

    This is the only stage with side effects (cursor advancement).
    Delegates to ScheduleManager.resolve_schedule_day() for resolution.
    """
    all_slots: list[ScheduleSlot] = []
    for zone in plan.zones:
        zone_slots = _zone_to_slots(
            zone,
            plan.grid_block_minutes,
            plan.programming_day_start_hour,
            run_request.broadcast_date,
        )
        all_slots.extend(zone_slots)

    manager = ScheduleManager(config)
    resolved_day = manager.resolve_schedule_day(
        channel_id=plan.channel_id,
        programming_day_date=run_request.broadcast_date,
        slots=all_slots,
        resolution_time=run_request.resolution_time,
    )

    return ScheduleDayArtifact(
        resolved_day=resolved_day,
        slots_generated=len(all_slots),
    )


# =============================================================================
# Schedule Day → EPG Events
# =============================================================================


def derive_epg(
    channel_id: str,
    schedule_day: ScheduleDayArtifact,
    programming_day_start_hour: int,
    grid_block_minutes: int = 30,
) -> list[EPGEvent]:
    """Derive viewer-facing EPG events from the Schedule Day.

    Read-only derivation — one EPGEvent per ProgramEvent.
    EPG is never a source of truth for planning.
    """
    return _derive_epg_from_program_events(
        channel_id,
        schedule_day.resolved_day,
        grid_block_minutes,
        programming_day_start_hour,
    )


def _derive_epg_from_program_events(
    channel_id: str,
    rd: ResolvedScheduleDay,
    grid_block_minutes: int,
    programming_day_start_hour: int,
) -> list[EPGEvent]:
    """Derive one EPGEvent per ProgramEvent.

    ProgramEvents and resolved_slots are generated in lockstep.
    Resolved_slots carry per-block asset details; ProgramEvents carry identity.
    """
    events: list[EPGEvent] = []
    grid_occupancy_seconds = grid_block_minutes * 60
    slot_idx = 0

    for pe in rd.program_events:
        # Use slot_time from first ResolvedSlot (avoids epoch-UTC round-trip)
        slot = rd.resolved_slots[slot_idx]
        start_dt = _slot_time_to_datetime(
            rd.programming_day_date, slot.slot_time, programming_day_start_hour
        )
        end_dt = start_dt + timedelta(
            seconds=pe.block_span_count * grid_occupancy_seconds
        )

        resolved_asset = pe.resolved_asset or slot.resolved_asset

        events.append(EPGEvent(
            channel_id=channel_id,
            start_time=start_dt,
            end_time=end_dt,
            title=resolved_asset.title,
            episode_title=resolved_asset.episode_title,
            episode_id=resolved_asset.episode_id,
            resolved_asset=resolved_asset,
            programming_day_date=rd.programming_day_date,
        ))

        slot_idx += pe.block_span_count

    return events


def _slot_time_to_datetime(
    programming_day_date: date,
    slot_time: time,
    programming_day_start_hour: int,
) -> datetime:
    """Convert a slot time to absolute datetime."""
    base = datetime.combine(programming_day_date, slot_time)
    if slot_time.hour < programming_day_start_hour:
        base += timedelta(days=1)
    return base


# =============================================================================
# Schedule Day → Segmented Blocks
# =============================================================================


def segment_blocks(
    schedule_day: ScheduleDayArtifact,
    grid_block_minutes: int,
    asset_library: AssetLibrary,
    break_profile: SyntheticBreakProfile | None = None,
) -> list[SegmentedBlock]:
    """Apply program segmentation per ProgramSegmentationAndAdAvail contract.

    Blocks derive identity from ProgramEvents. Each block carries
    program_event_id and block_index_within_event so that multi-block
    events produce contiguous blocks referencing the same event.
    Segmentation is purely per-block — no wall-clock alignment.
    """
    if break_profile is None:
        break_profile = SyntheticBreakProfile()

    block_duration_ms = grid_block_minutes * 60 * 1000
    rd = schedule_day.resolved_day
    result: list[SegmentedBlock] = []

    # Map each block to its ProgramEvent identity.
    # ProgramEvents define event spans; resolved_slots carry per-block asset details.
    block_assignments: list[tuple[int, str, int]] = []
    slot_idx = 0
    for pe in rd.program_events:
        for bi in range(pe.block_span_count):
            if slot_idx < len(rd.resolved_slots):
                block_assignments.append((slot_idx, pe.id, bi))
                slot_idx += 1

    for slot_idx, pe_id, bi in block_assignments:
        slot = rd.resolved_slots[slot_idx]
        asset_uri = slot.resolved_asset.file_path
        full_content_dur_ms = asset_library.get_duration_ms(asset_uri)
        markers = asset_library.get_markers(asset_uri)
        chapter_markers = sorted(
            [m for m in markers if m.kind == "chapter"],
            key=lambda m: m.offset_ms,
        )

        # Compute per-block content slice for multi-block events
        event_offset_ms = bi * block_duration_ms
        slice_end_ms = min(event_offset_ms + block_duration_ms, full_content_dur_ms)
        slice_dur_ms = max(0, slice_end_ms - event_offset_ms)

        # Filter chapter markers to this block's window
        block_chapters = [
            MarkerInfo(m.kind, m.offset_ms - event_offset_ms, m.label)
            for m in chapter_markers
            if event_offset_ms < m.offset_ms < slice_end_ms
        ]

        if block_chapters:
            segments, breaks = _segment_with_chapters(
                asset_uri, slice_dur_ms, block_chapters, block_duration_ms,
                asset_start_offset_ms=event_offset_ms,
            )
        else:
            num_segments = _get_segment_count(
                break_profile, grid_block_minutes
            )
            segments, breaks = _segment_synthetic(
                asset_uri, slice_dur_ms, block_duration_ms, num_segments,
                asset_start_offset_ms=event_offset_ms,
            )

        pad_ms = max(0, block_duration_ms - slice_dur_ms - sum(b.duration_ms for b in breaks))

        result.append(SegmentedBlock(
            slot_index=slot_idx,
            resolved_slot=slot,
            content_segments=segments,
            breaks=breaks,
            content_duration_ms=slice_dur_ms,
            block_duration_ms=block_duration_ms,
            pad_ms=pad_ms,
            program_event_id=pe_id,
            block_index_within_event=bi,
        ))

    return result


def _get_segment_count(
    profile: SyntheticBreakProfile,
    grid_block_minutes: int,
) -> int:
    """Get number of content segments based on block duration and profile."""
    if grid_block_minutes >= 60:
        return profile.hour_block_segments
    return profile.half_hour_block_segments


def _segment_with_chapters(
    asset_uri: str,
    content_dur_ms: int,
    chapter_markers: list[MarkerInfo],
    block_duration_ms: int,
    asset_start_offset_ms: int = 0,
) -> tuple[list[ContentSegmentSpec], list[BreakSpec]]:
    """Segment content using chapter markers as breakpoints."""
    segments: list[ContentSegmentSpec] = []
    breaks: list[BreakSpec] = []

    # Build content segments from chapter boundaries
    boundaries = [0] + [m.offset_ms for m in chapter_markers] + [content_dur_ms]
    # Remove duplicates and sort
    boundaries = sorted(set(boundaries))

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        if end > start:
            segments.append(ContentSegmentSpec(
                asset_uri=asset_uri,
                asset_start_offset_ms=start + asset_start_offset_ms,
                duration_ms=end - start,
            ))

    # Insert breaks between content segments
    total_content_ms = sum(s.duration_ms for s in segments)
    inventory_ms = max(0, block_duration_ms - total_content_ms)

    num_breaks = max(0, len(segments) - 1)
    if num_breaks > 0 and inventory_ms > 0:
        per_break_ms = inventory_ms // num_breaks
        remainder_ms = inventory_ms % num_breaks
        for i in range(num_breaks):
            extra = 1 if i < remainder_ms else 0
            breaks.append(BreakSpec(
                break_index=i,
                duration_ms=per_break_ms + extra,
            ))

    return segments, breaks


def _segment_synthetic(
    asset_uri: str,
    content_dur_ms: int,
    block_duration_ms: int,
    num_segments: int,
    asset_start_offset_ms: int = 0,
) -> tuple[list[ContentSegmentSpec], list[BreakSpec]]:
    """Segment content using synthetic breakpoints."""
    if content_dur_ms >= block_duration_ms or num_segments <= 1:
        # Content fills or exceeds block — no breaks
        return [ContentSegmentSpec(
            asset_uri=asset_uri,
            asset_start_offset_ms=asset_start_offset_ms,
            duration_ms=content_dur_ms,
        )], []

    # Divide content into equal segments
    segment_dur_ms = content_dur_ms // num_segments
    remainder_ms = content_dur_ms % num_segments

    segments: list[ContentSegmentSpec] = []
    offset = 0
    for i in range(num_segments):
        extra = 1 if i < remainder_ms else 0
        dur = segment_dur_ms + extra
        segments.append(ContentSegmentSpec(
            asset_uri=asset_uri,
            asset_start_offset_ms=offset + asset_start_offset_ms,
            duration_ms=dur,
        ))
        offset += dur

    # Calculate break inventory
    total_content_ms = sum(s.duration_ms for s in segments)
    inventory_ms = max(0, block_duration_ms - total_content_ms)

    num_breaks = num_segments - 1
    breaks: list[BreakSpec] = []
    if num_breaks > 0 and inventory_ms > 0:
        per_break_ms = inventory_ms // num_breaks
        break_remainder = inventory_ms % num_breaks
        for i in range(num_breaks):
            extra = 1 if i < break_remainder else 0
            breaks.append(BreakSpec(
                break_index=i,
                duration_ms=per_break_ms + extra,
            ))

    return segments, breaks


# =============================================================================
# Fill breaks Segmented Blocks → Playlist (Filled Blocks)
# =============================================================================


def fill_breaks(
    segmented_blocks: list[SegmentedBlock],
    asset_library: AssetLibrary,
    policy: BreakFillPolicy | None = None,
) -> list[FilledBlock]:
    """Fill each inserted break with filler/promo/ad material.

    All material resolved via AssetLibrary. Duration from catalog.
    """
    if policy is None:
        policy = BreakFillPolicy()

    result: list[FilledBlock] = []
    for block in segmented_blocks:
        filled_breaks: list[FilledBreak] = []
        for brk in block.breaks:
            filled = _fill_one_break(brk, asset_library, policy)
            filled_breaks.append(filled)

        # Absorb unfilled break time back into pad to preserve the invariant:
        # content + filled_breaks + pad == block_duration
        unfilled_ms = sum(
            fb.allocated_ms - fb.filled_ms
            for fb in filled_breaks
        )
        adjusted_pad_ms = block.pad_ms + unfilled_ms

        result.append(FilledBlock(
            slot_index=block.slot_index,
            resolved_slot=block.resolved_slot,
            content_segments=block.content_segments,
            filled_breaks=filled_breaks,
            content_duration_ms=block.content_duration_ms,
            block_duration_ms=block.block_duration_ms,
            pad_ms=adjusted_pad_ms,
            program_event_id=block.program_event_id,
            block_index_within_event=block.block_index_within_event,
        ))

    return result


def _fill_one_break(
    brk: BreakSpec,
    asset_library: AssetLibrary,
    policy: BreakFillPolicy,
) -> FilledBreak:
    """Pack filler items into a single break."""
    remaining_ms = brk.duration_ms
    items: list[BreakItem] = []
    used_uris: set[str] = set()

    while remaining_ms > 0:
        fillers = asset_library.get_filler_assets(
            max_duration_ms=remaining_ms, count=5
        )
        if not fillers:
            break

        placed = False
        for filler in fillers:
            if not policy.allow_repeat_within_break and filler.asset_uri in used_uris:
                continue
            if filler.duration_ms <= remaining_ms:
                items.append(BreakItem(
                    asset_uri=filler.asset_uri,
                    duration_ms=filler.duration_ms,
                    asset_type=filler.asset_type,
                ))
                remaining_ms -= filler.duration_ms
                used_uris.add(filler.asset_uri)
                placed = True
                break

        if not placed:
            break

    return FilledBreak(
        break_index=brk.break_index,
        allocated_ms=brk.duration_ms,
        items=items,
    )


# =============================================================================
# Assemble transmission log Playlist → Transmission Log
# =============================================================================


def assemble_transmission_log(
    channel_id: str,
    broadcast_date: date,
    filled_blocks: list[FilledBlock],
    epg_events: list[EPGEvent],
    programming_day_start_hour: int,
    grid_block_minutes: int,
    generation_time: datetime,
) -> TransmissionLog:
    """Assemble execution artifact with wall-clock alignment.

    Block-relative offsets from Stages 3-4 are translated to absolute
    epoch millisecond times. Interleaves content segments and break items
    into a flat, ordered segment list per block.
    """
    entries: list[TransmissionLogEntry] = []
    rd_date = broadcast_date

    for block_idx, fb in enumerate(filled_blocks):
        slot = fb.resolved_slot
        block_start_dt = _slot_time_to_datetime(
            rd_date, slot.slot_time, programming_day_start_hour
        )
        utc_dt = block_start_dt.replace(tzinfo=timezone.utc)
        block_start_ms = int(utc_dt.timestamp() * 1000)
        block_end_ms = block_start_ms + fb.block_duration_ms

        block_id = f"{channel_id}-{broadcast_date.isoformat()}-{block_idx:04d}"
        flat_segments = _interleave_segments(fb, block_start_ms)

        # Assign stable event_id to each segment for evidence reconciliation.
        for seg in flat_segments:
            seg["event_id"] = f"{block_id}-S{seg['segment_index']:04d}"

        entries.append(TransmissionLogEntry(
            block_id=block_id,
            block_index=block_idx,
            start_utc_ms=block_start_ms,
            end_utc_ms=block_end_ms,
            segments=flat_segments,
        ))

    return TransmissionLog(
        channel_id=channel_id,
        broadcast_date=broadcast_date,
        entries=entries,
        is_locked=False,
        metadata={
            "generation_time": generation_time.isoformat(),
            "grid_block_minutes": grid_block_minutes,
            "programming_day_start_hour": programming_day_start_hour,
        },
    )


def _interleave_segments(
    fb: FilledBlock,
    block_start_ms: int,
) -> list[dict[str, Any]]:
    """Interleave content segments and break items into flat segment list."""
    flat: list[dict[str, Any]] = []
    seg_index = 0
    break_iter = iter(fb.filled_breaks)
    next_break: FilledBreak | None = next(break_iter, None)

    for i, cs in enumerate(fb.content_segments):
        # Add content segment
        flat.append({
            "segment_index": seg_index,
            "asset_uri": cs.asset_uri,
            "asset_start_offset_ms": cs.asset_start_offset_ms,
            "segment_duration_ms": cs.duration_ms,
            "segment_type": "episode",
        })
        seg_index += 1

        # After each content segment (except the last), insert break items
        if next_break is not None and i < len(fb.content_segments) - 1:
            for item in next_break.items:
                seg_type = item.asset_type if item.asset_type in ("filler", "promo", "ad") else "filler"
                flat.append({
                    "segment_index": seg_index,
                    "asset_uri": item.asset_uri,
                    "asset_start_offset_ms": 0,
                    "segment_duration_ms": item.duration_ms,
                    "segment_type": seg_type,
                })
                seg_index += 1
            next_break = next(break_iter, None)

    # Append PAD segment if needed
    if fb.pad_ms > 0:
        flat.append({
            "segment_index": seg_index,
            "segment_duration_ms": fb.pad_ms,
            "segment_type": "pad",
        })

    return flat


def to_block_plan(entry: TransmissionLogEntry, channel_id_int: int) -> dict[str, Any]:
    """Convert a TransmissionLogEntry to a BlockPlan-compatible dict.

    Produces the format consumed by playout_session.BlockPlan.from_dict().
    """
    return {
        "block_id": entry.block_id,
        "channel_id": channel_id_int,
        "start_utc_ms": entry.start_utc_ms,
        "end_utc_ms": entry.end_utc_ms,
        "segments": entry.segments,
    }


# =============================================================================
# Transmission Log → Horizon-Locked Transmission Log
# =============================================================================


def lock_transmission_log(log: TransmissionLog, lock_time: datetime) -> TransmissionLog:
    """Mark the Transmission Log as execution-eligible and immutable (lock only, no write).

    Validates seam invariants. Returns a locked TransmissionLog with deterministic
    transmission_log_id. Does NOT write artifacts; use TransmissionLogArtifactWriter
    after this for artifact write (e.g. plan-day CLI).
    """
    from retrovue.runtime.transmission_log_validator import (
        TransmissionLogSeamError,
        validate_transmission_log_seams,
    )

    grid_min = log.metadata.get("grid_block_minutes")
    if grid_min is None:
        raise TransmissionLogSeamError(
            "lock_transmission_log: grid_block_minutes missing from log.metadata; "
            "cannot validate seam invariants"
        )
    validate_transmission_log_seams(log, int(grid_min))

    new_metadata = dict(log.metadata)
    new_metadata["locked_at"] = lock_time.isoformat()
    # Deterministic ID for planning harness (no random UUIDs)
    seed = f"{log.channel_id}:{log.broadcast_date.isoformat()}:{lock_time.isoformat()}"
    new_metadata["transmission_log_id"] = hashlib.sha256(seed.encode()).hexdigest()[:32]

    return TransmissionLog(
        channel_id=log.channel_id,
        broadcast_date=log.broadcast_date,
        entries=log.entries,
        is_locked=True,
        metadata=new_metadata,
    )


def lock_for_execution(
    log: TransmissionLog,
    lock_time: datetime,
    timezone_display: str = "UTC",
    artifact_base_path: Path | None = None,
) -> TransmissionLog:
    """Mark the Transmission Log as execution-eligible and immutable.

    This is a lifecycle state transition, not a data transform.
    Validates seam invariants before marking execution-eligible.
    After lock, writes transmission log artifacts (.tlog + .tlog.jsonl).
    """
    locked = lock_transmission_log(log, lock_time)

    from retrovue.planning.transmission_log_artifact_writer import (
        TransmissionLogArtifactWriter,
    )

    base_path = artifact_base_path or Path("/opt/retrovue/data/logs/transmission")
    writer = TransmissionLogArtifactWriter(base_path=base_path)
    writer.write(
        channel_id=locked.channel_id,
        broadcast_date=locked.broadcast_date,
        transmission_log=locked,
        timezone_display=timezone_display,
        generated_utc=lock_time,
    )

    return locked


# =============================================================================
# Orchestrator
# =============================================================================


def run_planning_pipeline(
    run_request: PlanningRunRequest,
    config: ScheduleManagerConfig,
    asset_library: AssetLibrary,
    lock_time: datetime | None = None,
    break_profile: SyntheticBreakProfile | None = None,
    break_fill_policy: BreakFillPolicy | None = None,
    artifact_base_path: Path | None = None,
) -> TransmissionLog:
    """Execute pipeline: Directive → SchedulePlan → ScheduleDay → EPG →
    SegmentedBlocks → FilledBlocks → TransmissionLog (optionally locked).
    """
    directive = run_request.directive

    plan = build_schedule_plan(directive)
    schedule_day = resolve_schedule_day(plan, run_request, config)
    epg_events = derive_epg(
        directive.channel_id,
        schedule_day,
        directive.programming_day_start_hour,
        grid_block_minutes=directive.grid_block_minutes,
    )
    segmented = segment_blocks(
        schedule_day,
        directive.grid_block_minutes,
        asset_library,
        break_profile=break_profile,
    )
    filled = fill_breaks(
        segmented, asset_library, policy=break_fill_policy
    )
    log = assemble_transmission_log(
        channel_id=directive.channel_id,
        broadcast_date=run_request.broadcast_date,
        filled_blocks=filled,
        epg_events=epg_events,
        programming_day_start_hour=directive.programming_day_start_hour,
        grid_block_minutes=directive.grid_block_minutes,
        generation_time=run_request.resolution_time,
    )
    if lock_time is not None:
        log = lock_for_execution(
            log, lock_time, artifact_base_path=artifact_base_path
        )

    return log


# =============================================================================
# Test Mock: InMemoryAssetLibrary
# =============================================================================


class InMemoryAssetLibrary:
    """Test mock implementing AssetLibrary protocol."""

    def __init__(self) -> None:
        self._durations: dict[str, int] = {}
        self._markers: dict[str, list[MarkerInfo]] = {}
        self._fillers: list[FillerAsset] = []

    def register_asset(
        self,
        asset_uri: str,
        duration_ms: int,
        markers: list[MarkerInfo] | None = None,
    ) -> None:
        self._durations[asset_uri] = duration_ms
        if markers:
            self._markers[asset_uri] = markers

    def register_filler(
        self,
        asset_uri: str,
        duration_ms: int,
        asset_type: str = "filler",
    ) -> None:
        self._fillers.append(FillerAsset(
            asset_uri=asset_uri,
            duration_ms=duration_ms,
            asset_type=asset_type,
        ))
        self._durations[asset_uri] = duration_ms

    def get_markers(self, asset_uri: str) -> list[MarkerInfo]:
        return list(self._markers.get(asset_uri, []))

    def get_duration_ms(self, asset_uri: str) -> int:
        return self._durations.get(asset_uri, 0)

    def get_filler_assets(
        self, max_duration_ms: int, count: int = 1
    ) -> list[FillerAsset]:
        eligible = [f for f in self._fillers if f.duration_ms <= max_duration_ms]
        return eligible[:count]
