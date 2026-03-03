# pkg/core/tests/contracts/test_scheduler_tier1_contract.py
#
# Operator-facing contract tests for Tier1Scheduler.
#
# Covers:
#   VAL-T1-001  build_horizon: type:template references unknown template
#   VAL-T1-002  build_horizon: type:pool references unknown pool
#   VAL-T1-003  build_horizon: type:asset references unknown asset_id
#   VAL-T1-004  delete_template: rejected while any ScheduledEntry references it
#   VAL-T1-005  rename_template: rejected while any ScheduledEntry references it
#
# Each test asserts:
#   - The correct SchedulerError.code is raised.
#   - The error message contains the expected identifiers and earliest window.
#   - The success path (zero references) completes without error.
#
# ── Expected failure mode ────────────────────────────────────────────────────
# All tests FAIL (NotImplementedError) until Tier1Scheduler is implemented.

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
    SchedulerError,
    Tier1Scheduler,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

CHANNEL_ID = "ch-t1-contract-test"
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


def _commit_one(
    scheduler: Tier1Scheduler,
    template_id: str,
    start_offset_s: int = 0,
    duration_s: int = 3_600,
) -> WindowKey:
    """Commit a single template-type window and return its WindowKey."""
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


# ─────────────────────────────────────────────────────────────────────────────
# VAL-T1-004  —  delete_template
# ─────────────────────────────────────────────────────────────────────────────

class TestDeleteTemplateVALT1004:

    def test_raises_when_committed_window_references_template(self):
        """delete_template raises VAL-T1-004 when a COMMITTED window
        references the template."""
        state = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        _commit_one(scheduler, "tmpl_a")

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.delete_template("tmpl_a")

        assert exc_info.value.code == "VAL-T1-004"

    def test_raises_when_blocked_window_references_template(self):
        """delete_template raises VAL-T1-004 even when the referencing
        window is BLOCKED.

        SCHED-INDEX-001 indexes BLOCKED entries; the template cannot be
        deleted until the operator explicitly removes or rebuilds the window.
        """
        state = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        key = _commit_one(scheduler, "tmpl_a")

        # Simulate ProgramDirector BLOCKED transition
        with state.schedule_registry._lock:
            entry = state.schedule_registry._windows[key]
            entry.state               = ScheduleWindowState.BLOCKED
            entry.blocked_reason_code = "VAL-T2-001"
            entry.blocked_at_ms       = BASE_MS + 1
            entry.blocked_details     = "simulated block for test"

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.delete_template("tmpl_a")

        assert exc_info.value.code == "VAL-T1-004"

    def test_error_contains_template_id_and_reference_count(self):
        """VAL-T1-004 error message contains the template_id and reference count."""
        state = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)
        _commit_one(scheduler, "tmpl_a", start_offset_s=0)
        _commit_one(scheduler, "tmpl_a", start_offset_s=3_600)

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.delete_template("tmpl_a")

        err = exc_info.value
        assert err.code == "VAL-T1-004"
        assert "tmpl_a" in err.message
        assert "2" in err.message  # reference count

    def test_error_reports_earliest_affected_window(self):
        """VAL-T1-004 error message identifies the earliest window by
        channel_id and wall_start_ms.

        Windows are committed in non-chronological order to verify that
        the implementation correctly identifies the earliest, not the most
        recently committed.
        """
        state = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)

        # Commit later window first, earlier window second
        _commit_one(scheduler, "tmpl_a", start_offset_s=7_200)  # wall_start = T+7200s
        _commit_one(scheduler, "tmpl_a", start_offset_s=0)       # wall_start = T+0s  ← earliest

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.delete_template("tmpl_a")

        err = exc_info.value
        assert CHANNEL_ID in err.message, "error must include the channel_id of the earliest window"
        assert str(_T(0)) in err.message, (
            "error must include wall_start_ms of the earliest window "
            f"(expected {_T(0)})"
        )

    def test_succeeds_when_zero_references(self):
        """delete_template succeeds (no exception) when TemplateReferenceIndex
        has zero entries for the template.
        """
        state = _make_channel_state()
        _add_template(state, "tmpl_a")
        scheduler = Tier1Scheduler(state)

        # Commit a window, then rebuild it to pool type (removes template reference)
        key = _commit_one(scheduler, "tmpl_a")
        scheduler.rebuild_window(
            key,
            ScheduleEntrySpec(
                type="pool",
                name="pool_a",
                wall_start_ms=_T(0),
                wall_end_ms=_T(3_600),
            ),
        )

        # Now delete must succeed
        scheduler.delete_template("tmpl_a")
        assert "tmpl_a" not in state.template_registry._templates


