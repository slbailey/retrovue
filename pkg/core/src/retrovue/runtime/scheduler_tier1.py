# pkg/core/src/retrovue/runtime/scheduler_tier1.py
#
# Tier 1 schedule commitment authority.
#
# Owns:
#   ScheduleRegistry        — committed time windows and entry references
#   TemplateReferenceIndex  — reverse index template_id → list[WindowKey]
#
# Lock ordering respected by this module (global; never violated):
#   TemplateRegistry._lock       (position 1)
#   ScheduleRegistry._lock       (position 2)
#   TemplateReferenceIndex._lock (position 3)
#
# PlaylogRegistry._lock (position 4) is NEVER acquired here.

from __future__ import annotations

import uuid
from bisect import bisect_left, insort
from dataclasses import dataclass
from typing import Optional

from retrovue.runtime.template_runtime import (
    ChannelRuntimeState,
    ScheduledEntry,
    ScheduleWindowState,
    TemplateDef,
    WindowKey,
)


# ─────────────────────────────────────────────────────────────────────────────
# Public error type
# ─────────────────────────────────────────────────────────────────────────────

class SchedulerError(Exception):
    """Raised when a Tier 1 Scheduler operation violates a documented contract rule.

    code    — machine-readable validation ID (e.g. "VAL-T1-004")
    message — human-readable description including affected IDs and earliest window
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ─────────────────────────────────────────────────────────────────────────────
# Input type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScheduleEntrySpec:
    """A pre-parsed schedule entry with wall-clock bounds in epoch ms.

    HH:MM parsing, timezone resolution, and midnight-crossing adjustment are
    performed by the caller upstream of Tier1Scheduler.  By the time this
    object is passed to build_horizon, all time values are absolute UTC
    epoch milliseconds and wall_end_ms > wall_start_ms is guaranteed.

    Field constraints (enforced by caller, not by Tier1Scheduler):
      type == "template"  →  name is set, asset_id is None, mode is None
      type == "pool"      →  name is set, asset_id is None, mode may be set
      type == "asset"     →  name is None, asset_id is set, mode is None
    """

    type: str            # "template" | "pool" | "asset"
    wall_start_ms: int   # epoch ms, UTC
    wall_end_ms: int     # epoch ms, UTC; invariant: wall_end_ms > wall_start_ms

    name: str | None = None       # template_id or pool_id
    asset_id: str | None = None   # direct asset reference (type == "asset" only)
    epg_title: str | None = None  # operator-assigned EPG title; None → Tier 2 derivation
    allow_bleed: bool = False
    mode: str | None = None       # selection strategy (type == "pool" only)


# ─────────────────────────────────────────────────────────────────────────────
# Internal index helpers
#
# Precondition for both: caller holds ScheduleRegistry._lock (2) and
# TemplateReferenceIndex._lock (3) simultaneously.
# ─────────────────────────────────────────────────────────────────────────────

def _index_insert(
    index_obj: object,   # TemplateReferenceIndex
    template_id: str,
    window_key: WindowKey,
) -> None:
    """Insert window_key into the sorted list for template_id.

    Maintains ascending wall_start_ms order via insort.
    WindowKey.__lt__ sorts by (channel_id, wall_start_ms).
    """
    idx = index_obj._index  # type: ignore[attr-defined]
    if template_id not in idx:
        idx[template_id] = []
    insort(idx[template_id], window_key)


def _index_remove(
    index_obj: object,   # TemplateReferenceIndex
    template_id: str,
    window_key: WindowKey,
) -> None:
    """Remove window_key from the list for template_id.

    No-op if template_id or window_key is already absent (idempotent).
    Removes the template_id key entirely when the list becomes empty.
    """
    idx = index_obj._index  # type: ignore[attr-defined]
    keys = idx.get(template_id)
    if keys is None:
        return
    try:
        keys.remove(window_key)
    except ValueError:
        return
    if not keys:
        del idx[template_id]


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 Scheduler
# ─────────────────────────────────────────────────────────────────────────────

class Tier1Scheduler:
    """Owns Tier 1 schedule commitments and TemplateReferenceIndex maintenance.

    One instance per channel.  Caller supplies the ChannelRuntimeState
    aggregating all per-channel runtime structures.

    LOCK ORDERING:  this class acquires locks only in global order:
        TemplateRegistry(1) → ScheduleRegistry(2) → TemplateReferenceIndex(3)
    PlaylogRegistry(4) is never acquired.
    """

    def __init__(self, channel_state: ChannelRuntimeState) -> None:
        self._state = channel_state

    # ── Build ─────────────────────────────────────────────────────────────────

    def build_horizon(
        self,
        entries: list[ScheduleEntrySpec],
        known_pools: set[str] | None = None,
        known_asset_ids: set[str] | None = None,
    ) -> list[WindowKey]:
        """Commit new schedule windows for the provided entries.

        Additive: entries whose WindowKey already exists in ScheduleRegistry
        are silently skipped.  Does not overwrite COMMITTED or BLOCKED windows;
        explicit rebuild_window is required for those.

        Validates entry references at commit time:
          VAL-T1-001: type == "template" and name absent from TemplateRegistry.
          VAL-T1-002: type == "pool" and name not in known_pools (if provided).
          VAL-T1-003: type == "asset" and asset_id not in known_asset_ids (if provided).

        Reference validation runs before any lock is acquired.  A validation
        failure raises immediately; no partial commits occur.

        Acquires (for the commit phase):
            ScheduleRegistry(2) → TemplateReferenceIndex(3)

        Returns the list of WindowKeys actually committed (skipped keys excluded).
        """
        s = self._state

        # ── Phase 1: Validate references and construct entries (no locks) ─────

        # VAL-T1-001: snapshot the template key set under TemplateRegistry lock,
        # then release immediately.  We do not hold the lock during commit; the
        # contract says Tier 1 does not snapshot templates, but checking existence
        # at build time is a point-in-time guard, not a persistent copy.
        with s.template_registry._lock:
            known_templates: frozenset[str] = frozenset(
                s.template_registry._templates.keys()
            )

        staged: list[ScheduledEntry] = []

        for spec in entries:
            # Reference validation
            if spec.type == "template":
                if spec.name not in known_templates:
                    raise SchedulerError(
                        "VAL-T1-001",
                        f"template '{spec.name}' not found in TemplateRegistry; "
                        f"cannot commit window "
                        f"[{spec.wall_start_ms}, {spec.wall_end_ms}]",
                    )
            elif spec.type == "pool":
                if known_pools is not None and spec.name not in known_pools:
                    raise SchedulerError(
                        "VAL-T1-002",
                        f"pool '{spec.name}' not found in known_pools; "
                        f"cannot commit window "
                        f"[{spec.wall_start_ms}, {spec.wall_end_ms}]",
                    )
            elif spec.type == "asset":
                if known_asset_ids is not None and spec.asset_id not in known_asset_ids:
                    raise SchedulerError(
                        "VAL-T1-003",
                        f"asset_id '{spec.asset_id}' not found in known_asset_ids; "
                        f"cannot commit window "
                        f"[{spec.wall_start_ms}, {spec.wall_end_ms}]",
                    )

            key = WindowKey(
                channel_id=s.channel_id,
                wall_start_ms=spec.wall_start_ms,
                wall_end_ms=spec.wall_end_ms,
            )
            entry = ScheduledEntry(
                window_uuid=str(uuid.uuid4()),
                window_key=key,
                type=spec.type,
                name=spec.name,
                asset_id=spec.asset_id,
                epg_title=spec.epg_title,
                allow_bleed=spec.allow_bleed,
                mode=spec.mode,
                committed_at_ms=s.clock.now_ms(),
            )
            staged.append(entry)

        # ── Phase 2: Atomic commit ────────────────────────────────────────────
        # Lock order: ScheduleRegistry(2) → TemplateReferenceIndex(3)

        committed_keys: list[WindowKey] = []

        with s.schedule_registry._lock:
            with s.template_ref_index._lock:
                for entry in staged:
                    if entry.window_key in s.schedule_registry._windows:
                        continue  # additive: skip existing keys

                    s.schedule_registry._windows[entry.window_key] = entry

                    if entry.type == "template":
                        _index_insert(s.template_ref_index, entry.name, entry.window_key)

                    committed_keys.append(entry.window_key)

        return committed_keys

    # ── Rebuild ───────────────────────────────────────────────────────────────

    def rebuild_window(
        self,
        window_key: WindowKey,
        replacement: ScheduleEntrySpec,
    ) -> WindowKey:
        """Replace an existing Tier 1 window with a new commit.

        Issues a new window_uuid (UUID4).  Resets state to COMMITTED and
        clears all blocked_* fields, regardless of the previous entry's state.

        TemplateReferenceIndex is updated atomically:
          - Removes the old WindowKey from _index[old_name] if old type was "template".
          - Inserts the new WindowKey into _index[new_name] if new type is "template".

        Acquires: ScheduleRegistry(2) → TemplateReferenceIndex(3)

        Returns the WindowKey of the rebuilt window (same as input).
        """
        s = self._state

        new_entry = ScheduledEntry(
            window_uuid=str(uuid.uuid4()),
            window_key=window_key,
            type=replacement.type,
            name=replacement.name,
            asset_id=replacement.asset_id,
            epg_title=replacement.epg_title,
            allow_bleed=replacement.allow_bleed,
            mode=replacement.mode,
            committed_at_ms=s.clock.now_ms(),
            # state defaults to COMMITTED; blocked_* fields default to None
        )

        with s.schedule_registry._lock:
            with s.template_ref_index._lock:
                old_entry = s.schedule_registry._windows.get(window_key)

                if old_entry is not None and old_entry.type == "template":
                    _index_remove(s.template_ref_index, old_entry.name, old_entry.window_key)

                s.schedule_registry._windows[window_key] = new_entry

                if new_entry.type == "template":
                    _index_insert(s.template_ref_index, new_entry.name, new_entry.window_key)

        return window_key

    # ── Template mutation enforcement ─────────────────────────────────────────

    def delete_template(self, template_id: str) -> None:
        """Delete a template definition from TemplateRegistry.

        Acquires: TemplateRegistry(1) → ScheduleRegistry(2) → TemplateReferenceIndex(3)

        The check (zero references) and the deletion are atomic under all three
        locks to close the race between a concurrent build_horizon that has
        updated ScheduleRegistry but not yet updated TemplateReferenceIndex.

        Raises:
            SchedulerError("VAL-T1-004"): TemplateReferenceIndex contains any
                WindowKey for template_id (any ScheduleWindowState).
        """
        s = self._state

        with s.template_registry._lock:
            with s.schedule_registry._lock:
                with s.template_ref_index._lock:
                    referenced = s.template_ref_index._index.get(template_id, [])

                    if referenced:
                        earliest = referenced[0]  # sorted ascending; [0] is earliest
                        earliest_entry = s.schedule_registry._windows.get(earliest)
                        state_str = (
                            earliest_entry.state.value
                            if earliest_entry is not None
                            else "unknown"
                        )
                        raise SchedulerError(
                            "VAL-T1-004",
                            f"cannot delete template '{template_id}': "
                            f"referenced by {len(referenced)} window(s); "
                            f"earliest: channel={earliest.channel_id} "
                            f"start={earliest.wall_start_ms} "
                            f"(state={state_str})",
                        )

                    if template_id not in s.template_registry._templates:
                        raise SchedulerError(
                            "VAL-T1-004",
                            f"template '{template_id}' not found in TemplateRegistry",
                        )

                    del s.template_registry._templates[template_id]

    def rename_template(self, old_id: str, new_id: str) -> None:
        """Rename a template definition in TemplateRegistry.

        Acquires: TemplateRegistry(1) → ScheduleRegistry(2) → TemplateReferenceIndex(3)

        Preserves segments and primary_segment_index from the old TemplateDef.
        No partial rename: the operation is atomic or not performed at all.

        Raises:
            SchedulerError("VAL-T1-005"): TemplateReferenceIndex contains any
                WindowKey for old_id (any ScheduleWindowState).
        """
        s = self._state

        with s.template_registry._lock:
            with s.schedule_registry._lock:
                with s.template_ref_index._lock:
                    referenced = s.template_ref_index._index.get(old_id, [])

                    if referenced:
                        earliest = referenced[0]
                        earliest_entry = s.schedule_registry._windows.get(earliest)
                        state_str = (
                            earliest_entry.state.value
                            if earliest_entry is not None
                            else "unknown"
                        )
                        raise SchedulerError(
                            "VAL-T1-005",
                            f"cannot rename template '{old_id}' → '{new_id}': "
                            f"referenced by {len(referenced)} window(s); "
                            f"earliest: channel={earliest.channel_id} "
                            f"start={earliest.wall_start_ms} "
                            f"(state={state_str})",
                        )

                    old_def = s.template_registry._templates.get(old_id)
                    if old_def is None:
                        raise SchedulerError(
                            "VAL-T1-005",
                            f"template '{old_id}' not found in TemplateRegistry",
                        )

                    if new_id in s.template_registry._templates:
                        raise SchedulerError(
                            "VAL-T1-005",
                            f"template '{new_id}' already exists in TemplateRegistry",
                        )

                    new_def = TemplateDef(
                        id=old_def.id.__class__(new_id),
                        segments=old_def.segments,
                        primary_segment_index=old_def.primary_segment_index,
                    )

                    del s.template_registry._templates[old_id]
                    s.template_registry._templates[new_id] = new_def
                    # TemplateReferenceIndex: old_id had zero references (passed
                    # check above); new_id is not yet referenced by any entry.
                    # No index update required.
