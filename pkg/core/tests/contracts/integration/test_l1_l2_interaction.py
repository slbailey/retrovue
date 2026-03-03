# pkg/core/tests/contracts/integration/test_l1_l2_interaction.py
#
# Integration contract tests: L1 (Tier 1 Scheduler) ↔ L2 (Tier 2 Director).
#
# Uses real runtime objects throughout.  No mocking of core logic.
#
# Invariants under test:
#   TIER1-IMMUTABILITY-001  — ScheduledEntry non-state fields frozen after commit
#   SCHED-INDEX-001         — TemplateReferenceIndex covers all states (COMMITTED + BLOCKED)
#   ACTIVE-FREEZE-001       — ACTIVE PlaylogWindow is never rebuilt or discarded
#   STALE-UUID-001          — Stale PlaylogWindows (source_uuid ≠ entry.uuid) are
#                             detected and replaced on next extend_horizon
#   SEED-SESSION-001        — Each build session draws a new seed; no-rebuild reuses
#                             the existing window and its seed unchanged
#
# ── Local Tier 2 spine ───────────────────────────────────────────────────────
#
# No production Tier 2 spine module exists yet.  _Tier2Director below is a
# minimal but complete real implementation of the Tier 2 resolution algorithm.
# It is intentionally part of this test module; the tests validate the
# interaction contract, not a stub.  When a production module is extracted,
# these tests will be updated to import from it.
#
# Algorithm implemented:
#   extend_horizon   — scan ScheduleRegistry; build/discard/skip PlaylogWindows
#   _decide_build_action — staleness check via source_window_uuid
#   _discard_stale_window — remove PENDING or EXPIRED (never ACTIVE)
#   _resolve_template_window — read TemplateDef live; fill window with events
#   _fill_template_window / _resolve_one_iteration — asset pick + event assembly
#   _mark_blocked    — atomic COMMITTED → BLOCKED transition on ScheduledEntry
#
# ── Expected result ──────────────────────────────────────────────────────────
# All 15 tests PASS when the Tier 1 implementation satisfies its contracts and
# the local _Tier2Director correctly enforces the Tier 2 algorithm.

from __future__ import annotations

import random
from dataclasses import dataclass, field

import pytest