# ─────────────────────────────────────────────────────────────────────────────
# VAL-T1-005  —  rename_template
# ─────────────────────────────────────────────────────────────────────────────

class TestRenameTemplateVALT1005:

    def test_raises_when_committed_window_references_old_id(self):
        """rename_template raises VAL-T1-005 when a COMMITTED window
        references the old template_id."""
        state = _make_channel_state()
        _add_template(state, "tmpl_old")
        scheduler = Tier1Scheduler(state)
        _commit_one(scheduler, "tmpl_old")

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.rename_template("tmpl_old", "tmpl_new")

        assert exc_info.value.code == "VAL-T1-005"

    def test_raises_when_blocked_window_references_old_id(self):
        """rename_template raises VAL-T1-005 even when the referencing
        window is BLOCKED."""
        state = _make_channel_state()
        _add_template(state, "tmpl_old")
        scheduler = Tier1Scheduler(state)
        key = _commit_one(scheduler, "tmpl_old")

        with state.schedule_registry._lock:
            entry = state.schedule_registry._windows[key]
            entry.state               = ScheduleWindowState.BLOCKED
            entry.blocked_reason_code = "VAL-T2-001"
            entry.blocked_at_ms       = BASE_MS + 1
            entry.blocked_details     = "simulated block"

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.rename_template("tmpl_old", "tmpl_new")

        assert exc_info.value.code == "VAL-T1-005"

    def test_error_contains_both_names_and_reference_count(self):
        """VAL-T1-005 error message contains old_id, new_id, and reference count."""
        state = _make_channel_state()
        _add_template(state, "tmpl_old")
        scheduler = Tier1Scheduler(state)
        _commit_one(scheduler, "tmpl_old", start_offset_s=0)
        _commit_one(scheduler, "tmpl_old", start_offset_s=3_600)

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.rename_template("tmpl_old", "tmpl_new")

        err = exc_info.value
        assert err.code == "VAL-T1-005"
        assert "tmpl_old" in err.message
        assert "tmpl_new" in err.message
        assert "2" in err.message

    def test_error_reports_earliest_affected_window(self):
        """VAL-T1-005 error message identifies the earliest window by
        channel_id and wall_start_ms."""
        state = _make_channel_state()
        _add_template(state, "tmpl_old")
        scheduler = Tier1Scheduler(state)

        _commit_one(scheduler, "tmpl_old", start_offset_s=3_600)  # later
        _commit_one(scheduler, "tmpl_old", start_offset_s=0)       # earlier ← earliest

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.rename_template("tmpl_old", "tmpl_new")

        err = exc_info.value
        assert CHANNEL_ID in err.message
        assert str(_T(0)) in err.message, (
            "error must include wall_start_ms of the earliest window"
        )

    def test_succeeds_when_zero_references_and_updates_registry(self):
        """rename_template succeeds when no windows reference the old_id.

        Post-conditions:
          - new_id present in TemplateRegistry with preserved segments and
            primary_segment_index.
          - old_id absent from TemplateRegistry.
        """
        state = _make_channel_state()
        original = _add_template(state, "tmpl_old")
        scheduler = Tier1Scheduler(state)

        # No windows committed for tmpl_old
        scheduler.rename_template("tmpl_old", "tmpl_new")

        assert "tmpl_new" in state.template_registry._templates, (
            "tmpl_new must be present after successful rename"
        )
        assert "tmpl_old" not in state.template_registry._templates, (
            "tmpl_old must be absent after successful rename"
        )
        new_def = state.template_registry._templates["tmpl_new"]
        assert new_def.id == "tmpl_new"
        assert new_def.segments == original.segments
        assert new_def.primary_segment_index == original.primary_segment_index


