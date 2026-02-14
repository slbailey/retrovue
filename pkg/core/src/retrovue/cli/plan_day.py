"""
Deterministic planning CLI entry point.

Runs planning pipeline for one channel + one broadcast day: pipeline,
seam validation, transmission log lock, artifact write. No execution,
scheduler daemon, or evidence server.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path

from retrovue.catalog.static_asset_library import StaticAssetLibrary
from retrovue.planning.transmission_log_artifact_writer import (
    TransmissionLogArtifactExistsError,
    TransmissionLogArtifactWriter,
)
from retrovue.runtime.clock import RealTimeMasterClock
from retrovue.runtime.planning_pipeline import (
    PlanningDirective,
    PlanningRunRequest,
    ZoneDirective,
    lock_transmission_log,
    run_planning_pipeline,
)
from retrovue.runtime.schedule_manager_service import (
    InMemoryResolvedStore,
    InMemorySequenceStore,
    JsonFileProgramCatalog,
    ScheduleManagerBackedScheduleService,
)
from retrovue.runtime.schedule_types import ScheduleManagerConfig
from retrovue.runtime.transmission_log_validator import TransmissionLogSeamError


# Default paths (same as ProgramDirector / contract)
DEFAULT_CHANNELS_CONFIG = Path("/opt/retrovue/config/channels.json")
DEFAULT_ARTIFACT_BASE_PATH = Path("/opt/retrovue/data/logs/transmission")
DEFAULT_ASSET_CATALOG = Path("/opt/retrovue/config/asset_catalog.json")


class PlanDayError(Exception):
    """Base for plan-day failures (unknown channel, planning error, etc.)."""


class UnknownChannelError(PlanDayError):
    """Channel not found in config."""


class InvalidDateError(PlanDayError):
    """Invalid or unparseable date."""


def plan_day(
    channel_id: str,
    broadcast_date: date,
    *,
    channels_config_path: Path = DEFAULT_CHANNELS_CONFIG,
    artifact_base_path: Path = DEFAULT_ARTIFACT_BASE_PATH,
    asset_catalog_path: Path | None = None,
) -> None:
    """
    Deterministic planning entry point.

    Runs:
        planning pipeline
        seam validation
        transmission log lock
        artifact write

    Does NOT:
        start execution
        start scheduler daemon
        modify horizon state beyond this day
    """
    from retrovue.runtime.providers.file_config_provider import FileChannelConfigProvider

    # Load channel config (same source as HorizonManager)
    config_provider = FileChannelConfigProvider(channels_config_path)
    channel_config = config_provider.get_channel_config(channel_id)
    if channel_config is None:
        raise UnknownChannelError(f"Channel '{channel_id}' not found in {channels_config_path}")

    schedule_config = channel_config.schedule_config
    programs_dir = Path(schedule_config.get("programs_dir", "/opt/retrovue/config/programs"))
    schedules_dir = Path(schedule_config.get("schedules_dir", "/opt/retrovue/config/schedules"))
    filler_path = schedule_config.get("filler_path", "/opt/retrovue/assets/filler.mp4")
    filler_duration = schedule_config.get("filler_duration_seconds", 3650.0)
    grid_minutes = schedule_config.get("grid_minutes", 30)
    programming_day_start_hour = schedule_config.get("programming_day_start_hour", 6)
    timezone_display = schedule_config.get("timezone_display", "UTC")

    # Load schedule (same loader as HorizonManager)
    clock = RealTimeMasterClock()
    service = ScheduleManagerBackedScheduleService(
        clock=clock,
        programs_dir=programs_dir,
        schedules_dir=schedules_dir,
        filler_path=filler_path,
        filler_duration_seconds=filler_duration,
        grid_minutes=grid_minutes,
        programming_day_start_hour=programming_day_start_hour,
    )
    success, error = service.load_schedule(channel_id)
    if not success:
        raise PlanDayError(f"Failed to load schedule for {channel_id}: {error}")

    slots = service.get_schedule_slots(channel_id)
    if not slots:
        raise PlanDayError(f"No schedule slots for channel {channel_id}")

    # Build directive: one zone 06:00–06:00 (full day) with programs in slot order
    programs = [s.program_ref for s in slots]
    day_start = time(programming_day_start_hour, 0)
    directive = PlanningDirective(
        channel_id=channel_id,
        grid_block_minutes=grid_minutes,
        programming_day_start_hour=programming_day_start_hour,
        zones=[
            ZoneDirective(
                start_time=day_start,
                end_time=day_start,  # same = full 24h wrap
                programs=programs,
                label="day",
            ),
        ],
    )

    # ScheduleManagerConfig for pipeline (same stores/catalog as service)
    catalog = JsonFileProgramCatalog(programs_dir)
    catalog.load_all()
    config = ScheduleManagerConfig(
        grid_minutes=grid_minutes,
        program_catalog=catalog,
        sequence_store=InMemorySequenceStore(),
        resolved_store=InMemoryResolvedStore(),
        filler_path=filler_path,
        filler_duration_seconds=filler_duration,
        programming_day_start_hour=programming_day_start_hour,
    )

    asset_path = asset_catalog_path or DEFAULT_ASSET_CATALOG
    if not asset_path.exists():
        raise PlanDayError(f"Asset catalog not found: {asset_path}")
    asset_library = StaticAssetLibrary(asset_path)

    resolution_time = datetime(
        broadcast_date.year,
        broadcast_date.month,
        broadcast_date.day,
        5,
        0,
        0,
        tzinfo=timezone.utc,
    )
    run_request = PlanningRunRequest(
        directive=directive,
        broadcast_date=broadcast_date,
        resolution_time=resolution_time,
    )

    # Run pipeline (no lock inside pipeline; we lock and write below)
    log = run_planning_pipeline(
        run_request,
        config,
        asset_library,
        lock_time=None,
    )

    lock_time = datetime(
        broadcast_date.year,
        broadcast_date.month,
        broadcast_date.day,
        5,
        30,
        0,
        tzinfo=timezone.utc,
    )
    locked = lock_transmission_log(log, lock_time)

    writer = TransmissionLogArtifactWriter(base_path=artifact_base_path)
    tlog_path = writer.write(
        channel_id=channel_id,
        broadcast_date=broadcast_date,
        transmission_log=locked,
        timezone_display=timezone_display,
        generated_utc=lock_time,
        transmission_log_id=locked.metadata.get("transmission_log_id"),
    )

    print("✔ Planning complete")
    print("✔ Transmission log locked")
    print("✔ Artifact written:")
    print(f"  {tlog_path}")
