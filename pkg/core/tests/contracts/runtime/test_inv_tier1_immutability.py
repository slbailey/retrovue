# pkg/core/tests/contracts/runtime/test_inv_tier1_immutability.py
#
# Contract: TIER1-IMMUTABILITY-001
#
# After commit, a ScheduledEntry's fields are immutable with exactly two
# permitted exceptions:
#   - state                (COMMITTED → BLOCKED, written by ProgramDirector)
#   - blocked_reason_code  (populated atomically with state transition)
#   - blocked_at_ms        (populated atomically with state transition)
#   - blocked_details      (populated atomically with state transition)
#
# The Scheduler never mutates a committed entry in place.  Rebuild discards
# the old ScheduledEntry object entirely and inserts a new one with a fresh
# window_uuid.  There is no implicit rebuild path; only explicit rebuild_window
# can replace a committed window.
#
# ── Expected failure mode ────────────────────────────────────────────────────
# All tests in this file FAIL (NotImplementedError) until Tier1Scheduler
# methods are implemented.  That failure is correct and expected.

from __future__ import annotations

import pytest

from retrovue.runtime.template_runtime import (
    ChannelActiveState,
    ChannelRuntimeState,
    PlaylogRegistry,
    ScheduleRegistry,
    ScheduleWindowState,
    SegmentSource,
    TemplateDef,
    TemplateReferenceIndex,
    TemplateRegistry,
    TemplateSegment,
    WindowKey,
)
from retrovue.runtime.scheduler_tier1 import (
    ScheduleEntrySpec,
    Tier1Scheduler,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

CHANNEL_ID = "ch-immut-test"
BASE_MS = 1_700_000_000_000


def _T(offset_s: int) -> int:
    return BASE_MS + offset_s * 1_000


class _FakeClock:
    def now_ms(self) -> int:
        return BASE_MS


class _FakeAssetCatalog:
    def get_asset_duration_ms(self, asset_id: str) -> int | None:
        return None

    def is_approved(self, asset_id: str) -> bool:
        return False


class _FakeMetadataEvaluator:
    def filter_candidates(
        self,
        candidate_asset_ids: list[str],
        rules: object,
        source_name: str,
    ) -> list[str]:
        return list(candidate_asset_ids)


def _make_channel_state() -> ChannelRuntimeState:
    return ChannelRuntimeState(
        channel_id=CHANNEL_ID,
        template_registry=TemplateRegistry(),
        schedule_registry=ScheduleRegistry(),
        template_ref_index=TemplateReferenceIndex(),
        playlog_registry=PlaylogRegistry(),
        active_state=ChannelActiveState(channel_id=CHANNEL_ID),
        asset_catalog=_FakeAssetCatalog(),
        metadata_evaluator=_FakeMetadataEvaluator(),
        clock=_FakeClock(),
    )


def _add_template(state: ChannelRuntimeState, template_id: str) -> TemplateDef:
    tdef = TemplateDef(
        id=template_id,
        segments=(
            TemplateSegment(
                source=SegmentSource(type="pool", name="pool_a"),
                selection=(),
                mode="random",
            ),
        ),
        primary_segment_index=0,
    )
    with state.template_registry._lock:
        state.template_registry._templates[template_id] = tdef
    return tdef


def _spec(template_id: str, start_offset_s: int = 0, duration_s: int = 3_600) -> ScheduleEntrySpec:
    return ScheduleEntrySpec(
        type="template",
        name=template_id,
        wall_start_ms=_T(start_offset_s),
        wall_end_ms=_T(start_offset_s + duration_s),
        epg_title="Test Show",
        allow_bleed=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

# Tier: 1 | Structural invariant
def test_non_state_fields_unchanged_after_additive_build():
    """Non-state fields of a committed ScheduledEntry are not modified by
    a subsequent build_horizon call that encounters the same WindowKey.

    build_horizon is additive: the second call must skip the existing entry
    and leave the original object intact.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    spec = _spec("tmpl_a")
    committed = scheduler.build_horizon([spec])
    key = committed[0]
    entry = state.schedule_registry._windows[key]

    saved = {
        "window_uuid":     entry.window_uuid,
        "name":            entry.name,
        "type":            entry.type,
        "epg_title":       entry.epg_title,
        "allow_bleed":     entry.allow_bleed,
        "committed_at_ms": entry.committed_at_ms,
    }

    # Second additive call — must be a no-op for this key
    scheduler.build_horizon([spec])

    still = state.schedule_registry._windows[key]
    assert still is entry, "build_horizon replaced the entry object; must skip existing keys"
    assert still.window_uuid     == saved["window_uuid"]
    assert still.name            == saved["name"]
    assert still.type            == saved["type"]
    assert still.epg_title       == saved["epg_title"]
    assert still.allow_bleed     == saved["allow_bleed"]
    assert still.committed_at_ms == saved["committed_at_ms"]


# Tier: 1 | Structural invariant
def test_rebuild_issues_new_window_uuid():
    """rebuild_window creates a replacement entry with a different window_uuid.

    Tier 2 staleness detection compares PlaylogWindow.source_window_uuid
    against ScheduledEntry.window_uuid.  If rebuild reuses the old uuid,
    ProgramDirector cannot detect that the Tier 1 entry has changed.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    spec = _spec("tmpl_a")
    committed = scheduler.build_horizon([spec])
    key = committed[0]
    original_uuid = state.schedule_registry._windows[key].window_uuid

    scheduler.rebuild_window(key, spec)

    new_entry = state.schedule_registry._windows[key]
    assert new_entry.window_uuid != original_uuid, (
        "rebuild_window must issue a new window_uuid; "
        "reusing the old uuid breaks Tier 2 staleness detection"
    )


# Tier: 1 | Structural invariant
def test_rebuild_replaces_entry_object_not_mutates():
    """After rebuild_window, the new entry in ScheduleRegistry is a different
    object from the one that was there before rebuild.

    The Scheduler never mutates committed entries; it replaces them.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    spec = _spec("tmpl_a")
    committed = scheduler.build_horizon([spec])
    key = committed[0]
    old_entry = state.schedule_registry._windows[key]

    scheduler.rebuild_window(key, spec)

    new_entry = state.schedule_registry._windows[key]
    assert new_entry is not old_entry, (
        "rebuild_window must create a new ScheduledEntry object, not mutate the existing one"
    )


# Tier: 1 | Structural invariant
def test_rebuild_old_entry_unreachable_via_registry():
    """After rebuild_window, the old ScheduledEntry object is no longer
    accessible through ScheduleRegistry for the same WindowKey.

    There is no secondary index that keeps the old entry alive.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    spec = _spec("tmpl_a")
    committed = scheduler.build_horizon([spec])
    key = committed[0]
    old_id = id(state.schedule_registry._windows[key])

    scheduler.rebuild_window(key, spec)

    current_entry = state.schedule_registry._windows[key]
    assert id(current_entry) != old_id, (
        "old ScheduledEntry must not be the object at the same WindowKey after rebuild"
    )


# Tier: 1 | Structural invariant
def test_rebuild_blocked_window_resets_all_blocked_fields():
    """rebuild_window on a BLOCKED entry produces a COMMITTED entry with
    state == COMMITTED and all blocked_* fields set to None.

    rebuild_window is the only path to clear BLOCKED state from a window.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    spec = _spec("tmpl_a")
    committed = scheduler.build_horizon([spec])
    key = committed[0]

    # Simulate ProgramDirector BLOCKED transition
    with state.schedule_registry._lock:
        entry = state.schedule_registry._windows[key]
        entry.state               = ScheduleWindowState.BLOCKED
        entry.blocked_reason_code = "VAL-T2-001"
        entry.blocked_at_ms       = BASE_MS + 500
        entry.blocked_details     = "template absent at Tier 2 resolution time"

    scheduler.rebuild_window(key, spec)

    rebuilt = state.schedule_registry._windows[key]
    assert rebuilt.state               == ScheduleWindowState.COMMITTED, (
        "rebuilt entry must have state COMMITTED"
    )
    assert rebuilt.blocked_reason_code is None, (
        "blocked_reason_code must be cleared on rebuild"
    )
    assert rebuilt.blocked_at_ms is None, (
        "blocked_at_ms must be cleared on rebuild"
    )
    assert rebuilt.blocked_details is None, (
        "blocked_details must be cleared on rebuild"
    )


# Tier: 1 | Structural invariant
def test_window_uuid_values_are_unique_across_distinct_commits():
    """Each call to build_horizon for a distinct WindowKey produces a unique
    window_uuid.  UUIDs are never reused within a channel's commit history.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    entries = [
        _spec("tmpl_a", start_offset_s=0),
        _spec("tmpl_a", start_offset_s=3_600),
        _spec("tmpl_a", start_offset_s=7_200),
    ]
    committed_keys = scheduler.build_horizon(entries)

    uuids = [
        state.schedule_registry._windows[k].window_uuid
        for k in committed_keys
    ]
    assert len(uuids) == len(set(uuids)), (
        f"Duplicate window_uuid values detected: {uuids}"
    )
