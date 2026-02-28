"""Horizon Manager — Production-Ready (Phase 1+)

Wall-clock-driven policy enforcer for EPG and execution horizons.
Evaluates horizon depth and triggers extensions when below threshold.

See: docs/domains/HorizonManager_v0.1.md
     docs/contracts/ScheduleHorizonManagementContract_v0.1.md

Phase 1+: Wired into ProgramDirector in shadow and authoritative modes.
Evaluation via evaluate_once() or a background daemon thread via
start()/stop().  Provides structured health reports for observability.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocols — what HorizonManager needs from upstream layers
# ---------------------------------------------------------------------------

@runtime_checkable
class ScheduleExtender(Protocol):
    """What HorizonManager needs from the schedule/EPG layer.

    Concrete adapters wrap ScheduleManager (or mocks) behind
    this interface.  HorizonManager never calls ScheduleManager directly.
    """

    def epg_day_exists(self, broadcast_date: date) -> bool:
        """Return True if the broadcast date has already been resolved."""
        ...

    def extend_epg_day(self, broadcast_date: date) -> None:
        """Resolve EPG for the given broadcast date."""
        ...


@runtime_checkable
class ExecutionExtender(Protocol):
    """What HorizonManager needs from the execution/pipeline layer.

    Concrete adapters wrap run_planning_pipeline (or mocks) behind
    this interface.  HorizonManager never calls the pipeline directly.
    """

    def extend_execution_day(self, broadcast_date: date) -> int:
        """Generate execution data for the given broadcast date.

        Returns the end_utc_ms of the last entry in the generated
        TransmissionLog.
        """
        ...


# ---------------------------------------------------------------------------
# Health Report
# ---------------------------------------------------------------------------

@dataclass
class HorizonHealthReport:
    """Snapshot of horizon health at a point in time.

    Returned by HorizonManager.get_health_report() for endpoints
    and structured logging.
    """
    epg_depth_hours: float
    execution_depth_hours: float
    min_epg_days: int
    min_execution_hours: int
    epg_farthest_date: str | None
    execution_window_end_utc_ms: int
    last_evaluation_utc_ms: int
    is_healthy: bool
    epg_compliant: bool
    execution_compliant: bool
    next_block_compliant: bool
    coverage_compliant: bool
    proactive_extension_triggered: bool
    evaluation_interval_seconds: int
    store_entry_count: int


@dataclass
class ExtensionAttempt:
    """Record of a single execution horizon extension attempt."""
    attempt_id: str
    now_utc_ms: int
    window_end_before_ms: int
    window_end_after_ms: int
    reason_code: str        # "REASON_TIME_THRESHOLD" | "DAILY_ROLL" | "REASON_OPERATOR_OVERRIDE"
    triggered_by: str       # "SCHED_MGR_POLICY"
    success: bool
    error_code: str | None = None


@dataclass
class SeamViolation:
    """Record of a contiguity violation between adjacent entries."""
    left_block_id: str
    left_end_utc_ms: int
    right_block_id: str
    right_start_utc_ms: int
    delta_ms: int           # right_start - left_end; >0 = gap, <0 = overlap


# ---------------------------------------------------------------------------
# HorizonManager
# ---------------------------------------------------------------------------

# Safety valve: never extend more than this many days in a single evaluation.
_MAX_EXTENSION_DAYS = 30


class HorizonManager:
    """Wall-clock-driven horizon depth enforcer.

    Evaluates EPG and execution horizon depths at a fixed interval.
    Triggers schedule resolution and pipeline execution when depths
    fall below configured minimums.

    Phase 1: passive mode.  Can be evaluated explicitly via
    evaluate_once().  start()/stop() run a background daemon thread.
    """

    def __init__(
        self,
        schedule_manager: ScheduleExtender,
        planning_pipeline: ExecutionExtender,
        master_clock,  # needs .now_utc() -> datetime
        min_epg_days: int = 3,
        min_execution_hours: int = 6,
        evaluation_interval_seconds: int = 10,
        programming_day_start_hour: int = 6,
        execution_store=None,  # Optional ExecutionWindowStore
        locked_window_ms: int = 0,
        proactive_extend_threshold_ms: int = 0,
    ):
        self._schedule_manager = schedule_manager
        self._planning_pipeline = planning_pipeline
        self._clock = master_clock
        self._min_epg_days = min_epg_days
        self._min_execution_hours = min_execution_hours
        self._eval_interval_s = evaluation_interval_seconds
        self._day_start_hour = programming_day_start_hour
        self._execution_store = execution_store
        self._locked_window_ms = locked_window_ms
        self._proactive_extend_threshold_ms = proactive_extend_threshold_ms
        self._logger = logging.getLogger(__name__)

        # Internal state
        self._epg_farthest_date: date | None = None
        self._execution_window_end_utc_ms: int = 0
        self._last_evaluation_utc_ms: int = 0
        self._next_block_compliant: bool = True
        self._coverage_compliant: bool = True
        self._seam_violations: list[SeamViolation] = []
        self._proactive_extension_triggered: bool = False

        # Generation tracking (for publish_atomic_replace)
        self._next_generation_id: int = 0

        # Audit state
        self._extension_attempt_count: int = 0
        self._extension_success_count: int = 0
        self._extension_forbidden_trigger_count: int = 0
        self._extension_attempt_log: list[ExtensionAttempt] = []

        # Background thread
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public properties (observability)
    # ------------------------------------------------------------------

    @property
    def epg_window_end_utc_ms(self) -> int:
        """End of the farthest resolved broadcast day, in epoch ms."""
        if self._epg_farthest_date is None:
            return 0
        return self._day_end_utc_ms(self._epg_farthest_date)

    @property
    def execution_window_end_utc_ms(self) -> int:
        """End of the farthest generated TransmissionLog entry, in epoch ms."""
        return self._execution_window_end_utc_ms

    @property
    def last_evaluation_utc_ms(self) -> int:
        """Wall-clock time of the most recent evaluate_once() call, in epoch ms."""
        return self._last_evaluation_utc_ms

    @property
    def extension_attempt_count(self) -> int:
        """Total execution extension attempts since init."""
        return self._extension_attempt_count

    @property
    def extension_success_count(self) -> int:
        """Successful execution extensions since init."""
        return self._extension_success_count

    @property
    def extension_forbidden_trigger_count(self) -> int:
        """Forbidden-trigger attempts intercepted since init."""
        return self._extension_forbidden_trigger_count

    @property
    def next_block_compliant(self) -> bool:
        """True when the next block at 'now' is present in the store."""
        return self._next_block_compliant

    @property
    def coverage_compliant(self) -> bool:
        """True when all adjacent entries form a contiguous sequence."""
        return self._coverage_compliant

    @property
    def seam_violations(self) -> list[SeamViolation]:
        """Seam violations found during the most recent evaluation."""
        return list(self._seam_violations)

    @property
    def proactive_extension_triggered(self) -> bool:
        """True if the most recent evaluate_once() triggered a proactive extension."""
        return self._proactive_extension_triggered

    @property
    def extension_attempt_log(self) -> list[ExtensionAttempt]:
        """Full log of all execution extension attempts."""
        return list(self._extension_attempt_log)

    # ------------------------------------------------------------------
    # Depth queries
    # ------------------------------------------------------------------

    def get_epg_depth_hours(self) -> float:
        """Current EPG horizon depth in hours (from now to farthest day end)."""
        now_ms = self._now_utc_ms()
        end_ms = self.epg_window_end_utc_ms
        if end_ms <= now_ms:
            return 0.0
        return (end_ms - now_ms) / 3_600_000.0

    def get_execution_depth_hours(self) -> float:
        """Current execution horizon depth in hours (from now to farthest entry end)."""
        now_ms = self._now_utc_ms()
        end_ms = self._execution_window_end_utc_ms
        if end_ms <= now_ms:
            return 0.0
        return (end_ms - now_ms) / 3_600_000.0

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @property
    def is_healthy(self) -> bool:
        """True when both EPG and execution depths meet configured minimums."""
        return (
            self.get_epg_depth_hours() >= self._min_epg_days * 24.0
            and self.get_execution_depth_hours() >= self._min_execution_hours
        )

    def get_health_report(self) -> HorizonHealthReport:
        """Build a point-in-time health snapshot."""
        epg_h = self.get_epg_depth_hours()
        exec_h = self.get_execution_depth_hours()
        store_count = 0
        if self._execution_store is not None:
            try:
                store_count = len(self._execution_store.get_all_entries())
            except Exception:
                pass
        return HorizonHealthReport(
            epg_depth_hours=round(epg_h, 2),
            execution_depth_hours=round(exec_h, 2),
            min_epg_days=self._min_epg_days,
            min_execution_hours=self._min_execution_hours,
            epg_farthest_date=(
                self._epg_farthest_date.isoformat()
                if self._epg_farthest_date else None
            ),
            execution_window_end_utc_ms=self._execution_window_end_utc_ms,
            last_evaluation_utc_ms=self._last_evaluation_utc_ms,
            is_healthy=self.is_healthy,
            epg_compliant=epg_h >= self._min_epg_days * 24.0,
            execution_compliant=exec_h >= self._min_execution_hours,
            next_block_compliant=self._next_block_compliant,
            coverage_compliant=self._coverage_compliant,
            proactive_extension_triggered=self._proactive_extension_triggered,
            evaluation_interval_seconds=self._eval_interval_s,
            store_entry_count=store_count,
        )

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def evaluate_once(self) -> None:
        """Evaluate horizon depths and extend if below policy thresholds.

        Safe to call from any thread.  Does not block on I/O (all
        extension calls are synchronous to the planning pipeline).
        """
        now = self._clock.now_utc()
        now_ms = int(now.timestamp() * 1000)
        self._last_evaluation_utc_ms = now_ms
        self._proactive_extension_triggered = False

        current_bd = self._broadcast_date_for(now)

        # --- EPG depth ---
        epg_end_ms = self.epg_window_end_utc_ms
        epg_depth_h = max(0.0, (epg_end_ms - now_ms) / 3_600_000.0)
        min_epg_h = self._min_epg_days * 24.0

        extended = False

        if epg_depth_h < min_epg_h:
            self._extend_epg(current_bd, now_ms)
            extended = True

        # --- Execution depth ---
        exec_depth_h = max(0.0, (self._execution_window_end_utc_ms - now_ms) / 3_600_000.0)

        if exec_depth_h < self._min_execution_hours:
            self._extend_execution(current_bd, now_ms)
            extended = True

        # --- Next block readiness (INV-HORIZON-NEXT-BLOCK-READY-001) ---
        if self._execution_store is not None:
            self._check_next_block_ready(now_ms, current_bd)

        # --- Seam contiguity (INV-HORIZON-CONTINUOUS-COVERAGE-001) ---
        if self._execution_store is not None:
            self._check_seam_contiguity()

        # --- Proactive extension (INV-HORIZON-PROACTIVE-EXTEND-001) ---
        self._check_proactive_extend(now_ms, current_bd)

        # --- Structured status log ---
        # Healthy + no extension = steady state → DEBUG (avoid log noise).
        # Unhealthy or extension occurred = actionable → WARNING/INFO.
        report = self.get_health_report()
        if not report.is_healthy:
            level = logging.WARNING
        elif extended:
            level = logging.INFO
        else:
            level = logging.DEBUG
        self._logger.log(
            level,
            "HorizonManager: healthy=%s epg=%.1fh (%.1fd, %s) "
            "exec=%.1fh min_epg=%dd min_exec=%dh "
            "store_entries=%d extended=%s",
            report.is_healthy,
            report.epg_depth_hours,
            report.epg_depth_hours / 24.0,
            "compliant" if report.epg_compliant else "BELOW_THRESHOLD",
            report.execution_depth_hours,
            report.min_epg_days,
            report.min_execution_hours,
            report.store_entry_count,
            extended,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background evaluation thread."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="HorizonManager",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "HorizonManager: started (interval=%ds)", self._eval_interval_s,
        )

    def stop(self) -> None:
        """Stop the background evaluation thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._eval_interval_s + 5)
            self._thread = None
        self._logger.info("HorizonManager: stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Background loop: evaluate → sleep → repeat."""
        while not self._stop_event.is_set():
            try:
                self.evaluate_once()
            except Exception:
                self._logger.exception("HorizonManager: evaluation failed")
            self._stop_event.wait(timeout=self._eval_interval_s)

    def _broadcast_date_for(self, dt: datetime) -> date:
        """Determine which broadcast day a wall-clock time falls in."""
        if dt.hour < self._day_start_hour:
            return (dt - timedelta(days=1)).date()
        return dt.date()

    def _day_end_utc_ms(self, broadcast_date: date) -> int:
        """End of a broadcast day (next calendar day at start hour) in epoch ms."""
        end_dt = datetime(
            broadcast_date.year,
            broadcast_date.month,
            broadcast_date.day,
            self._day_start_hour, 0, 0,
            tzinfo=timezone.utc,
        ) + timedelta(days=1)
        return int(end_dt.timestamp() * 1000)

    def _now_utc_ms(self) -> int:
        return int(self._clock.now_utc().timestamp() * 1000)

    def _allocate_generation_id(self) -> int:
        """Return a monotonically increasing generation_id for atomic publish."""
        self._next_generation_id += 1
        return self._next_generation_id

    def _extend_epg(self, current_bd: date, now_ms: int) -> None:
        """Extend EPG horizon until depth meets min_epg_days."""
        target_end_ms = now_ms + self._min_epg_days * 24 * 3_600_000

        if self._epg_farthest_date is not None:
            next_date = self._epg_farthest_date + timedelta(days=1)
        else:
            next_date = current_bd

        days_extended = 0
        while (self.epg_window_end_utc_ms < target_end_ms
               and days_extended < _MAX_EXTENSION_DAYS):
            if not self._schedule_manager.epg_day_exists(next_date):
                self._logger.info(
                    "HorizonManager: extending EPG → %s",
                    next_date.isoformat(),
                )
                self._schedule_manager.extend_epg_day(next_date)
            self._epg_farthest_date = next_date
            next_date = next_date + timedelta(days=1)
            days_extended += 1

    def _extend_execution(self, current_bd: date, now_ms: int) -> None:
        """Extend execution horizon until depth meets min_execution_hours."""
        target_end_ms = now_ms + self._min_execution_hours * 3_600_000

        if self._execution_window_end_utc_ms > 0:
            # Find the next broadcast date after current coverage
            end_dt = datetime.fromtimestamp(
                self._execution_window_end_utc_ms / 1000.0,
                tz=timezone.utc,
            )
            next_date = self._broadcast_date_for(end_dt)
            # If current coverage already includes this day's end, move to next
            if self._day_end_utc_ms(next_date) <= self._execution_window_end_utc_ms:
                next_date = next_date + timedelta(days=1)
        else:
            next_date = current_bd

        days_extended = 0
        while (self._execution_window_end_utc_ms < target_end_ms
               and days_extended < _MAX_EXTENSION_DAYS):
            window_end_before = self._execution_window_end_utc_ms
            self._extension_attempt_count += 1
            attempt_id = f"ext-{self._extension_attempt_count}"

            self._logger.info(
                "HorizonManager: extending execution → %s",
                next_date.isoformat(),
            )

            try:
                result = self._planning_pipeline.extend_execution_day(next_date)
            except Exception as exc:
                error_code = getattr(exc, "error_code", str(exc))
                attempt = ExtensionAttempt(
                    attempt_id=attempt_id,
                    now_utc_ms=now_ms,
                    window_end_before_ms=window_end_before,
                    window_end_after_ms=self._execution_window_end_utc_ms,
                    reason_code="REASON_TIME_THRESHOLD",
                    triggered_by="SCHED_MGR_POLICY",
                    success=False,
                    error_code=error_code,
                )
                self._extension_attempt_log.append(attempt)
                self._logger.warning(
                    "HorizonManager: pipeline failure for %s: %s",
                    next_date.isoformat(), error_code,
                )
                break

            # Duck-type: result is int (legacy) or has .end_utc_ms + .entries
            if isinstance(result, int):
                end_ms = result
            else:
                end_ms = result.end_utc_ms
                if self._execution_store is not None and hasattr(result, "entries"):
                    self._execution_store.add_entries(result.entries)

            if end_ms > self._execution_window_end_utc_ms:
                self._execution_window_end_utc_ms = end_ms

            self._extension_success_count += 1
            attempt = ExtensionAttempt(
                attempt_id=attempt_id,
                now_utc_ms=now_ms,
                window_end_before_ms=window_end_before,
                window_end_after_ms=self._execution_window_end_utc_ms,
                reason_code="REASON_TIME_THRESHOLD",
                triggered_by="SCHED_MGR_POLICY",
                success=True,
            )
            self._extension_attempt_log.append(attempt)

            next_date = next_date + timedelta(days=1)
            days_extended += 1

    def _check_next_block_ready(self, now_ms: int, current_bd: date) -> None:
        """Verify block at 'now' is present (INV-HORIZON-NEXT-BLOCK-READY-001).

        If the block is missing and the gap falls inside the locked window,
        the violation is attributed to INV-HORIZON-LOCKED-IMMUTABLE-001.
        If the block is missing and the gap is outside the locked window,
        a pipeline fill is attempted.
        """
        store = self._execution_store
        entry = store.get_entry_at(now_ms)
        if entry is not None:
            self._next_block_compliant = True
            return

        # Block missing — determine if gap is in locked window
        if self._locked_window_ms > 0:
            locked_end = now_ms + self._locked_window_ms
            # now_ms is always inside [now, now + locked_window), so the gap
            # at now_ms is within the locked window.
            window_end_before = self._execution_window_end_utc_ms
            self._extension_attempt_count += 1
            attempt_id = f"ext-{self._extension_attempt_count}"
            attempt = ExtensionAttempt(
                attempt_id=attempt_id,
                now_utc_ms=now_ms,
                window_end_before_ms=window_end_before,
                window_end_after_ms=window_end_before,
                reason_code="REASON_TIME_THRESHOLD",
                triggered_by="SCHED_MGR_POLICY",
                success=False,
                error_code="INV-HORIZON-LOCKED-IMMUTABLE-001-VIOLATED",
            )
            self._extension_attempt_log.append(attempt)
            self._next_block_compliant = False
            self._logger.warning(
                "HorizonManager: next-block gap at now=%d is inside "
                "locked window [%d, %d) — cannot fill",
                now_ms, now_ms, locked_end,
            )
            return

        # Gap outside locked window — attempt pipeline fill
        window_end_before = self._execution_window_end_utc_ms
        self._extension_attempt_count += 1
        attempt_id = f"ext-{self._extension_attempt_count}"

        try:
            result = self._planning_pipeline.extend_execution_day(current_bd)
        except Exception as exc:
            error_code = getattr(exc, "error_code", str(exc))
            attempt = ExtensionAttempt(
                attempt_id=attempt_id,
                now_utc_ms=now_ms,
                window_end_before_ms=window_end_before,
                window_end_after_ms=self._execution_window_end_utc_ms,
                reason_code="REASON_TIME_THRESHOLD",
                triggered_by="SCHED_MGR_POLICY",
                success=False,
                error_code="PIPELINE_EXHAUSTED",
            )
            self._extension_attempt_log.append(attempt)
            self._next_block_compliant = False
            self._logger.warning(
                "HorizonManager: next-block fill failed for %s: %s",
                current_bd.isoformat(), error_code,
            )
            return

        # Pipeline succeeded — ingest entries and update window end
        if isinstance(result, int):
            end_ms = result
        else:
            end_ms = result.end_utc_ms
            if hasattr(result, "entries"):
                store.add_entries(result.entries)

        if end_ms > self._execution_window_end_utc_ms:
            self._execution_window_end_utc_ms = end_ms

        # Recheck: does the store now have a block at now_ms?
        entry = store.get_entry_at(now_ms)
        if entry is not None:
            self._extension_success_count += 1
            attempt = ExtensionAttempt(
                attempt_id=attempt_id,
                now_utc_ms=now_ms,
                window_end_before_ms=window_end_before,
                window_end_after_ms=self._execution_window_end_utc_ms,
                reason_code="REASON_TIME_THRESHOLD",
                triggered_by="SCHED_MGR_POLICY",
                success=True,
            )
            self._extension_attempt_log.append(attempt)
            self._next_block_compliant = True
        else:
            attempt = ExtensionAttempt(
                attempt_id=attempt_id,
                now_utc_ms=now_ms,
                window_end_before_ms=window_end_before,
                window_end_after_ms=self._execution_window_end_utc_ms,
                reason_code="REASON_TIME_THRESHOLD",
                triggered_by="SCHED_MGR_POLICY",
                success=False,
                error_code="PIPELINE_EXHAUSTED",
            )
            self._extension_attempt_log.append(attempt)
            self._next_block_compliant = False

    def _check_seam_contiguity(self) -> None:
        """Validate all adjacent entries are contiguous (INV-HORIZON-CONTINUOUS-COVERAGE-001).

        For every adjacent pair (E_i, E_{i+1}), E_i.end_utc_ms must equal
        E_{i+1}.start_utc_ms exactly.  Violations are recorded as SeamViolation
        and logged as planning faults.
        """
        store = self._execution_store
        entries = store.get_all_entries()  # already sorted by start_utc_ms
        if len(entries) < 2:
            self._coverage_compliant = True
            self._seam_violations = []
            return

        violations: list[SeamViolation] = []
        for i in range(len(entries) - 1):
            left = entries[i]
            right = entries[i + 1]
            delta = right.start_utc_ms - left.end_utc_ms
            if delta != 0:
                v = SeamViolation(
                    left_block_id=left.block_id,
                    left_end_utc_ms=left.end_utc_ms,
                    right_block_id=right.block_id,
                    right_start_utc_ms=right.start_utc_ms,
                    delta_ms=delta,
                )
                violations.append(v)
                kind = "gap" if delta > 0 else "overlap"
                self._logger.warning(
                    "INV-HORIZON-CONTINUOUS-COVERAGE-001-VIOLATED: "
                    "%s of %d ms between %s (end=%d) and %s (start=%d)",
                    kind, abs(delta),
                    left.block_id, left.end_utc_ms,
                    right.block_id, right.start_utc_ms,
                )

        self._seam_violations = violations
        self._coverage_compliant = len(violations) == 0

    def _check_proactive_extend(self, now_ms: int, current_bd: date) -> None:
        """Proactive extension when remaining horizon crosses watermark (INV-HORIZON-PROACTIVE-EXTEND-001).

        If proactive_extend_threshold_ms == 0, this check is disabled.
        If remaining horizon > threshold, no action.
        If remaining <= threshold, attempt a single extension.
        """
        if self._proactive_extend_threshold_ms <= 0:
            return

        remaining_ms = self._execution_window_end_utc_ms - now_ms
        if remaining_ms > self._proactive_extend_threshold_ms:
            return

        # Remaining is at or below watermark — attempt one extension
        self._proactive_extension_triggered = True

        # Determine next broadcast date to extend
        if self._execution_window_end_utc_ms > 0:
            end_dt = datetime.fromtimestamp(
                self._execution_window_end_utc_ms / 1000.0,
                tz=timezone.utc,
            )
            next_date = self._broadcast_date_for(end_dt)
            if self._day_end_utc_ms(next_date) <= self._execution_window_end_utc_ms:
                next_date = next_date + timedelta(days=1)
        else:
            next_date = current_bd

        window_end_before = self._execution_window_end_utc_ms
        self._extension_attempt_count += 1
        attempt_id = f"ext-{self._extension_attempt_count}"

        self._logger.info(
            "HorizonManager: proactive extension → %s "
            "(remaining=%dms, threshold=%dms)",
            next_date.isoformat(), remaining_ms,
            self._proactive_extend_threshold_ms,
        )

        try:
            result = self._planning_pipeline.extend_execution_day(next_date)
        except Exception as exc:
            error_code = getattr(exc, "error_code", str(exc))
            attempt = ExtensionAttempt(
                attempt_id=attempt_id,
                now_utc_ms=now_ms,
                window_end_before_ms=window_end_before,
                window_end_after_ms=self._execution_window_end_utc_ms,
                reason_code="REASON_TIME_THRESHOLD",
                triggered_by="SCHED_MGR_POLICY",
                success=False,
                error_code=error_code,
            )
            self._extension_attempt_log.append(attempt)
            self._logger.warning(
                "HorizonManager: proactive extension failed for %s: %s",
                next_date.isoformat(), error_code,
            )
            return

        # Ingest result via atomic publish (INV-HORIZON-PROACTIVE-EXTEND-001)
        if isinstance(result, int):
            end_ms = result
        else:
            end_ms = result.end_utc_ms
            if self._execution_store is not None and hasattr(result, "entries") and result.entries:
                gen_id = self._allocate_generation_id()
                pub = self._execution_store.publish_atomic_replace(
                    range_start_ms=result.entries[0].start_utc_ms,
                    range_end_ms=end_ms,
                    new_entries=result.entries,
                    generation_id=gen_id,
                    reason_code="REASON_TIME_THRESHOLD",
                )
                if not pub.ok:
                    attempt = ExtensionAttempt(
                        attempt_id=attempt_id,
                        now_utc_ms=now_ms,
                        window_end_before_ms=window_end_before,
                        window_end_after_ms=self._execution_window_end_utc_ms,
                        reason_code="REASON_TIME_THRESHOLD",
                        triggered_by="SCHED_MGR_POLICY",
                        success=False,
                        error_code=pub.error_code,
                    )
                    self._extension_attempt_log.append(attempt)
                    self._logger.warning(
                        "HorizonManager: proactive atomic publish rejected: %s",
                        pub.error_code,
                    )
                    return

        if end_ms > self._execution_window_end_utc_ms:
            self._execution_window_end_utc_ms = end_ms

        self._extension_success_count += 1
        attempt = ExtensionAttempt(
            attempt_id=attempt_id,
            now_utc_ms=now_ms,
            window_end_before_ms=window_end_before,
            window_end_after_ms=self._execution_window_end_utc_ms,
            reason_code="REASON_TIME_THRESHOLD",
            triggered_by="SCHED_MGR_POLICY",
            success=True,
        )
        self._extension_attempt_log.append(attempt)