# ─────────────────────────────────────────────────────────────────────────────
# VAL-T1-001 / VAL-T1-002 / VAL-T1-003  —  reference validation at build time
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildTimeReferenceValidation:

    def test_val_t1_001_unknown_template_rejected(self):
        """build_horizon raises VAL-T1-001 when type:template references a
        template_id not currently present in TemplateRegistry.
        """
        state = _make_channel_state()
        # Intentionally NOT adding "ghost_template" to TemplateRegistry
        scheduler = Tier1Scheduler(state)

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.build_horizon([
                ScheduleEntrySpec(
                    type="template",
                    name="ghost_template",
                    wall_start_ms=_T(0),
                    wall_end_ms=_T(3_600),
                )
            ])

        err = exc_info.value
        assert err.code == "VAL-T1-001"
        assert "ghost_template" in err.message

    def test_val_t1_001_known_template_accepted(self):
        """build_horizon does NOT raise VAL-T1-001 when the referenced
        template exists in TemplateRegistry."""
        state = _make_channel_state()
        _add_template(state, "real_template")
        scheduler = Tier1Scheduler(state)

        committed = scheduler.build_horizon([
            ScheduleEntrySpec(
                type="template",
                name="real_template",
                wall_start_ms=_T(0),
                wall_end_ms=_T(3_600),
            )
        ])
        assert len(committed) == 1

    def test_val_t1_002_unknown_pool_rejected(self):
        """build_horizon raises VAL-T1-002 when type:pool references a
        pool_id not present in the known_pools set.
        """
        state = _make_channel_state()
        scheduler = Tier1Scheduler(state)

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.build_horizon(
                entries=[
                    ScheduleEntrySpec(
                        type="pool",
                        name="nonexistent_pool",
                        wall_start_ms=_T(0),
                        wall_end_ms=_T(3_600),
                    )
                ],
                known_pools={"pool_a", "pool_b"},
            )

        err = exc_info.value
        assert err.code == "VAL-T1-002"
        assert "nonexistent_pool" in err.message

    def test_val_t1_002_known_pool_accepted(self):
        """build_horizon does NOT raise VAL-T1-002 when the referenced pool
        is in the known_pools set."""
        state = _make_channel_state()
        scheduler = Tier1Scheduler(state)

        committed = scheduler.build_horizon(
            entries=[
                ScheduleEntrySpec(
                    type="pool",
                    name="pool_a",
                    wall_start_ms=_T(0),
                    wall_end_ms=_T(3_600),
                )
            ],
            known_pools={"pool_a"},
        )
        assert len(committed) == 1

    def test_val_t1_003_unknown_asset_rejected(self):
        """build_horizon raises VAL-T1-003 when type:asset references an
        asset_id not present in the known_asset_ids set.
        """
        state = _make_channel_state()
        scheduler = Tier1Scheduler(state)

        with pytest.raises(SchedulerError) as exc_info:
            scheduler.build_horizon(
                entries=[
                    ScheduleEntrySpec(
                        type="asset",
                        asset_id="asset-ghost-001",
                        wall_start_ms=_T(0),
                        wall_end_ms=_T(3_600),
                    )
                ],
                known_asset_ids={"asset-real-001", "asset-real-002"},
            )

        err = exc_info.value
        assert err.code == "VAL-T1-003"
        assert "asset-ghost-001" in err.message

    def test_val_t1_003_known_asset_accepted(self):
        """build_horizon does NOT raise VAL-T1-003 when the referenced asset_id
        is in the known_asset_ids set."""
        state = _make_channel_state()
        scheduler = Tier1Scheduler(state)

        committed = scheduler.build_horizon(
            entries=[
                ScheduleEntrySpec(
                    type="asset",
                    asset_id="asset-real-001",
                    wall_start_ms=_T(0),
                    wall_end_ms=_T(3_600),
                )
            ],
            known_asset_ids={"asset-real-001"},
        )
        assert len(committed) == 1
