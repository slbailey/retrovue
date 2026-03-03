# pkg/core/src/retrovue/runtime/template_runtime.py
#
# In-memory runtime model for the Template Assembly + Schedule DSL.
#
# Governs:
#   Template definition, segment composition, template resolution lifecycle,
#   duration enforcement, selection rule evaluation, schedule window management.
#
# ─── Layer map (bottom-up) ───────────────────────────────────────────────────
#
#   L0  Config          — TemplateRegistry (live template definitions)
#   L1  Tier 1          — ScheduleRegistry + TemplateReferenceIndex
#   L2  Tier 2          — PlaylogRegistry + PlaylogWindow
#   L3  Active tracking — ChannelActiveState
#   L4  Coordinator     — ChannelRuntimeState (one per channel)
#
# ─── Ownership rules ─────────────────────────────────────────────────────────
#
#   Config loader     writes L0; no other layer writes L0
#   Scheduler         writes L1; co-maintains L1 index atomically
#   ProgramDirector   writes L2; reads L0 live at each build
#   ChannelManager    reads L2; writes L3 transitions only
#
#   No layer may write to a layer it does not own.
#   No snapshot of L0 is taken at L1 commit time.
#
# ─── GLOBAL LOCK ORDERING (CRITICAL — read before acquiring any lock) ────────
#
#   When acquiring multiple locks simultaneously, ALWAYS acquire in this order:
#
#       1. TemplateRegistry._lock
#       2. ScheduleRegistry._lock
#       3. TemplateReferenceIndex._lock
#       4. PlaylogRegistry._lock
#
#   Never acquire a lock at a lower index while holding a lock at a higher
#   index number. Violating this order is a deadlock hazard.
#
#   Example (correct):
#       with schedule_registry._lock:
#           with template_ref_index._lock:
#               ...   # ScheduleRegistry(2) before TemplateRefIndex(3) ✓
#
#   Example (WRONG — will deadlock):
#       with template_ref_index._lock:       # acquires 3
#           with schedule_registry._lock:    # tries to acquire 2 → DEADLOCK ✗
#               ...
#
#   Single-lock operations may acquire any lock independently without
#   considering this order. The rule applies only when multiple locks
#   are held simultaneously.
#
# ─── External dependency interfaces ─────────────────────────────────────────
#
#   Three external interfaces are consumed at Tier 2 resolution time.
#   They are declared as Protocols below and documented at the bottom of
#   this file. Implementations live outside this module.
#
#   AssetCatalog     — asset resolution and approval-state checks
#   MetadataEvaluator — selection rule evaluation against asset metadata
#   Clock            — wall-clock authority for activation boundary decisions
#

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


# ─────────────────────────────────────────────────────────────────────────────
# External dependency interfaces
#
# These Protocols define the boundaries between the template/schedule runtime
# and external systems. They are comment-level contracts: the signatures
# describe what the runtime requires, not how it is implemented.
#
# LOCK ORDERING NOTE: implementations of these interfaces MUST NOT acquire
# any of the runtime locks (TemplateRegistry, ScheduleRegistry,
# TemplateReferenceIndex, PlaylogRegistry) internally. Doing so would place
# an external call inside a lock and create inversion risk.
# ─────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class AssetCatalog(Protocol):
    """Provides asset resolution and approval-state queries.

    Used by Tier 2 resolver to:
      - Resolve an asset_id to its physical path and duration_ms.
      - Check whether a candidate asset is in an approved state before
        emitting it as a resolved segment.

    An asset that fails the approval check is treated as absent from the
    candidate set (equivalent to VAL-T2-008). The catalog never returns
    an unapproved asset as a valid resolution result.

    The catalog is read-only from the perspective of the resolver.
    All mutations to catalog state (ingest, approval, retirement) occur
    outside the Tier 2 build path.

    Implementations MUST NOT acquire any runtime lock (TemplateRegistry,
    ScheduleRegistry, TemplateReferenceIndex, PlaylogRegistry) internally.
    """
    def get_asset_duration_ms(self, asset_id: str) -> int | None:
        """Return the duration in milliseconds for asset_id, or None if absent."""
        ...

    def is_approved(self, asset_id: str) -> bool:
        """Return True if the asset is in an approved state for playout."""
        ...