from retrovue.runtime.template_runtime import (
    ChannelActiveState,
    ChannelRuntimeState,
    PlaylogEvent,
    PlaylogRegistry,
    PlaylogWindow,
    PlaylogWindowState,
    ResolvedSegment,
    ScheduleRegistry,
    ScheduledEntry,
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
    SchedulerError,
    Tier1Scheduler,
    _index_insert,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CHANNEL_ID        = "ch-l1-l2-integration"
BASE_MS           = 1_700_000_000_000   # fixed epoch base; all offsets from here
WINDOW_DURATION_S = 3_600               # 1 hour windows throughout
WINDOW_DURATION_MS = WINDOW_DURATION_S * 1_000

POOL_MAIN  = "pool_main"
POOL_EMPTY = "pool_empty"
ASSET_A    = "asset-a-001"
ASSET_B    = "asset-b-001"


def _T(offset_s: int) -> int:
    return BASE_MS + offset_s * 1_000


# ─────────────────────────────────────────────────────────────────────────────
# Fake infrastructure
# ─────────────────────────────────────────────────────────────────────────────

class _FakeClock:
    def __init__(self, now_ms: int = BASE_MS) -> None:
        self._now = now_ms

    def now_ms(self) -> int:
        return self._now

    def advance_to(self, ms: int) -> None:
        self._now = ms


class _FakeAssetCatalog:
    """Extends the AssetCatalog Protocol with pool-asset mapping for tests.

    list_pool_assets is a test-only extension beyond the Protocol; it is called
    only from _Tier2Director._pick_asset which is itself a test-local class.
    """

    def __init__(self) -> None:
        self._assets: dict[str, int]       = {}   # asset_id → duration_ms
        self._pools:  dict[str, list[str]] = {}   # pool_id  → list[asset_id]

    def add_asset(self, asset_id: str, duration_ms: int) -> None:
        self._assets[asset_id] = duration_ms

    def add_pool(self, pool_id: str, asset_ids: list[str]) -> None:
        self._pools[pool_id] = list(asset_ids)

    def get_asset_duration_ms(self, asset_id: str) -> int | None:
        return self._assets.get(asset_id)

    def is_approved(self, asset_id: str) -> bool:
        return asset_id in self._assets

    def list_pool_assets(self, pool_id: str) -> list[str]:
        return list(self._pools.get(pool_id, []))


class _FakeMetadataEvaluator:
    def filter_candidates(
        self,
        candidate_asset_ids: list[str],
        rules: object,
        source_name: str,
    ) -> list[str]:
        return list(candidate_asset_ids)


def _make_catalog() -> _FakeAssetCatalog:
    catalog = _FakeAssetCatalog()
    catalog.add_asset(ASSET_A, WINDOW_DURATION_MS)  # fills one window exactly
    catalog.add_asset(ASSET_B, WINDOW_DURATION_MS)
    catalog.add_pool(POOL_MAIN, [ASSET_A])
    # POOL_EMPTY: no add_pool call → list_pool_assets returns []
    return catalog


def _make_channel_state(
    catalog: _FakeAssetCatalog | None = None,
    clock: _FakeClock | None = None,
) -> ChannelRuntimeState:
    return ChannelRuntimeState(
        channel_id=CHANNEL_ID,
        template_registry=TemplateRegistry(),
        schedule_registry=ScheduleRegistry(),
        template_ref_index=TemplateReferenceIndex(),
        playlog_registry=PlaylogRegistry(),
        active_state=ChannelActiveState(channel_id=CHANNEL_ID),
        asset_catalog=catalog if catalog is not None else _make_catalog(),
        metadata_evaluator=_FakeMetadataEvaluator(),
        clock=clock if clock is not None else _FakeClock(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Schedule helpers
# ─────────────────────────────────────────────────────────────────────────────

def _add_template(
    state: ChannelRuntimeState,
    template_id: str,
    pool_id: str = POOL_MAIN,
) -> TemplateDef:
    tdef = TemplateDef(
        id=template_id,
        segments=(
            TemplateSegment(
                source=SegmentSource(type="pool", name=pool_id),
                selection=(),
                mode="random",
            ),
        ),
        primary_segment_index=0,
    )
    with state.template_registry._lock:
        state.template_registry._templates[template_id] = tdef
    return tdef


def _commit_one(
    scheduler: Tier1Scheduler,
    template_id: str,
    start_offset_s: int = 0,
    duration_s: int = WINDOW_DURATION_S,
) -> WindowKey:
    keys = scheduler.build_horizon([
        ScheduleEntrySpec(
            type="template",
            name=template_id,
            wall_start_ms=_T(start_offset_s),
            wall_end_ms=_T(start_offset_s + duration_s),
        )
    ])
    assert len(keys) == 1
    return keys[0]


def _template_spec(
    template_id: str,
    start_offset_s: int = 0,
    duration_s: int = WINDOW_DURATION_S,
) -> ScheduleEntrySpec:
    return ScheduleEntrySpec(
        type="template",
        name=template_id,
        wall_start_ms=_T(start_offset_s),
        wall_end_ms=_T(start_offset_s + duration_s),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ChannelManager simulation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _activate_window(state: ChannelRuntimeState, key: WindowKey) -> None:
    """Simulate ChannelManager PENDING → ACTIVE transition."""
    with state.playlog_registry._lock:
        pw = state.playlog_registry._windows[key]
        pw.state = PlaylogWindowState.ACTIVE
        state.playlog_registry._active_keys.add(key)
    state.active_state.active_window_key = key


def _expire_window(state: ChannelRuntimeState, key: WindowKey) -> None:
    """Simulate ChannelManager ACTIVE → EXPIRED transition."""
    with state.playlog_registry._lock:
        pw = state.playlog_registry._windows[key]
        pw.state = PlaylogWindowState.EXPIRED
        state.playlog_registry._active_keys.discard(key)
    state.active_state.active_window_key = None


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 spine — real minimal implementation
#
# _Tier2Director is a complete implementation of the Tier 2 resolution
# algorithm.  It is not a mock.  It maintains the same invariants that a
# production ProgramDirector must maintain:
#
#   - Staleness detection: PlaylogWindow.source_window_uuid vs
#     ScheduledEntry.window_uuid.  Mismatch → discard and rebuild.
#   - ACTIVE freeze: a window in _active_keys is never discarded or rebuilt.
#   - EXPIRED + stale: a stale expired window is replaced (the operator
#     rebuilt the Tier 1 entry; the old as-run record is orphaned and a
#     fresh PENDING window is produced for the upcoming slot).
#   - EXPIRED + current: retained as-is for lineage.
#   - BLOCKED: skipped entirely; no build attempted.
#   - _mark_blocked: atomic COMMITTED → BLOCKED under ScheduleRegistry lock;
#     only fires if the entry has not been rebuilt between build-start and
#     failure (window_uuid guard).
#
# Asset resolution is simplified for tests: _pick_asset calls
# catalog.list_pool_assets() (a test-extension beyond the Protocol) and
# returns the first approved asset.  No selection rules are evaluated.
# ─────────────────────────────────────────────────────────────────────────────

def _draw_session_seed() -> int:
    """Draw a fresh pseudo-random seed for one Tier 2 build session."""
    return random.getrandbits(62)


class _Tier2Director:
    """Minimal real Tier 2 spine for integration testing."""

    def __init__(self, state: ChannelRuntimeState) -> None:
        self._state = state

    # ── Public API ────────────────────────────────────────────────────────────

    def extend_horizon(self, now_ms: int, lookahead_end_ms: int) -> list[WindowKey]:
        """Build PlaylogWindows for all COMMITTED windows whose slot overlaps
        the half-open range (now_ms, lookahead_end_ms].

        Processes entries in ascending wall_start_ms order.  The ScheduleRegistry
        lock is held only for the initial snapshot; individual builds run unlocked.
        """
        s = self._state

        with s.schedule_registry._lock:
            entries = sorted(
                s.schedule_registry._windows.values(),
                key=lambda e: e.window_key.wall_start_ms,
            )

        built: list[WindowKey] = []
        for entry in entries:
            key = entry.window_key
            if key.wall_end_ms <= now_ms:
                continue
            if key.wall_start_ms > lookahead_end_ms:
                break
            if entry.state == ScheduleWindowState.BLOCKED:
                continue

            action = self._decide_build_action(entry)
            if action == "SKIP":
                continue
            if action == "DISCARD_AND_BUILD":
                self._discard_stale_window(key)

            if self._resolve_window(entry):
                built.append(key)

        return built

    # ── Decision ──────────────────────────────────────────────────────────────

    def _decide_build_action(self, entry: ScheduledEntry) -> str:
        s = self._state
        with s.playlog_registry._lock:
            existing = s.playlog_registry._windows.get(entry.window_key)

        if existing is None:
            return "BUILD_NEW"

        if existing.state == PlaylogWindowState.ACTIVE:
            # Freeze boundary: ACTIVE windows are never rebuilt regardless of
            # staleness.  The freeze lifts only when ChannelManager expires the
            # window (ACTIVE → EXPIRED).
            return "SKIP"

        stale = existing.source_window_uuid != entry.window_uuid

        if existing.state == PlaylogWindowState.EXPIRED:
            # Stale expired: operator rebuilt the Tier 1 entry; the old as-run
            # record is orphaned.  Produce a fresh PENDING window.
            # Current expired: retain for as-run lineage.
            return "DISCARD_AND_BUILD" if stale else "SKIP"

        # PENDING
        return "DISCARD_AND_BUILD" if stale else "SKIP"

    # ── Discard ───────────────────────────────────────────────────────────────

    def _discard_stale_window(self, window_key: WindowKey) -> None:
        """Remove a PENDING or EXPIRED PlaylogWindow.  Never removes ACTIVE."""
        s = self._state
        with s.playlog_registry._lock:
            existing = s.playlog_registry._windows.get(window_key)
            if existing is not None and existing.state != PlaylogWindowState.ACTIVE:
                del s.playlog_registry._windows[window_key]

    # ── Resolve ───────────────────────────────────────────────────────────────

    def _resolve_window(self, entry: ScheduledEntry) -> bool:
        if entry.type == "template":
            return self._resolve_template_window(entry)
        # pool and asset types: build a minimal placeholder window
        return self._resolve_direct_window(entry)

    def _resolve_template_window(self, entry: ScheduledEntry) -> bool:
        s = self._state

        # Read TemplateDef live — no snapshot; this is intentional.
        with s.template_registry._lock:
            tdef = s.template_registry._templates.get(entry.name)

        if tdef is None:
            # VAL-T2-001: template absent at Tier 2 resolution time.
            self._mark_blocked(
                entry,
                "VAL-T2-001",
                f"template '{entry.name}' not found in TemplateRegistry at Tier 2 resolution time",
            )
            return False

        seed    = _draw_session_seed()
        now_ms  = s.clock.now_ms()
        events  = self._fill_template_window(entry, tdef, seed)
        if events is None:
            return False  # _mark_blocked already called

        pw = PlaylogWindow(
            window_key=entry.window_key,
            source_window_uuid=entry.window_uuid,
            events=events,
            build_seed=seed,
            built_at_ms=now_ms,
        )
        with s.playlog_registry._lock:
            s.playlog_registry._windows[entry.window_key] = pw
        return True

    def _fill_template_window(
        self,
        entry: ScheduledEntry,
        tdef: TemplateDef,
        seed: int,
    ) -> list[PlaylogEvent] | None:
        window_duration_ms = entry.window_key.wall_end_ms - entry.window_key.wall_start_ms
        total_ms   = 0
        events     = []
        iteration  = 0

        while total_ms < window_duration_ms and iteration < 1_000:
            result = self._resolve_one_iteration(tdef)
            if result is None:
                # VAL-T2-008: no approved asset for a segment.
                self._mark_blocked(
                    entry,
                    "VAL-T2-008",
                    f"no approved assets available for template '{tdef.id}'",
                )
                return None

            segments, iter_duration_ms, primary_asset_id = result
            if iter_duration_ms == 0:
                break  # pathological; avoid infinite loop

            events.append(PlaylogEvent(
                iteration_index=iteration,
                segments=tuple(segments),
                primary_asset_id=primary_asset_id,
                epg_title=entry.epg_title or primary_asset_id,
                total_duration_ms=iter_duration_ms,
            ))
            total_ms  += iter_duration_ms
            iteration += 1

        return events

    def _resolve_one_iteration(
        self,
        tdef: TemplateDef,
    ) -> tuple[list[ResolvedSegment], int, str] | None:
        catalog         = self._state.asset_catalog
        resolved: list[ResolvedSegment] = []
        primary_asset   = ""
        iter_duration   = 0

        for seg_idx, segment in enumerate(tdef.segments):
            asset_id = self._pick_asset(segment)
            if asset_id is None:
                return None
            dur = catalog.get_asset_duration_ms(asset_id)
            if dur is None or dur == 0:
                return None

            is_primary = (seg_idx == tdef.primary_segment_index)
            resolved.append(ResolvedSegment(
                segment_index=seg_idx,
                asset_id=asset_id,
                duration_ms=dur,
                is_primary_content=is_primary,
            ))
            if is_primary:
                primary_asset  = asset_id
                iter_duration  = dur

        if iter_duration == 0:
            # Fallback: sum all segments when none is flagged primary.
            iter_duration = sum(rs.duration_ms for rs in resolved)

        return resolved, iter_duration, primary_asset

    def _pick_asset(self, segment: TemplateSegment) -> str | None:
        """Return the first approved asset for a segment's pool, or None."""
        catalog = self._state.asset_catalog
        pool_id = segment.source.name or ""
        # list_pool_assets is a test-extension on _FakeAssetCatalog
        candidates: list[str] = getattr(catalog, "list_pool_assets", lambda _: [])(pool_id)
        return next((cid for cid in candidates if catalog.is_approved(cid)), None)

    def _resolve_direct_window(self, entry: ScheduledEntry) -> bool:
        """Build a minimal PlaylogWindow for pool/asset-type entries."""
        s      = self._state
        seed   = _draw_session_seed()
        now_ms = s.clock.now_ms()
        pw = PlaylogWindow(
            window_key=entry.window_key,
            source_window_uuid=entry.window_uuid,
            events=[],
            build_seed=seed,
            built_at_ms=now_ms,
        )
        with s.playlog_registry._lock:
            s.playlog_registry._windows[entry.window_key] = pw
        return True

    # ── BLOCKED transition ────────────────────────────────────────────────────

    def _mark_blocked(
        self,
        entry: ScheduledEntry,
        code: str,
        details: str,
    ) -> None:
        """Atomic COMMITTED → BLOCKED transition on the ScheduledEntry.

        The window_uuid guard ensures that a concurrent rebuild_window between
        the start of extend_horizon and the resolution failure does not
        accidentally block the freshly committed entry.
        """
        s = self._state
        with s.schedule_registry._lock:
            live = s.schedule_registry._windows.get(entry.window_key)
            if live is not None and live.window_uuid == entry.window_uuid:
                live.state               = ScheduleWindowState.BLOCKED
                live.blocked_reason_code = code
                live.blocked_at_ms       = s.clock.now_ms()
                live.blocked_details     = details


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1: Rebuild while window is PENDING
# ─────────────────────────────────────────────────────────────────────────────

class TestRebuildWhilePending:
    """Staleness detected on PENDING PlaylogWindow → discard and rebuild."""

    def test_stale_pending_window_discarded_and_rebuilt(self):
        """After a Tier 1 rebuild, the next extend_horizon discards the stale
        PENDING PlaylogWindow and produces a new one carrying the new uuid."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key           = _commit_one(scheduler, "tmpl_a")
        original_uuid = state.schedule_registry._windows[key].window_uuid

        director.extend_horizon(BASE_MS, _T(7_200))

        first_pw = state.playlog_registry._windows[key]
        assert first_pw.state == PlaylogWindowState.PENDING
        assert first_pw.source_window_uuid == original_uuid
        first_seed = first_pw.build_seed

        # Tier 1 rebuild issues a new window_uuid.
        scheduler.rebuild_window(key, _template_spec("tmpl_a"))
        new_uuid = state.schedule_registry._windows[key].window_uuid
        assert new_uuid != original_uuid

        # Staleness detected → stale PENDING discarded → fresh window built.
        director.extend_horizon(BASE_MS, _T(7_200))

        second_pw = state.playlog_registry._windows[key]
        assert second_pw is not first_pw, (
            "stale PENDING PlaylogWindow must be replaced, not reused"
        )
        assert second_pw.source_window_uuid == new_uuid, (
            "new PlaylogWindow must carry the window_uuid from the Tier 1 rebuild"
        )
        assert second_pw.state == PlaylogWindowState.PENDING
        assert second_pw.build_seed != first_seed, (
            "new build session must draw a different seed"
        )

    def test_no_rebuild_when_uuid_current(self):
        """extend_horizon twice with no Tier 1 rebuild → same PlaylogWindow object."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))
        first_pw = state.playlog_registry._windows[key]

        director.extend_horizon(BASE_MS, _T(7_200))
        assert state.playlog_registry._windows[key] is first_pw, (
            "extend_horizon must not rebuild a current (non-stale) PENDING window"
        )

    def test_index_consistent_after_pending_rebuild(self):
        """TemplateReferenceIndex still contains the WindowKey under the same
        template_id after a rebuild-while-pending (same template referenced)."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))
        scheduler.rebuild_window(key, _template_spec("tmpl_a"))
        director.extend_horizon(BASE_MS, _T(7_200))

        assert key in state.template_ref_index._index.get("tmpl_a", []), (
            "WindowKey must remain in TemplateReferenceIndex after rebuild-while-pending"
        )

    def test_scheduled_entry_not_mutated_by_director(self):
        """extend_horizon must not replace or mutate ScheduledEntry objects
        (except for the permitted BLOCKED state transition fields)."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key          = _commit_one(scheduler, "tmpl_a")
        entry_before = state.schedule_registry._windows[key]
        uuid_before  = entry_before.window_uuid

        director.extend_horizon(BASE_MS, _T(7_200))

        entry_after = state.schedule_registry._windows[key]
        assert entry_after is entry_before, (
            "extend_horizon must not replace the ScheduledEntry object (TIER1-IMMUTABILITY-001)"
        )
        assert entry_after.window_uuid == uuid_before
        assert entry_after.state == ScheduleWindowState.COMMITTED


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2: Rebuild while window is ACTIVE
# ─────────────────────────────────────────────────────────────────────────────

class TestRebuildWhileActive:
    """ACTIVE window freeze boundary: operator rebuild is silently deferred until
    the window expires."""

    def test_active_window_not_rebuilt_during_extend(self):
        """extend_horizon skips a stale ACTIVE window — freeze boundary holds."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))

        first_pw             = state.playlog_registry._windows[key]
        original_source_uuid = first_pw.source_window_uuid

        _activate_window(state, key)

        # Operator rebuilds at Tier 1 while window is on-air.
        scheduler.rebuild_window(key, _template_spec("tmpl_a"))
        new_entry_uuid = state.schedule_registry._windows[key].window_uuid
        assert new_entry_uuid != original_source_uuid

        # extend_horizon must not touch the ACTIVE window.
        director.extend_horizon(BASE_MS, _T(7_200))

        still_pw = state.playlog_registry._windows[key]
        assert still_pw is first_pw, (
            "ACTIVE PlaylogWindow must not be replaced during extend_horizon "
            "(ACTIVE-FREEZE-001)"
        )
        assert still_pw.source_window_uuid == original_source_uuid, (
            "ACTIVE PlaylogWindow must retain its original source_window_uuid"
        )
        assert still_pw.state == PlaylogWindowState.ACTIVE

    def test_stale_rebuild_processed_after_expiry(self):
        """After the ACTIVE window expires, extend_horizon detects the pending
        Tier 1 rebuild (stale EXPIRED) and produces a fresh PENDING window."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key      = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))
        first_pw = state.playlog_registry._windows[key]

        _activate_window(state, key)

        # Rebuild while ACTIVE — freeze means this is not processed yet.
        scheduler.rebuild_window(key, _template_spec("tmpl_a"))
        new_uuid = state.schedule_registry._windows[key].window_uuid

        director.extend_horizon(BASE_MS, _T(7_200))
        assert state.playlog_registry._windows[key] is first_pw, (
            "freeze must hold: ACTIVE window not replaced"
        )

        # Window expires — freeze lifts.
        _expire_window(state, key)
        assert state.playlog_registry._windows[key].state == PlaylogWindowState.EXPIRED

        # Next extend_horizon: EXPIRED + stale → replace with fresh PENDING.
        director.extend_horizon(BASE_MS, _T(7_200))

        rebuilt_pw = state.playlog_registry._windows[key]
        assert rebuilt_pw is not first_pw, (
            "stale EXPIRED PlaylogWindow must be replaced on next extend_horizon"
        )
        assert rebuilt_pw.source_window_uuid == new_uuid, (
            "rebuilt window must carry the window_uuid from the Tier 1 rebuild"
        )
        assert rebuilt_pw.state == PlaylogWindowState.PENDING

    def test_expired_current_window_retained_for_lineage(self):
        """An EXPIRED PlaylogWindow whose source_uuid matches the current Tier 1
        entry is not replaced — it is retained for as-run lineage."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))
        _activate_window(state, key)
        _expire_window(state, key)

        expired_pw = state.playlog_registry._windows[key]
        assert expired_pw.state == PlaylogWindowState.EXPIRED

        # No Tier 1 rebuild — uuid still matches.
        director.extend_horizon(BASE_MS, _T(7_200))

        assert state.playlog_registry._windows[key] is expired_pw, (
            "current (non-stale) EXPIRED window must be retained for lineage"
        )

    def test_active_keys_cleared_after_expiry(self):
        """_active_keys and active_state.active_window_key are both cleared when
        ChannelManager expires the window."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))
        _activate_window(state, key)

        assert key in state.playlog_registry._active_keys
        assert state.active_state.active_window_key == key

        _expire_window(state, key)

        assert key not in state.playlog_registry._active_keys, (
            "_active_keys must not contain the WindowKey after expiry"
        )
        assert state.active_state.active_window_key is None


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3: Template deletion while window BLOCKED
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplateDeletionWhileBlocked:
    """SCHED-INDEX-001 guarantees BLOCKED windows stay in the index, blocking
    template deletion (VAL-T1-004) until the operator rebuilds."""

    def test_blocked_window_prevents_template_deletion(self):
        """extend_horizon marks a window BLOCKED when the template's pool has
        no approved assets.  delete_template is then rejected (VAL-T1-004)
        because SCHED-INDEX-001 still indexes the BLOCKED entry."""
        catalog = _make_catalog()
        # POOL_EMPTY has no assets; the Tier 2 build will fail.
        catalog.add_pool(POOL_EMPTY, [])

        state     = _make_channel_state(catalog)
        _add_template(state, "tmpl_empty", pool_id=POOL_EMPTY)
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_empty")
        director.extend_horizon(BASE_MS, _T(7_200))

        entry = state.schedule_registry._windows[key]
        assert entry.state == ScheduleWindowState.BLOCKED, (
            "window must be BLOCKED when Tier 2 resolution fails (empty pool)"
        )
        assert entry.blocked_reason_code == "VAL-T2-008"
        assert entry.blocked_at_ms is not None
        assert entry.blocked_details is not None

        # SCHED-INDEX-001: BLOCKED entry still in index.
        assert key in state.template_ref_index._index.get("tmpl_empty", []), (
            "BLOCKED window must remain in TemplateReferenceIndex (SCHED-INDEX-001)"
        )

        # delete_template rejected because the window is still indexed.
        with pytest.raises(SchedulerError) as exc_info:
            scheduler.delete_template("tmpl_empty")
        assert exc_info.value.code == "VAL-T1-004", (
            "delete_template must raise VAL-T1-004 while BLOCKED window is in index"
        )
        assert "tmpl_empty" in exc_info.value.message

    def test_delete_succeeds_after_rebuild_to_different_template(self):
        """After rebuild_window switches to a different template, the index no
        longer references the original template → delete_template succeeds."""
        catalog = _make_catalog()
        catalog.add_pool(POOL_EMPTY, [])

        state     = _make_channel_state(catalog)
        _add_template(state, "tmpl_empty", pool_id=POOL_EMPTY)
        _add_template(state, "tmpl_main",  pool_id=POOL_MAIN)
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_empty")
        director.extend_horizon(BASE_MS, _T(7_200))

        assert state.schedule_registry._windows[key].state == ScheduleWindowState.BLOCKED

        # Operator rebuilds to working template; state resets to COMMITTED.
        scheduler.rebuild_window(
            key,
            ScheduleEntrySpec(
                type="template",
                name="tmpl_main",
                wall_start_ms=_T(0),
                wall_end_ms=_T(WINDOW_DURATION_S),
            ),
        )

        # Index: tmpl_empty removed, tmpl_main inserted.
        assert "tmpl_empty" not in state.template_ref_index._index, (
            "tmpl_empty must be absent from index after rebuild to a different template"
        )
        assert key in state.template_ref_index._index.get("tmpl_main", [])

        # delete_template("tmpl_empty") now succeeds — zero references in index.
        scheduler.delete_template("tmpl_empty")
        assert "tmpl_empty" not in state.template_registry._templates

    def test_rebuild_after_blocked_allows_tier2_build(self):
        """rebuild_window resets state to COMMITTED and clears blocked_* fields.
        The next extend_horizon can then successfully build a PlaylogWindow."""
        catalog = _make_catalog()
        catalog.add_pool(POOL_EMPTY, [])

        state     = _make_channel_state(catalog)
        _add_template(state, "tmpl_empty", pool_id=POOL_EMPTY)
        _add_template(state, "tmpl_main",  pool_id=POOL_MAIN)
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_empty")
        director.extend_horizon(BASE_MS, _T(7_200))
        assert state.schedule_registry._windows[key].state == ScheduleWindowState.BLOCKED

        # Operator's fix: rebuild to a working template.
        scheduler.rebuild_window(
            key,
            ScheduleEntrySpec(
                type="template",
                name="tmpl_main",
                wall_start_ms=_T(0),
                wall_end_ms=_T(WINDOW_DURATION_S),
            ),
        )

        rebuilt_entry = state.schedule_registry._windows[key]
        assert rebuilt_entry.state == ScheduleWindowState.COMMITTED, (
            "rebuild_window must reset state to COMMITTED"
        )
        assert rebuilt_entry.blocked_reason_code is None
        assert rebuilt_entry.blocked_at_ms is None
        assert rebuilt_entry.blocked_details is None

        # Tier 2 can now build a PlaylogWindow.
        director.extend_horizon(BASE_MS, _T(7_200))
        pw = state.playlog_registry._windows.get(key)
        assert pw is not None, (
            "Tier 2 must build a PlaylogWindow after the operator rebuilds a BLOCKED window"
        )
        assert pw.source_window_uuid == rebuilt_entry.window_uuid
        assert pw.state == PlaylogWindowState.PENDING


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4: Cold restart behaviour
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_restart(state_before: ChannelRuntimeState) -> ChannelRuntimeState:
    """Reproduce the startup sequence from RuntimeLifecycleAuthority_v1.0 §8.

    Step 1: TemplateRegistry rebuilt from config (same TemplateDefs).
    Step 2: ScheduleRegistry restored from Postgres (entries copied verbatim,
            preserving window_uuid and state — including BLOCKED).
    Step 3: TemplateReferenceIndex derived from restored ScheduleRegistry.
    Step 4: PlaylogRegistry starts empty.
    Step 5: ChannelActiveState initialised with active_window_key = None.
    """
    # Step 1: TemplateRegistry from config.
    new_template_registry = TemplateRegistry()
    with state_before.template_registry._lock:
        for tid, tdef in state_before.template_registry._templates.items():
            new_template_registry._templates[tid] = tdef

    # Step 2: ScheduleRegistry restored from Postgres.
    restored_schedule = ScheduleRegistry()
    with state_before.schedule_registry._lock:
        for wkey, entry in state_before.schedule_registry._windows.items():
            restored_schedule._windows[wkey] = entry

    # Step 3: TemplateReferenceIndex derived from restored ScheduleRegistry.
    new_tri = TemplateReferenceIndex()
    for wkey, entry in restored_schedule._windows.items():
        if entry.type == "template":
            _index_insert(new_tri, entry.name, wkey)

    # Step 4 + 5: fresh PlaylogRegistry and ChannelActiveState.
    return ChannelRuntimeState(
        channel_id=state_before.channel_id,
        template_registry=new_template_registry,
        schedule_registry=restored_schedule,
        template_ref_index=new_tri,
        playlog_registry=PlaylogRegistry(),
        active_state=ChannelActiveState(channel_id=state_before.channel_id),
        asset_catalog=state_before.asset_catalog,
        metadata_evaluator=state_before.metadata_evaluator,
        clock=_FakeClock(),
    )


class TestColdRestartBehavior:
    """Restart posture: ScheduleRegistry (with uuid + state) restored exactly;
    PlaylogRegistry and ChannelActiveState start empty."""

    def test_playlog_registry_empty_after_restart(self):
        """PlaylogRegistry is empty post-restart even if windows were built
        before shutdown.  The first extend_horizon rebuilds the horizon."""
        state_before = _make_channel_state()
        _add_template(state_before, "tmpl_a")
        scheduler_before = Tier1Scheduler(state_before)
        director_before  = _Tier2Director(state_before)

        key = _commit_one(scheduler_before, "tmpl_a")
        director_before.extend_horizon(BASE_MS, _T(7_200))
        assert key in state_before.playlog_registry._windows

        state_after = _simulate_restart(state_before)

        assert len(state_after.playlog_registry._windows) == 0, (
            "PlaylogRegistry must be empty after cold restart"
        )
        assert state_after.active_state.active_window_key is None

    def test_window_uuid_preserved_across_restart(self):
        """window_uuid on ScheduledEntry is restored exactly from Postgres."""
        state_before     = _make_channel_state()
        _add_template(state_before, "tmpl_a")
        scheduler_before = Tier1Scheduler(state_before)

        key           = _commit_one(scheduler_before, "tmpl_a")
        original_uuid = state_before.schedule_registry._windows[key].window_uuid

        state_after = _simulate_restart(state_before)

        restored_uuid = state_after.schedule_registry._windows[key].window_uuid
        assert restored_uuid == original_uuid, (
            "window_uuid must survive cold restart (RuntimeLifecycleAuthority §5)"
        )

    def test_template_ref_index_rebuilt_from_schedule_registry(self):
        """TemplateReferenceIndex is derived from the restored ScheduleRegistry
        and contains the same entries it held before shutdown."""
        state_before     = _make_channel_state()
        _add_template(state_before, "tmpl_a")
        scheduler_before = Tier1Scheduler(state_before)

        key = _commit_one(scheduler_before, "tmpl_a")

        state_after = _simulate_restart(state_before)

        assert key in state_after.template_ref_index._index.get("tmpl_a", []), (
            "TemplateReferenceIndex must be reconstructed from restored ScheduleRegistry"
        )

    def test_tier2_builds_normally_after_restart(self):
        """After cold restart, extend_horizon produces a valid PlaylogWindow
        carrying the same window_uuid that was persisted before shutdown."""
        state_before     = _make_channel_state()
        _add_template(state_before, "tmpl_a")
        scheduler_before = Tier1Scheduler(state_before)

        key           = _commit_one(scheduler_before, "tmpl_a")
        original_uuid = state_before.schedule_registry._windows[key].window_uuid

        state_after   = _simulate_restart(state_before)
        director_after = _Tier2Director(state_after)
        director_after.extend_horizon(BASE_MS, _T(7_200))

        pw = state_after.playlog_registry._windows.get(key)
        assert pw is not None, (
            "Tier 2 must build a PlaylogWindow on the first extend_horizon after restart"
        )
        assert pw.source_window_uuid == original_uuid, (
            "post-restart PlaylogWindow must carry the persisted window_uuid"
        )

    def test_blocked_state_survives_restart(self):
        """BLOCKED windows are restored with all blocked_* fields intact.
        extend_horizon skips them; TemplateReferenceIndex still contains them."""
        state_before     = _make_channel_state()
        _add_template(state_before, "tmpl_a")
        scheduler_before = Tier1Scheduler(state_before)

        key = _commit_one(scheduler_before, "tmpl_a")

        # Simulate ProgramDirector marking the window BLOCKED (as _mark_blocked does).
        with state_before.schedule_registry._lock:
            entry                    = state_before.schedule_registry._windows[key]
            entry.state              = ScheduleWindowState.BLOCKED
            entry.blocked_reason_code = "VAL-T2-001"
            entry.blocked_at_ms      = BASE_MS + 500
            entry.blocked_details    = "template absent at Tier 2 resolution time"

        state_after = _simulate_restart(state_before)

        restored = state_after.schedule_registry._windows[key]
        assert restored.state               == ScheduleWindowState.BLOCKED
        assert restored.blocked_reason_code == "VAL-T2-001"
        assert restored.blocked_at_ms       == BASE_MS + 500
        assert restored.blocked_details     == "template absent at Tier 2 resolution time"

        # SCHED-INDEX-001 preserved after restart.
        assert key in state_after.template_ref_index._index.get("tmpl_a", []), (
            "BLOCKED entry must be in TemplateReferenceIndex after restart (SCHED-INDEX-001)"
        )

        # Tier 2 skips BLOCKED windows.
        director_after = _Tier2Director(state_after)
        director_after.extend_horizon(BASE_MS, _T(7_200))
        assert key not in state_after.playlog_registry._windows, (
            "Tier 2 must not build a PlaylogWindow for a BLOCKED window after restart"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5: Seed behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestSeedBehavior:
    """build_seed is drawn fresh per build session; no rebuild → no new seed."""

    def test_no_rebuild_reuses_existing_window_and_seed(self):
        """Two extend_horizon calls with no Tier 1 rebuild return the same
        PlaylogWindow object with the same build_seed."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))
        first_pw   = state.playlog_registry._windows[key]
        first_seed = first_pw.build_seed

        director.extend_horizon(BASE_MS, _T(7_200))
        same_pw = state.playlog_registry._windows[key]

        assert same_pw is first_pw, (
            "extend_horizon without rebuild must reuse the existing PlaylogWindow"
        )
        assert same_pw.build_seed == first_seed, (
            "seed must not change when no rebuild has occurred (SEED-SESSION-001)"
        )

    def test_tier1_rebuild_produces_new_seed(self):
        """A Tier 1 rebuild triggers staleness detection → new build session →
        new build_seed drawn (statistically distinct from the prior seed)."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))
        first_seed = state.playlog_registry._windows[key].build_seed

        scheduler.rebuild_window(key, _template_spec("tmpl_a"))
        director.extend_horizon(BASE_MS, _T(7_200))
        second_seed = state.playlog_registry._windows[key].build_seed

        assert second_seed != first_seed, (
            "Tier 1 rebuild must trigger a new build session with a new seed"
        )

    def test_restart_produces_new_seed(self):
        """After cold restart (empty PlaylogRegistry), the first extend_horizon
        draws a new seed — the previous session's seed is not restored."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")
        director.extend_horizon(BASE_MS, _T(7_200))
        pre_restart_seed = state.playlog_registry._windows[key].build_seed

        # Simulate cold restart: clear PlaylogRegistry (Tier 2 state not persisted).
        state.playlog_registry._windows.clear()
        state.playlog_registry._active_keys.clear()

        director.extend_horizon(BASE_MS, _T(7_200))
        post_restart_seed = state.playlog_registry._windows[key].build_seed

        assert post_restart_seed != pre_restart_seed, (
            "cold restart must produce a new build session seed; "
            "seeds are never restored from pre-restart state"
        )

    def test_source_window_uuid_tracks_tier1_entry_across_rebuilds(self):
        """source_window_uuid always matches the current ScheduledEntry.window_uuid
        immediately after each extend_horizon completes a build."""
        state     = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        director  = _Tier2Director(state)

        key = _commit_one(scheduler, "tmpl_a")

        for _ in range(3):
            entry = state.schedule_registry._windows[key]
            director.extend_horizon(BASE_MS, _T(7_200))
            pw = state.playlog_registry._windows[key]
            assert pw.source_window_uuid == entry.window_uuid, (
                "source_window_uuid must match ScheduledEntry.window_uuid "
                "immediately after extend_horizon"
            )
            scheduler.rebuild_window(key, _template_spec("tmpl_a"))
