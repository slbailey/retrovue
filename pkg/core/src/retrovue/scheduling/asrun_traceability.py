"""AsRun traceability validation.

Enforces INV-ASRUN-TRACEABILITY-001: every AsRun entry must be traceable
through the full derivation chain back to a SchedulePlan.

Chain: AsRun → ExecutionEntry → TransmissionLogEntry → ResolvedScheduleDay → SchedulePlan
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AsRunEntry:
    """One as-run record — what actually aired.

    Immutable once created (frozen=True).
    """

    asrun_id: str
    channel_id: str
    start_utc_ms: int
    end_utc_ms: int
    asset_path: str
    execution_entry_id: str | None  # ref to ExecutionEntry
    is_operator_override: bool = False


@dataclass(frozen=True)
class DerivationChainLink:
    """One link in the derivation chain for audit traversal."""

    asrun_id: str
    execution_entry_id: str
    transmission_log_ref: str
    schedule_day_date: str
    plan_id: str


def validate_asrun_traceability(entry: AsRunEntry) -> None:
    """Validate INV-ASRUN-TRACEABILITY-001 at creation time.

    An AsRun entry MUST reference an ExecutionEntry. Entries without
    an execution_entry_id are rejected unless they are operator overrides
    (which still need the override ExecutionEntry reference).

    Raises ValueError on violation.
    """
    if not entry.execution_entry_id:
        raise ValueError(
            f"INV-ASRUN-TRACEABILITY-001-VIOLATED: "
            f"AsRun entry {entry.asrun_id} has no execution_entry_id. "
            f"Every AsRun record must reference the ExecutionEntry that "
            f"authorized the broadcast."
        )


def traverse_derivation_chain(
    *,
    asrun: AsRunEntry,
    execution_entry_id: str,
    transmission_log_ref: str,
    schedule_day_date: str,
    plan_id: str,
) -> DerivationChainLink:
    """Traverse and validate the full derivation chain.

    Returns a DerivationChainLink if all links are valid.
    Raises ValueError if any link is broken.
    """
    if not asrun.execution_entry_id:
        raise ValueError(
            f"INV-ASRUN-TRACEABILITY-001-VIOLATED: "
            f"AsRun {asrun.asrun_id} → ExecutionEntry link broken (null)"
        )
    if not execution_entry_id:
        raise ValueError(
            f"INV-ASRUN-TRACEABILITY-001-VIOLATED: "
            f"ExecutionEntry link is null"
        )
    if not transmission_log_ref:
        raise ValueError(
            f"INV-ASRUN-TRACEABILITY-001-VIOLATED: "
            f"ExecutionEntry → TransmissionLog link broken (null)"
        )
    if not schedule_day_date:
        raise ValueError(
            f"INV-ASRUN-TRACEABILITY-001-VIOLATED: "
            f"TransmissionLog → ScheduleDay link broken (null)"
        )
    if not plan_id:
        raise ValueError(
            f"INV-ASRUN-TRACEABILITY-001-VIOLATED: "
            f"ScheduleDay → SchedulePlan link broken (null)"
        )

    return DerivationChainLink(
        asrun_id=asrun.asrun_id,
        execution_entry_id=execution_entry_id,
        transmission_log_ref=transmission_log_ref,
        schedule_day_date=schedule_day_date,
        plan_id=plan_id,
    )
