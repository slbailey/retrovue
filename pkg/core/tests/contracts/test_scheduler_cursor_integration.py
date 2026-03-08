"""Contract tests for Scheduler Cursor Integration.

Validates all invariants defined in:
    docs/contracts/scheduler_cursor_integration.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-DERIVATION, LAW-IMMUTABILITY.

These tests simulate the scheduler compilation protocol using lightweight
fakes. No real scheduler, database, or media is involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from retrovue.runtime.progression_cursor import (
    AdvanceResult,
    PlanningFault,
    ProgressionCursor,
    ScheduleBlockIdentity,
    advance_cursor,
    initialize_cursor,
)


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

POOL_ASSETS = ["asset-0", "asset-1", "asset-2", "asset-3", "asset-4"]


def _identity(
    channel_id: str = "ch-1",
    schedule_layer: str = "thursday",
    start_time: str = "20:00",
    program_ref: str = "sitcom_hour",
) -> ScheduleBlockIdentity:
    return ScheduleBlockIdentity(
        channel_id=channel_id,
        schedule_layer=schedule_layer,
        start_time=start_time,
        program_ref=program_ref,
    )


class CompilationFault(Exception):
    """Raised when cursor persistence fails during compilation."""


@dataclass
class FakeArtifact:
    """Minimal schedule artifact produced by the fake scheduler."""

    asset_id: str
    identity: ScheduleBlockIdentity


@dataclass
class FakeCursorStore:
    """In-memory cursor store with optional write failure injection."""

    _data: dict[tuple, ProgressionCursor] = field(default_factory=dict)
    fail_on_save: bool = False

    def _key(self, identity: ScheduleBlockIdentity) -> tuple:
        return (
            identity.channel_id,
            identity.schedule_layer,
            identity.start_time,
            identity.program_ref,
        )

    def load(self, identity: ScheduleBlockIdentity) -> ProgressionCursor | None:
        return self._data.get(self._key(identity))

    def save(self, cursor: ProgressionCursor) -> None:
        if self.fail_on_save:
            raise OSError("INV-SCHED-CURSOR-002: simulated cursor store write failure")
        self._data[self._key(cursor.identity)] = cursor

    def snapshot(self) -> dict[tuple, ProgressionCursor]:
        return dict(self._data)

    @classmethod
    def from_snapshot(cls, snap: dict[tuple, ProgressionCursor]) -> FakeCursorStore:
        store = cls()
        store._data = dict(snap)
        return store


@dataclass
class FakeScheduler:
    """Minimal scheduler that follows the 6-step cursor protocol.

    Protocol:
        1. Resolve identity
        2. Load cursor (or initialize)
        3. Select asset
        4. Advance cursor
        5. Persist cursor
        6. Publish artifact

    This is a test double — it validates the protocol contract, not the
    real scheduler implementation.
    """

    cursor_store: FakeCursorStore
    pool_assets: list[str]
    artifacts: list[FakeArtifact] = field(default_factory=list)
    event_log: list[str] = field(default_factory=list)

    def compile_execution(
        self,
        identity: ScheduleBlockIdentity,
        progression: str = "sequential",
    ) -> FakeArtifact:
        """Execute one pass of the compilation protocol."""

        # Step 1: resolve identity (already provided)

        # Step 2: load cursor
        cursor = self.cursor_store.load(identity)
        if cursor is None:
            mode = "shuffle" if progression == "shuffle" else "sequential"
            cursor = initialize_cursor(identity, mode=mode)
        self.event_log.append("cursor_loaded")

        # Step 3 + 4: select asset and advance cursor
        result = advance_cursor(
            cursor=cursor,
            pool_assets=self.pool_assets,
            progression=progression,
        )
        self.event_log.append("cursor_advanced")

        # Step 5: persist cursor
        try:
            self.cursor_store.save(result.cursor)
            self.event_log.append("cursor_persisted")
        except OSError:
            self.event_log.append("cursor_persist_failed")
            raise CompilationFault(
                "INV-SCHED-CURSOR-005: cursor persistence failed, artifact not published"
            )

        # Step 6: publish artifact
        artifact = FakeArtifact(
            asset_id=result.selected_asset,
            identity=identity,
        )
        self.artifacts.append(artifact)
        self.event_log.append("artifact_published")

        return artifact

    def compile_block(
        self,
        identity: ScheduleBlockIdentity,
        executions: int = 1,
        progression: str = "sequential",
    ) -> list[FakeArtifact]:
        """Compile a schedule block with N executions."""
        results = []
        for _ in range(executions):
            results.append(self.compile_execution(identity, progression))
        return results


# ===========================================================================
# INV-SCHED-CURSOR-001
# Cursor must be loaded before asset selection
# ===========================================================================


@pytest.mark.contract
class TestInvSchedCursor001:
    """INV-SCHED-CURSOR-001"""

    def test_cursor_loaded_before_sequential_selection(self):
        # INV-SCHED-CURSOR-001 — sequential compilation loads cursor before selecting
        store = FakeCursorStore()
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        scheduler.compile_execution(identity, progression="sequential")

        # cursor_loaded must appear before cursor_advanced
        log = scheduler.event_log
        assert "cursor_loaded" in log
        assert "cursor_advanced" in log
        assert log.index("cursor_loaded") < log.index("cursor_advanced")

    def test_cursor_loaded_before_shuffle_selection(self):
        # INV-SCHED-CURSOR-001 — shuffle compilation loads cursor before selecting
        store = FakeCursorStore()
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        scheduler.compile_execution(identity, progression="shuffle")

        log = scheduler.event_log
        assert log.index("cursor_loaded") < log.index("cursor_advanced")

    def test_cursor_initialized_when_absent(self):
        # INV-SCHED-CURSOR-001 — first compilation initializes cursor at position=0
        store = FakeCursorStore()
        identity = _identity()

        # No cursor exists in store
        assert store.load(identity) is None

        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        scheduler.compile_execution(identity)

        # After compilation, cursor must exist in store at position=1 (post-advance)
        persisted = store.load(identity)
        assert persisted is not None
        assert persisted.position == 1
        assert persisted.cycle == 0


# ===========================================================================
# INV-SCHED-CURSOR-002
# Cursor must be persisted after advancement
# ===========================================================================


@pytest.mark.contract
class TestInvSchedCursor002:
    """INV-SCHED-CURSOR-002"""

    def test_cursor_persisted_after_advance(self):
        # INV-SCHED-CURSOR-002 — cursor store contains updated position after compilation
        store = FakeCursorStore()
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        scheduler.compile_execution(identity)

        persisted = store.load(identity)
        assert persisted is not None
        assert persisted.position == 1

    def test_cursor_persisted_before_artifact_exists(self):
        # INV-SCHED-CURSOR-002 — cursor persist event occurs before artifact publish event
        store = FakeCursorStore()
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        scheduler.compile_execution(identity)

        log = scheduler.event_log
        assert "cursor_persisted" in log
        assert "artifact_published" in log
        assert log.index("cursor_persisted") < log.index("artifact_published")

    def test_persist_failure_blocks_artifact(self):
        # INV-SCHED-CURSOR-002 — cursor store write failure prevents artifact publication
        store = FakeCursorStore(fail_on_save=True)
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        with pytest.raises(CompilationFault):
            scheduler.compile_execution(identity)

        assert len(scheduler.artifacts) == 0
        assert "artifact_published" not in scheduler.event_log


# ===========================================================================
# INV-SCHED-CURSOR-003
# Scheduler must not use in-memory progression counters
# ===========================================================================


@pytest.mark.contract
class TestInvSchedCursor003:
    """INV-SCHED-CURSOR-003"""

    def test_no_in_memory_counters(self):
        # INV-SCHED-CURSOR-003 — compilation uses cursor store, not a local dict counter.
        # Verify: two independent scheduler instances with the same store produce
        # continuous progression, not restarted-from-zero progression.
        store = FakeCursorStore()
        identity = _identity()

        # First scheduler compiles one execution
        sched_1 = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        sched_1.compile_execution(identity)

        # Second scheduler (new instance, same store) compiles next
        sched_2 = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        sched_2.compile_execution(identity)

        # Store must show position=2 (not reset to 1)
        persisted = store.load(identity)
        assert persisted is not None
        assert persisted.position == 2

        # Assets must be different (positions 0 and 1 from pool)
        assert sched_1.artifacts[0].asset_id == POOL_ASSETS[0]
        assert sched_2.artifacts[0].asset_id == POOL_ASSETS[1]

    def test_restart_continues_from_persisted_position(self):
        # INV-SCHED-CURSOR-003 — after simulated restart, compilation resumes
        # from stored position, not from 0.
        store = FakeCursorStore()
        identity = _identity()

        # Compile 3 executions, then take snapshot
        sched = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        sched.compile_block(identity, executions=3)
        snapshot = store.snapshot()

        # Simulate restart: new store from snapshot, new scheduler
        restored_store = FakeCursorStore.from_snapshot(snapshot)
        new_sched = FakeScheduler(cursor_store=restored_store, pool_assets=POOL_ASSETS)
        new_sched.compile_execution(identity)

        # Must select asset at position 3 (not 0)
        assert new_sched.artifacts[0].asset_id == POOL_ASSETS[3]

        persisted = restored_store.load(identity)
        assert persisted is not None
        assert persisted.position == 4


# ===========================================================================
# INV-SCHED-CURSOR-004
# Schedule artifact must reflect cursor-selected asset
# ===========================================================================


@pytest.mark.contract
class TestInvSchedCursor004:
    """INV-SCHED-CURSOR-004"""

    def test_artifact_contains_cursor_selected_asset(self):
        # INV-SCHED-CURSOR-004 — artifact asset_id matches cursor-selected asset
        store = FakeCursorStore()
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        artifact = scheduler.compile_execution(identity)

        # Cursor was at position 0 → selected asset-0
        assert artifact.asset_id == POOL_ASSETS[0]

    def test_multi_execution_artifacts_match_cursor_sequence(self):
        # INV-SCHED-CURSOR-004 — 3 executions produce assets at positions 0, 1, 2
        store = FakeCursorStore()
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        artifacts = scheduler.compile_block(identity, executions=3)

        assert artifacts[0].asset_id == POOL_ASSETS[0]
        assert artifacts[1].asset_id == POOL_ASSETS[1]
        assert artifacts[2].asset_id == POOL_ASSETS[2]


# ===========================================================================
# INV-SCHED-CURSOR-005
# Cursor persistence must precede artifact publication
# ===========================================================================


@pytest.mark.contract
class TestInvSchedCursor005:
    """INV-SCHED-CURSOR-005"""

    def test_persist_precedes_publish(self):
        # INV-SCHED-CURSOR-005 — cursor store write happens before artifact is emitted
        store = FakeCursorStore()
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        scheduler.compile_execution(identity)

        log = scheduler.event_log
        persist_idx = log.index("cursor_persisted")
        publish_idx = log.index("artifact_published")
        assert persist_idx < publish_idx

    def test_failed_persist_no_artifact(self):
        # INV-SCHED-CURSOR-005 — store write failure means zero artifacts produced
        store = FakeCursorStore(fail_on_save=True)
        scheduler = FakeScheduler(cursor_store=store, pool_assets=POOL_ASSETS)
        identity = _identity()

        with pytest.raises(CompilationFault):
            scheduler.compile_execution(identity)

        assert len(scheduler.artifacts) == 0
        assert "cursor_persist_failed" in scheduler.event_log
        assert "artifact_published" not in scheduler.event_log
