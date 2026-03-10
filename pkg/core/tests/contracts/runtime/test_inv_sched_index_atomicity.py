# pkg/core/tests/contracts/runtime/test_inv_sched_index_atomicity.py
#
# Contract: SCHED-INDEX-001
#
# TemplateReferenceIndex is co-maintained atomically with ScheduleRegistry.
#
# Every ScheduledEntry of type "template" — regardless of its
# ScheduleWindowState (COMMITTED or BLOCKED) — has a corresponding WindowKey
# in TemplateReferenceIndex._index[template_id].
#
# Absence from the index is equivalent to zero references and is the gate
# condition for template deletion (VAL-T1-004) and rename (VAL-T1-005).
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
# Test fixtures and helpers
# ─────────────────────────────────────────────────────────────────────────────

CHANNEL_ID = "ch-sched-index-test"
BASE_MS = 1_700_000_000_000  # fixed epoch base; all windows are offsets from here


def _T(offset_s: int) -> int:
    """Convert a seconds offset into an absolute epoch ms."""
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
    """Register a minimal TemplateDef in TemplateRegistry."""
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


def _template_entry(
    template_id: str,
    start_offset_s: int,
    duration_s: int = 3_600,
) -> ScheduleEntrySpec:
    return ScheduleEntrySpec(
        type="template",
        name=template_id,
        wall_start_ms=_T(start_offset_s),
        wall_end_ms=_T(start_offset_s + duration_s),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

# Tier: 2 | Scheduling logic invariant
def test_commit_template_window_populates_index():
    """After build_horizon for a type:template entry, its WindowKey appears
    in TemplateReferenceIndex._index[template_id].
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    committed = scheduler.build_horizon([_template_entry("tmpl_a", 0)])

    assert len(committed) == 1
    key = committed[0]
    assert "tmpl_a" in state.template_ref_index._index, (
        "template_id absent from index after commit"
    )
    assert key in state.template_ref_index._index["tmpl_a"], (
        "WindowKey absent from index after commit"
    )


# Tier: 2 | Scheduling logic invariant
def test_rebuild_to_different_template_swaps_index_entry():
    """Rebuilding a window to reference a different template:
    - old template_id's WindowKey is removed from the index
    - new template_id's WindowKey is inserted into the index
    Both transitions must be visible after rebuild_window returns.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    _add_template(state, "tmpl_b")
    scheduler = Tier1Scheduler(state)

    committed = scheduler.build_horizon([_template_entry("tmpl_a", 0)])
    key = committed[0]

    # Pre-condition: key indexed under tmpl_a
    assert key in state.template_ref_index._index.get("tmpl_a", [])

    scheduler.rebuild_window(
        key,
        ScheduleEntrySpec(
            type="template",
            name="tmpl_b",
            wall_start_ms=_T(0),
            wall_end_ms=_T(3_600),
        ),
    )

    # Post-conditions: old ref gone, new ref present
    assert key not in state.template_ref_index._index.get("tmpl_a", []), (
        "old WindowKey must be removed from tmpl_a index after rebuild"
    )
    assert key in state.template_ref_index._index.get("tmpl_b", []), (
        "new WindowKey must be added to tmpl_b index after rebuild"
    )


# Tier: 2 | Scheduling logic invariant
def test_committed_to_blocked_transition_preserves_index_entry():
    """When ProgramDirector marks a window BLOCKED (simulating VAL-T2-001),
    the WindowKey must remain in TemplateReferenceIndex.

    SCHED-INDEX-001 requires ALL states (COMMITTED and BLOCKED) to be indexed.
    A BLOCKED window still holds a live template reference; allowing deletion
    of the template would leave a dangling reference on the next rebuild attempt.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    committed = scheduler.build_horizon([_template_entry("tmpl_a", 0)])
    key = committed[0]

    # Simulate ProgramDirector writing BLOCKED state (as _mark_blocked would)
    with state.schedule_registry._lock:
        entry = state.schedule_registry._windows[key]
        entry.state = ScheduleWindowState.BLOCKED
        entry.blocked_reason_code = "VAL-T2-001"
        entry.blocked_at_ms = BASE_MS + 1_000
        entry.blocked_details = "template absent at Tier 2 resolution time"

    # Index must be unchanged after the BLOCKED transition
    assert key in state.template_ref_index._index.get("tmpl_a", []), (
        "WindowKey must stay in index after COMMITTED → BLOCKED transition; "
        "SCHED-INDEX-001 covers all states"
    )


# Tier: 2 | Scheduling logic invariant
def test_rebuild_to_pool_type_removes_from_index():
    """Rebuilding a template-type window to a pool-type entry removes
    the WindowKey from TemplateReferenceIndex.  Pool entries are not tracked.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    committed = scheduler.build_horizon([_template_entry("tmpl_a", 0)])
    key = committed[0]

    scheduler.rebuild_window(
        key,
        ScheduleEntrySpec(
            type="pool",
            name="pool_a",
            wall_start_ms=_T(0),
            wall_end_ms=_T(3_600),
        ),
    )

    remaining = state.template_ref_index._index.get("tmpl_a", [])
    assert key not in remaining, (
        "WindowKey must be removed from index when window is rebuilt to pool type"
    )


# Tier: 2 | Scheduling logic invariant
def test_index_list_sorted_ascending_by_wall_start_ms():
    """The WindowKey list per template_id in the index is sorted ascending
    by wall_start_ms.  Sorted order is the contract for 'earliest affected
    window' reporting in VAL-T1-004 / VAL-T1-005 errors.
    """
    state = _make_channel_state()
    _add_template(state, "tmpl_a")
    scheduler = Tier1Scheduler(state)

    # Commit three windows in intentionally non-ascending order
    entries = [
        _template_entry("tmpl_a", start_offset_s=7_200),   # 3rd chronologically
        _template_entry("tmpl_a", start_offset_s=0),        # 1st chronologically
        _template_entry("tmpl_a", start_offset_s=3_600),    # 2nd chronologically
    ]
    scheduler.build_horizon(entries)

    keys = state.template_ref_index._index["tmpl_a"]
    start_times = [k.wall_start_ms for k in keys]
    assert start_times == sorted(start_times), (
        f"Index not sorted by wall_start_ms; got {start_times}"
    )
    assert start_times[0] == _T(0), (
        "First index entry must be the chronologically earliest window"
    )
