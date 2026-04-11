"""Foreign content validation across the scheduling derivation chain.

Enforces INV-NO-FOREIGN-CONTENT-001: no artifact at any layer may
reference an asset that cannot be traced to the upstream authority.

Validation functions for each layer:
  - ScheduleDay slots → must trace to SchedulePlan zone assets
  - TransmissionLogEntry → must trace to ResolvedScheduleDay slots
  - ExecutionEntry → must trace to TransmissionLogEntry
"""

from __future__ import annotations

from retrovue.scheduling.execution_entry import ExecutionEntry
from retrovue.scheduling.transmission_log import TransmissionLogEntry


def validate_scheduleday_assets(
    *,
    slot_asset_ids: list[str],
    plan_asset_ids: set[str],
) -> None:
    """Validate that all ScheduleDay slot asset references exist in the
    generating SchedulePlan's zone assets.

    Raises ValueError if any slot references a foreign asset.
    """
    for asset_id in slot_asset_ids:
        if asset_id not in plan_asset_ids:
            raise ValueError(
                f"INV-NO-FOREIGN-CONTENT-001-VIOLATED: "
                f"ScheduleDay slot references asset '{asset_id}' "
                f"which is absent from the generating SchedulePlan zones"
            )


def validate_transmission_log_assets(
    *,
    tl_entries: list[TransmissionLogEntry],
    scheduleday_asset_ids: set[str],
) -> None:
    """Validate that all TransmissionLogEntry asset references exist in
    the source ResolvedScheduleDay.

    Raises ValueError if any entry references a foreign asset.
    """
    for entry in tl_entries:
        if entry.asset_id and entry.asset_id not in scheduleday_asset_ids:
            raise ValueError(
                f"INV-NO-FOREIGN-CONTENT-001-VIOLATED: "
                f"TransmissionLogEntry '{entry.entry_id}' references asset "
                f"'{entry.asset_id}' which is absent from the source "
                f"ResolvedScheduleDay"
            )


def validate_execution_entry_assets(
    *,
    exec_entries: list[ExecutionEntry],
    transmission_log_asset_paths: set[str],
) -> None:
    """Validate that all ExecutionEntry asset references exist in the
    source TransmissionLog (via asset_path).

    Raises ValueError if any entry references a foreign asset.
    Only non-override entries are validated.
    """
    for entry in exec_entries:
        if entry.is_operator_override:
            continue
        if entry.asset_path not in transmission_log_asset_paths:
            raise ValueError(
                f"INV-NO-FOREIGN-CONTENT-001-VIOLATED: "
                f"ExecutionEntry '{entry.entry_id}' references asset path "
                f"'{entry.asset_path}' which is absent from the source "
                f"TransmissionLog entries"
            )