@runtime_checkable
class MetadataEvaluator(Protocol):
    """Evaluates selection rules against asset metadata.

    Used by Tier 2 resolver to filter candidate asset sets within a
    template segment before the mode strategy is applied.

    Rules are evaluated conjunctively in declared order. If any rule
    produces an invalid or unresolvable result (VAL-T2-006), the evaluator
    raises ResolutionError — it does not return an empty set silently.

    The evaluator is stateless between calls. Rule state from one segment
    does not propagate to another.

    Implementations MUST NOT acquire any runtime lock (TemplateRegistry,
    ScheduleRegistry, TemplateReferenceIndex, PlaylogRegistry) internally.
    """
    def filter_candidates(
        self,
        candidate_asset_ids: list[str],
        rules: tuple[SelectionRule, ...],
        source_name: str,
    ) -> list[str]:
        """Return the subset of candidate_asset_ids that satisfy all rules.

        Raises ResolutionError on VAL-T2-006 (invalid rule or metadata
        property unavailable). Returns an empty list when all candidates
        are filtered out (VAL-T2-007 caller responsibility).
        """
        ...


@runtime_checkable
class Clock(Protocol):
    """Wall-clock authority for activation boundary decisions.

    Used by ChannelManager and ProgramDirector to determine:
      - Whether a PlaylogWindow's wall_start_ms has been reached
        (triggering PENDING → ACTIVE transition).
      - Whether a PlaylogWindow's wall_end_ms has passed
        (triggering ACTIVE → EXPIRED transition).
      - Whether an ACTIVE window's bleed extension has exceeded its
        natural end time (scheduling-layer concern).

    All time comparisons that affect lifecycle transitions MUST use this
    interface. Direct calls to time.time() or datetime.now() within the
    runtime model are prohibited.

    Implementations MUST NOT acquire any runtime lock (TemplateRegistry,
    ScheduleRegistry, TemplateReferenceIndex, PlaylogRegistry) internally.
    """
    def now_ms(self) -> int:
        """Return the current wall-clock time as epoch milliseconds (UTC)."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WindowKey:
    """Time-coordinate identity for a scheduled window.

    WindowKey is the time-based lookup key used across all registries and
    indexes. It is NOT the sole identity of a committed Tier 1 entry —
    that role belongs to ScheduledEntry.window_uuid.

    A given (channel_id, wall_start_ms, wall_end_ms) triple may be
    represented by multiple successive ScheduledEntry commits over time
    if the operator rebuilds the window. Each rebuild produces a new
    window_uuid; the WindowKey remains the same.

    Cross-midnight windows: wall_end_ms > wall_start_ms always holds.
    The Scheduler converts HH:MM boundaries to absolute epoch ms before
    producing a WindowKey, resolving midnight crossing at build time.
    """
    channel_id:    str
    wall_start_ms: int   # epoch ms, UTC
    wall_end_ms:   int   # epoch ms, UTC; invariant: wall_end_ms > wall_start_ms

    def __lt__(self, other: WindowKey) -> bool:
        return (self.channel_id, self.wall_start_ms) < (other.channel_id, other.wall_start_ms)


# ─────────────────────────────────────────────────────────────────────────────
# State enumerations
# ─────────────────────────────────────────────────────────────────────────────

class ScheduleWindowState(enum.Enum):
    COMMITTED = "committed"  # normal; Tier 2 resolution permitted
    BLOCKED   = "blocked"    # VAL-T2-001 fired; no Tier 2 retry until operator
                             # explicitly rebuilds (issues a new window_uuid)


class PlaylogWindowState(enum.Enum):
    PENDING  = "pending"   # resolved; not yet active; may be discarded and rebuilt
    ACTIVE   = "active"    # window-level freeze: no rebuild permitted until EXPIRED
    EXPIRED  = "expired"   # execution completed; retained for as-run lineage


# ─────────────────────────────────────────────────────────────────────────────
# L0 — Config (Template definitions)
#
# Owner:      Config loader
# Read by:    Tier 2 resolver — live at each Tier 2 build; no snapshot taken
# Written by: Config loader only (on channel config load or operator reload)
# Mutable:    yes — operator may modify template definitions between builds;
#             modifications affect the next Tier 2 build of any referencing window
# Protected:  TemplateRegistry._lock (see GLOBAL LOCK ORDERING: position 1)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SegmentSource:
    """Declared content source for a template segment.

    name is required when type is 'collection' or 'pool'.
    name is None when type is 'primary_content'.
    """
    type: Literal["collection", "pool", "primary_content"]
    name: str | None


@dataclass(frozen=True)
class SelectionRule:
    """One filter rule applied to a segment's candidate asset set.

    Rules are evaluated conjunctively in declared order by MetadataEvaluator.
    type is the rule discriminator (e.g. 'tags').
    values are the rule operands.
    """
    type:   str
    values: tuple[str, ...]  # tuple for hashability within frozen TemplateDef


@dataclass(frozen=True)
class TemplateSegment:
    """One segment within a template definition.

    Segments are processed in declared order. Each resolves to exactly one asset.
    selection is empty when no filtering is declared on this segment.
    """
    source:    SegmentSource
    selection: tuple[SelectionRule, ...]  # declared order; may be empty
    mode:      str                        # selection strategy, e.g. 'random'


@dataclass(frozen=True)
class TemplateDef:
    """A complete template definition as declared in channel config.

    Immutable once loaded. The Tier 2 resolver reads this object live at
    each build and never caches or snapshots it.

    PRIMARY SEGMENT DETERMINISM (Modification 5):
    primary_segment_index is computed once at parse time and stored here.
    It is the 0-based index into segments of the segment that constitutes
    the primary content of a resolved event.

    Computation rule (applied by Config loader, not by the resolver):
      1. If exactly one segment has source.type == 'primary_content',
         that segment's index is primary_segment_index.
      2. If no segment has source.type == 'primary_content' and exactly
         one segment has source.type == 'pool', that segment's index is
         primary_segment_index by convention.
      3. Any other configuration is a parse-time failure (VAL-PARSE-015 or
         VAL-T2-004/VAL-T2-005 as applicable).

    Storing primary_segment_index at parse time eliminates all runtime
    inference ambiguity. The resolver never scans segments to locate primary
    content; it reads primary_segment_index directly.

    Invariants:
      0 <= primary_segment_index < len(segments)
      Template ID is unique within its channel (VAL-PARSE-014).
      len(segments) >= 1 (VAL-PARSE-015).
    """
    id:                    str
    segments:              tuple[TemplateSegment, ...]  # declared order; len >= 1
    primary_segment_index: int                          # computed at parse time


@dataclass
class TemplateRegistry:
    """Channel-scoped live template registry.

    One instance per channel. Populated and maintained by Config loader.
    Read live by Tier 2 resolver at the start of each PlaylogWindow build.

    LOCK ORDERING: position 1 — must be acquired before ScheduleRegistry,
    TemplateReferenceIndex, or PlaylogRegistry when multiple locks are held.

    No snapshot is ever taken from this registry. The TemplateDef visible
    at Tier 2 build time is the TemplateDef that governs that build,
    regardless of what was visible at Tier 1 commit time.

    Primary index: template_id (str) → TemplateDef
    """
    _templates: dict[str, TemplateDef] = field(default_factory=dict)
    _lock:      threading.RLock        = field(default_factory=threading.RLock)
    # LOCK ORDERING: position 1 (outermost when held with other runtime locks)


# ─────────────────────────────────────────────────────────────────────────────
# L1 — Tier 1 (Schedule commitments)
#
# Owner:      Scheduler
# Written by: Scheduler (on operator schedule build or explicit operator rebuild)
# Immutable:  yes — after commit, no field changes except:
#               state:                   COMMITTED → BLOCKED
#               blocked_reason_code:     None → str
#               blocked_at_ms:           None → int
#               blocked_details:         None → str
#             All other fields are frozen at commit time.
# Protected:  ScheduleRegistry._lock (see GLOBAL LOCK ORDERING: position 2)
#             TemplateReferenceIndex._lock (see GLOBAL LOCK ORDERING: position 3)
#             Both locks must be acquired together (in order) for any write
#             that touches both ScheduleRegistry and TemplateReferenceIndex.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScheduledEntry:
    """One committed Tier 1 schedule window.

    IDENTITY (Modification 1):
    window_uuid is the stable identity of this specific commit. It is a
    UUID4 string assigned by the Scheduler at commit time. It uniquely
    identifies this particular version of the Tier 1 entry.

    WindowKey is the time-coordinate key used for registry lookups. A given
    WindowKey may be associated with multiple window_uuids over time if the
    operator rebuilds the window. Each rebuild produces a new window_uuid.

    Consumers that need to detect staleness (e.g. ProgramDirector checking
    whether a PlaylogWindow was built from the current commit) compare
    window_uuid values, not WindowKeys.

    BLOCKED STATE METADATA (Modification 3):
    When state transitions to BLOCKED (VAL-T2-001 fires), the three blocked_*
    fields are populated atomically with the failure context. They are None
    while state == COMMITTED.

    A BLOCKED window requires explicit operator rebuild before Tier 2 will
    attempt resolution again. Operator rebuild issues a new window_uuid,
    resets state to COMMITTED, and clears the blocked_* fields.

    Field constraints (enforced upstream at parse / schedule build):
      type == 'template' → name is set, asset_id is None, mode is None
      type == 'pool'     → name is set, asset_id is None, mode may be set
      type == 'asset'    → name is None, asset_id is set, mode is None
    """
    # Identity (Modification 1)
    window_uuid:    str          # UUID4 string; stable identity of this commit;
                                 # changes on every operator rebuild of this window
    window_key:     WindowKey    # time-coordinate; same across rebuilds of the
                                 # same logical window; used as registry dict key

    # Canonical entry schema fields
    type:           Literal["template", "pool", "asset"]
    name:           str | None   # template_id or pool_id
    asset_id:       str | None   # direct asset reference (type == 'asset' only)
    epg_title:      str | None   # if set, EPG identity committed at Tier 1
    allow_bleed:    bool         # default False
    mode:           str | None   # selection strategy (type == 'pool' only)

    # Tier 1 lifecycle
    committed_at_ms: int
    state:           ScheduleWindowState = ScheduleWindowState.COMMITTED

    # BLOCKED failure metadata (Modification 3)
    # All three fields are None while state == COMMITTED.
    # Populated atomically when state transitions to BLOCKED.
    # Cleared atomically when operator rebuild resets state to COMMITTED.
    blocked_reason_code: str | None = None   # machine-readable code, e.g. 'VAL-T2-001'
    blocked_at_ms:       int | None = None   # epoch ms when BLOCKED transition occurred
    blocked_details:     str | None = None   # human-readable context for the operator


@dataclass
class ScheduleRegistry:
    """Channel-scoped Tier 1 schedule window store.

    One instance per channel. Written only by Scheduler.
    Consumers (ProgramDirector, ChannelManager) read only.

    LOCK ORDERING: position 2 — must be acquired after TemplateRegistry
    and before TemplateReferenceIndex or PlaylogRegistry when multiple
    locks are held simultaneously.

    Writes to ScheduleRegistry that affect template references MUST
    atomically update TemplateReferenceIndex under both locks acquired
    in order (ScheduleRegistry lock first, then TemplateReferenceIndex lock).

    Primary index: WindowKey → ScheduledEntry
    """
    _windows: dict[WindowKey, ScheduledEntry] = field(default_factory=dict)
    _lock:    threading.RLock                 = field(default_factory=threading.RLock)
    # LOCK ORDERING: position 2


@dataclass
class TemplateReferenceIndex:
    """Reverse index from template_id to committed Tier 1 window keys.

    Owner: Scheduler.
    SCHED-INDEX-001: Co-maintained atomically with ScheduleRegistry on every write.

    STATE COVERAGE (Modification 2):
    This index includes ALL ScheduledEntry records that reference a template_id,
    regardless of ScheduleWindowState. Both COMMITTED and BLOCKED entries are
    indexed. This is required because:
      - VAL-T1-004 (prevent template deletion while referenced) must fire
        even when the referencing window is BLOCKED. A BLOCKED window is a
        committed Tier 1 entry that still holds the reference; the template
        cannot be deleted until the operator explicitly removes or rebuilds
        that window.
      - Restricting the index to COMMITTED-only entries would create a window
        where a template appears safe to delete (because its only referencing
        window is BLOCKED) but the BLOCKED window still holds a dangling
        reference that will fail again on the next rebuild attempt.

    Invariant: a template_id present in this index has at least one
    ScheduledEntry (in any state) whose name == template_id.
    Absent from the index == zero references == safe to delete or rename.

    The list[WindowKey] per template_id is sorted by wall_start_ms ascending.
    The sorted order provides the "earliest affected window" for VAL-T1-004
    and VAL-T1-005 error messages.

    LOCK ORDERING: position 3 — must be acquired after TemplateRegistry
    and ScheduleRegistry, before PlaylogRegistry, when multiple locks held.

    Maintenance events (all atomic with the corresponding ScheduleRegistry write,
    both locks held in order):
      - New window committed (type == 'template')  → append WindowKey to list
      - Window rebuilt (template ref changed)       → remove old WindowKey, add new
      - Window explicitly removed by operator       → remove WindowKey from list
      - Template deleted (VAL-T1-004 passes)        → template_id absent from index
      - Template renamed (VAL-T1-005 passes)        → old key removed; new key added
      - Window transitions COMMITTED → BLOCKED       → WindowKey stays in index
      - Window rebuilt from BLOCKED (new commit)    → old WindowKey replaced with new
    """
    _index: dict[str, list[WindowKey]] = field(default_factory=dict)
    # key:   template_id
    # value: sorted (ascending wall_start_ms) list of WindowKeys for ALL
    #        ScheduledEntry records (any state) whose name == template_id
    _lock:  threading.RLock            = field(default_factory=threading.RLock)
    # LOCK ORDERING: position 3


# ─────────────────────────────────────────────────────────────────────────────
# L2 — Tier 2 (Playlog resolution)
#
# Owner:      ProgramDirector
# Written by: ProgramDirector (on Playlog horizon extension)
# Read by:    ChannelManager (for execution scheduling)
# Freeze:     WINDOW-LEVEL (Modification 4) — an ACTIVE PlaylogWindow may
#             not be discarded or rebuilt. The freeze boundary is the entire
#             PlaylogWindow, not individual segments within it. There is no
#             segment-level freeze tracking in the runtime model.
# Protected:  PlaylogRegistry._lock (see GLOBAL LOCK ORDERING: position 4)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResolvedSegment:
    """One template segment resolved to a concrete asset.

    Produced during Tier 2 resolution. Immutable once created.

    segment_index is the 0-based position in the source TemplateDef.segments.
    is_primary_content is True when segment_index == TemplateDef.primary_segment_index.
    duration_ms is provided by AssetCatalog at resolution time.
    """
    segment_index:      int
    asset_id:           str
    duration_ms:        int
    is_primary_content: bool


@dataclass(frozen=True)
class PlaylogEvent:
    """One complete iteration of a schedulable entry within its window.

    Produced during Tier 2 resolution. Immutable once created.
    segments preserves the source template's declared segment order.

    epg_title is the resolved EPG identity string for this event:
      - Taken from ScheduledEntry.epg_title if set (Tier 1 authority).
      - Derived from the primary content asset title if ScheduledEntry.epg_title
        is None (Tier 2 derivation via AssetCatalog).
    """
    iteration_index:   int
    segments:          tuple[ResolvedSegment, ...]
    primary_asset_id:  str    # asset_id where ResolvedSegment.is_primary_content
    epg_title:         str    # resolved EPG identity string
    total_duration_ms: int


@dataclass
class PlaylogWindow:
    """Tier 2 resolution output for one Tier 1 scheduled window.

    SOURCE IDENTITY (Modification 1):
    source_window_uuid records the ScheduledEntry.window_uuid of the commit
    that this PlaylogWindow was built from. ProgramDirector uses this to
    detect staleness: if ScheduledEntry.window_uuid has changed since this
    window was built (operator rebuilt the Tier 1 entry), this PlaylogWindow
    is stale and must be discarded before a new build begins.

    WINDOW-LEVEL FREEZE (Modification 4):
    The freeze boundary is the PlaylogWindow, not individual segments.
    When state == ACTIVE, the entire PlaylogWindow is frozen:
      - No rebuild, discard, or modification of this window is permitted.
      - ChannelManager is executing against the resolved events in this window.
      - The freeze lifts when state transitions to EXPIRED.
    There is no segment-level freeze tracking. Segment immutability within
    an ACTIVE window is enforced structurally: PlaylogEvent and ResolvedSegment
    are frozen=True dataclasses and cannot be mutated in-place.

    LIFECYCLE:
      PENDING  → built, not yet active; may be discarded and rebuilt freely
      ACTIVE   → window-level freeze; no rebuild until EXPIRED
      EXPIRED  → execution completed; retained for as-run lineage

    build_seed is stored for diagnostic traceability only. A new seed is
    drawn for each build session; this field has no effect on future builds.

    events is populated atomically by the builder before the PlaylogWindow
    is inserted into PlaylogRegistry (consumers never see a partially built window).
    """
    window_key:          WindowKey
    source_window_uuid:  str                # ScheduledEntry.window_uuid at build time
    events:              list[PlaylogEvent]
    build_seed:          int                # session seed (diagnostic only)
    built_at_ms:         int                # epoch ms when build completed
    state:               PlaylogWindowState = PlaylogWindowState.PENDING


@dataclass
class PlaylogBuildContext:
    """Transient resolution context for one Tier 2 horizon build session.

    Created at the start of a Tier 2 build for one window.
    Discarded after the build completes. Never stored in PlaylogRegistry.

    window_uuid is the ScheduledEntry.window_uuid of the entry being built.
    It is propagated into PlaylogWindow.source_window_uuid on build completion.

    seed is stable for this (window, build session) pair. Given identical
    inputs (TemplateDef, available assets, seed), resolution produces
    identical output within this session. A new seed is drawn per session.
    """
    window_key:    WindowKey
    window_uuid:   str   # copied from ScheduledEntry.window_uuid at build start
    seed:          int
    started_at_ms: int


@dataclass
class PlaylogRegistry:
    """Channel-scoped Tier 2 playlog window store.

    One instance per channel. Written by ProgramDirector.
    Read by ProgramDirector (lookahead) and ChannelManager (execution).

    WINDOW-LEVEL FREEZE (Modification 4):
    The _active_keys set tracks which WindowKeys are currently ACTIVE.
    Before any rebuild or discard of a PlaylogWindow, ProgramDirector MUST
    check _active_keys. A WindowKey present in _active_keys is frozen at
    the window level — no rebuild is permitted until ChannelManager
    transitions that window to EXPIRED and removes it from _active_keys.

    Invariant: at most one WindowKey is in _active_keys at any instant
    (per channel). This is enforced by ChannelManager at transition time.

    LOCK ORDERING: position 4 — innermost; must be acquired after all
    other runtime locks when multiple locks are held simultaneously.

    Primary index:          WindowKey → PlaylogWindow
    Active freeze sentinel: _active_keys (set[WindowKey])
    """
    _windows:     dict[WindowKey, PlaylogWindow] = field(default_factory=dict)
    _active_keys: set[WindowKey]                 = field(default_factory=set)
    _lock:        threading.RLock                = field(default_factory=threading.RLock)
    # LOCK ORDERING: position 4 (innermost)


# ─────────────────────────────────────────────────────────────────────────────
# L3 — Active window tracking
#
# Owner:      ChannelManager
# One instance per channel.
# Transitions:
#   None → ACTIVE   on first viewer arrival or scheduled activation time
#   ACTIVE → EXPIRED on window wall_end_ms reached or last viewer departure
#
# Consistency invariant: active_window_key is non-None if and only if
# PlaylogRegistry._active_keys contains that WindowKey and the corresponding
# PlaylogWindow.state == ACTIVE. These three records change together under
# PlaylogRegistry._lock (LOCK ORDERING position 4).
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChannelActiveState:
    """Per-channel record of the currently executing playlog window.

    WINDOW-LEVEL FREEZE (Modification 4):
    active_window_key references the PlaylogWindow that is currently frozen
    (state == ACTIVE in PlaylogRegistry). Freeze is at the window level:
    the entire PlaylogWindow identified by active_window_key is immutable
    for the duration of execution. There is no sub-window or segment-level
    freeze concept in the runtime model.

    When active_window_key is None, no window is executing (channel is dark
    or between windows — filler system applies at channel level).

    activated_at_ms and expires_at_ms are used by ChannelManager to schedule
    the ACTIVE → EXPIRED transition via the Clock interface.
    expires_at_ms == active_window_key.wall_end_ms (plus any bleed extension).
    """
    channel_id:         str
    active_window_key:  WindowKey | None = None
    activated_at_ms:    int | None       = None
    expires_at_ms:      int | None       = None


# ─────────────────────────────────────────────────────────────────────────────
# L4 — Channel coordinator
#
# One instance per channel. Aggregates all per-channel runtime state.
# Created by ChannelManager at channel registration time.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChannelRuntimeState:
    """Aggregates all in-memory runtime state for one channel.

    Ownership summary:
      template_registry    — Config loader writes; ProgramDirector reads live (L0)
      schedule_registry    — Scheduler writes; ProgramDirector/ChannelManager read (L1)
      template_ref_index   — Scheduler co-maintains with schedule_registry (L1)
      playlog_registry     — ProgramDirector writes; ChannelManager reads (L2)
      active_state         — ChannelManager writes; ProgramDirector reads (L3)

    External interface references are held here for injection into Tier 2
    build operations. These are read-only from the perspective of this struct.
    """
    channel_id: str

    # L0
    template_registry:   TemplateRegistry

    # L1
    schedule_registry:   ScheduleRegistry
    template_ref_index:  TemplateReferenceIndex   # SCHED-INDEX-001

    # L2
    playlog_registry:    PlaylogRegistry

    # L3
    active_state:        ChannelActiveState

    # External dependencies (injected; no implementation here)
    asset_catalog:       AssetCatalog        # for asset resolution + approval checks
    metadata_evaluator:  MetadataEvaluator   # for selection rule evaluation
    clock:               Clock               # for activation boundary decisions
