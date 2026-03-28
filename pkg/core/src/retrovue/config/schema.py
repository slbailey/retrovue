"""
Schema validation for config/defaults.yaml and channel YAML files.

Uses Pydantic v2 for structural + type validation. Provides clear error
messages with YAML path, expected type, actual value, and context.

Integration point: called by config_loader (defaults) and resolver (channel)
before merge, so invalid data never reaches runtime components.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator


# ============================================================================
# defaults.yaml schema
# ============================================================================

class _Strict(BaseModel):
    """Base with strict config: no extra fields, validate assignment."""
    model_config = ConfigDict(extra="forbid")


# --- scheduling ---

class SchedulingHorizon(_Strict):
    days: int
    recompile_threshold_hours: int

class SchedulingResolver(_Strict):
    ttl_seconds: float

class SchedulingGridMinutes(_Strict):
    network_television: int
    premium_movie: int

class SchedulingBlockDefaults(_Strict):
    slots: int
    grid_blocks: int
    progression: str
    exhaustion_policy: str
    fill_mode: str
    bleed: bool
    schedule_layer: str
    start_time: str

class SchedulingSchema(_Strict):
    broadcast_day_start_hour: int
    grid_minutes: SchedulingGridMinutes
    epg_grid_minutes: int
    default_template: str
    default_channel_type: str
    default_timezone: str
    compiler_seed: int | None
    compiler_version: str
    horizon: SchedulingHorizon
    resolver: SchedulingResolver
    block_defaults: SchedulingBlockDefaults
    frame_tolerance_ms: int
    default_fps_numerator: int
    default_fps_denominator: int


# --- playout ---

class PlayoutTiming(_Strict):
    min_prefeed_lead_time_ms: int
    startup_latency_seconds: int | float
    scheduling_buffer_seconds: float

class PlayoutPace(_Strict):
    target_hz: float
    max_frame_multiplier: float

class PlayoutBreaks(_Strict):
    default_count: int

class PlayoutTransitions(_Strict):
    default_fade_duration_ms: int
    default_type: str
    default_duration_ms: int

class PlayoutGrpc(_Strict):
    readiness_timeout_seconds: float
    version_timeout_seconds: float
    retry_interval_seconds: float
    attach_stream_timeout_seconds: float
    start_session_timeout_seconds: float
    feed_timeout_seconds: float
    stop_session_timeout_seconds: float
    air_termination_timeout_seconds: float
    event_thread_join_timeout_seconds: float

class PlayoutSchema(_Strict):
    timing: PlayoutTiming
    pace: PlayoutPace
    breaks: PlayoutBreaks
    transitions: PlayoutTransitions
    default_gain_db: float
    grpc: PlayoutGrpc


# --- channel ---

class ChannelRecovery(_Strict):
    base_delay_seconds: float
    max_attempts: int
    error_backoff_max_ticks: int

class ChannelQueue(_Strict):
    depth: int

class ChannelDiagnostics(_Strict):
    duration_seconds: float
    ring_max_events: int

class ChannelStartup(_Strict):
    max_workers: int
    concurrency: int

class ChannelEvidence(_Strict):
    enabled: bool
    port: int
    asrun_dir: str
    ack_dir: str
    segment_cache_max: int

class ChannelEncoding(_Strict):
    video_bitrate_bps: int
    aspect_policy: str
    blockplan_only: bool

class ChannelDefaultProgramFormat(_Strict):
    width: int
    height: int
    frame_rate: str
    sample_rate: int
    audio_channels: int
    aspect_policy: str

class ChannelFiller(_Strict):
    path: str
    duration_ms: int
    alignment: Literal["start", "end"]

class ChannelSchema(_Strict):
    linger_seconds: int
    teardown_timeout_seconds: float
    mock_grid_block_minutes: int
    default_filler_duration_seconds: float
    default_segment_seconds: float
    recovery: ChannelRecovery
    queue: ChannelQueue
    health_check_interval_seconds: float
    diagnostics: ChannelDiagnostics
    startup: ChannelStartup
    evidence: ChannelEvidence
    encoding: ChannelEncoding
    default_program_format: ChannelDefaultProgramFormat
    filler: ChannelFiller


# --- hls ---

class HlsSegmenter(_Strict):
    target_duration_ms: int
    max_gop_ms: int
    max_plausible_pcr_ticks: int

class HlsRing(_Strict):
    capacity: int
    manifest_window: int

class HlsSession(_Strict):
    timeout_ms: int
    reap_interval_ms: int

class HlsSchema(_Strict):
    segmenter: HlsSegmenter
    ring: HlsRing
    session: HlsSession


# --- streaming ---

class StreamingBuffers(_Strict):
    client_buffer_bytes: int
    ring_buffer_max_bytes: int
    min_client_buffer_bytes: int
    uds_rcvbuf_bytes: int

class StreamingChunks(_Strict):
    read_chunk_bytes: int
    legacy_chunk_bytes: int
    drain_max_bytes: int

class StreamingBackpressure(_Strict):
    policy: str
    slow_threshold_seconds: float
    log_interval_seconds: float

class StreamingSlowClient(_Strict):
    put_timeout_seconds: float

class StreamingFfmpeg(_Strict):
    read_from_files_live: bool
    probe_size: str
    analyze_duration: str
    enable_resend_headers: bool
    enable_initial_discontinuity: bool

class StreamingSchema(_Strict):
    buffers: StreamingBuffers
    chunks: StreamingChunks
    drain_timeout_seconds: float
    upstream_poll_timeout_seconds: float
    backpressure: StreamingBackpressure
    slow_client: StreamingSlowClient
    ffmpeg: StreamingFfmpeg


# --- system ---

class SystemPorts(_Strict):
    program_director: int
    channel_manager: int

class SystemPaths(_Strict):
    schedules_dir: str
    channels_dir: str
    sqlite_path: str
    sidecar_schema: str

class SystemDatabase(_Strict):
    pool_size: int
    max_overflow: int
    pool_timeout_seconds: int
    connect_timeout_seconds: int

class SystemMetrics(_Strict):
    sample_hz: float
    aggregation_window_seconds: float

class SystemEnrichment(_Strict):
    loudness_max_supplement_db: float
    loudness_timeout_seconds: int
    ffprobe_timeout_seconds: int
    max_content_duration_ms: int

class SystemTraffic(_Strict):
    default_cooldown_seconds: int
    max_plays_per_day: int

class SystemPlaylistBuilder(_Strict):
    warn_on_first_missing_playlog_plan_only: bool

class SystemSchema(_Strict):
    ports: SystemPorts
    paths: SystemPaths
    database: SystemDatabase
    log_level: str
    environment: str
    processor_job_retention_days: int
    metrics: SystemMetrics
    enrichment: SystemEnrichment
    traffic: SystemTraffic
    playlist_builder: SystemPlaylistBuilder


# --- integrations ---

class IntegrationsPlex(_Strict):
    device_id: str
    friendly_name: str
    tuner_count: int
    firmware_version: str

class IntegrationsIptv(_Strict):
    default_timezone: str

class IntegrationsSchema(_Strict):
    plex: IntegrationsPlex
    iptv: IntegrationsIptv


# --- air ---

class AirGrpc(_Strict):
    bind_address: str
    enable_reflection: bool

class AirBuffers(_Strict):
    default_frames: int
    min_video_depth: int
    min_depth_for_drop: int
    min_audio_seam_ms: int

class AirPrefeed(_Strict):
    min_lead_time_ms: int
    max_poll_attempts: int

class AirTick(_Strict):
    max_null_run: int
    max_total_decodes: int
    max_prime_wallclock_ms: int

class AirPipeline(_Strict):
    min_audio_prime_ms: int
    min_segment_swap_audio_ms: int
    min_segment_swap_video_frames: int
    min_segment_prep_headroom_ms: int
    min_segment_prep_headroom_frames: int
    max_wait_ms: int

class AirProducer(_Strict):
    max_audio_frames_per_tick: int
    max_opportunistic_drain_frames: int
    max_media_duration_hours: int

class AirDecoder(_Strict):
    max_pending_audio_frames: int
    max_eagain_retries: int

class AirEvidence(_Strict):
    spool_root: str
    flush_interval_ms: int
    flush_records_max: int
    max_spool_bytes: int
    schema_version: int
    max_backoff_ms: int

class AirSchema(_Strict):
    grpc: AirGrpc
    metrics_port: int
    api_version: str
    buffers: AirBuffers
    prefeed: AirPrefeed
    tick: AirTick
    pipeline: AirPipeline
    producer: AirProducer
    decoder: AirDecoder
    evidence: AirEvidence


# ============================================================================
# Top-level defaults schema
# ============================================================================

class DefaultsSchema(_Strict):
    """Complete schema for config/defaults.yaml."""
    scheduling: SchedulingSchema
    playout: PlayoutSchema
    channel: ChannelSchema
    hls: HlsSchema
    streaming: StreamingSchema
    system: SystemSchema
    integrations: IntegrationsSchema
    air: AirSchema


# ============================================================================
# Channel YAML schema (identifiers + pass-through + optional overrides)
# ============================================================================

class ChannelFormatVideo(BaseModel):
    """Channel format.video section (pass-through, minimal validation)."""
    model_config = ConfigDict(extra="allow")
    width: int | None = None
    height: int | None = None
    frame_rate: str | None = None
    aspect_policy: str | None = None

class ChannelFormatAudio(BaseModel):
    """Channel format.audio section (pass-through, minimal validation)."""
    model_config = ConfigDict(extra="allow")
    sample_rate: int | None = None
    channels: int | None = None

class ChannelFormat(BaseModel):
    """Channel format section (pass-through, minimal structure check)."""
    model_config = ConfigDict(extra="allow")
    video: ChannelFormatVideo | None = None
    audio: ChannelFormatAudio | None = None
    grid_minutes: int | None = None

class ChannelFillerYaml(BaseModel):
    """Channel filler section (pass-through)."""
    model_config = ConfigDict(extra="forbid")
    path: str | None = None
    duration_ms: int | None = None
    alignment: Literal["start", "end"] | None = None

class ChannelYamlSchema(BaseModel):
    """
    Schema for channel YAML files.

    Validates identifiers (required) and structural correctness of
    pass-through sections.  Does NOT validate the content of pools,
    programs, schedule, or traffic — those are governed by their own
    contracts.
    """
    model_config = ConfigDict(extra="allow")

    # --- identifiers (one of channel_id or channel required) ---
    channel_id: str | None = None
    channel: str | None = None  # legacy, maps to channel_id
    number: int | None = None
    channel_number: int | None = None  # legacy, maps to number
    name: str | None = None
    channel_type: str | None = None
    timezone: str | None = None

    # --- pass-through (structural check only) ---
    format: ChannelFormat | None = None
    filler: ChannelFillerYaml | None = None
    pools: dict[str, Any] | None = None
    programs: dict[str, Any] | None = None
    schedule: dict[str, Any] | None = None
    traffic: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _require_identifiers(self) -> "ChannelYamlSchema":
        if not self.channel_id and not self.channel:
            raise ValueError(
                "channel YAML must contain 'channel_id' (or legacy 'channel') — "
                "this is the unique channel identifier"
            )
        if self.number is None and self.channel_number is None:
            raise ValueError(
                "channel YAML must contain 'number' (or legacy 'channel_number') — "
                "positive integer required for Plex GuideNumber"
            )
        effective_number = self.number if self.number is not None else self.channel_number
        if not isinstance(effective_number, int) or effective_number < 1:
            raise ValueError(
                f"channel number must be a positive integer, got {effective_number!r}"
            )
        return self


# ============================================================================
# Public validation API
# ============================================================================

class SchemaValidationError(Exception):
    """Raised when schema validation fails.

    Attributes:
        errors: List of individual validation error dicts with loc, msg, type.
    """

    def __init__(self, message: str, errors: list[dict[str, Any]]):
        super().__init__(message)
        self.errors = errors


def validate_defaults(data: dict[str, Any]) -> None:
    """Validate a parsed defaults.yaml dict against the schema.

    Raises SchemaValidationError with detailed per-field errors.
    """
    try:
        DefaultsSchema.model_validate(data)
    except ValidationError as exc:
        raise SchemaValidationError(
            f"defaults.yaml schema validation failed ({exc.error_count()} errors)",
            errors=_format_errors(exc),
        ) from exc


def validate_channel_yaml(data: dict[str, Any]) -> None:
    """Validate a parsed channel YAML dict against the schema.

    Validates identifiers and structural correctness. Does NOT validate
    pools/programs/schedule/traffic content.

    Raises SchemaValidationError with detailed per-field errors.
    """
    try:
        ChannelYamlSchema.model_validate(data)
    except ValidationError as exc:
        raise SchemaValidationError(
            f"channel YAML schema validation failed ({exc.error_count()} errors)",
            errors=_format_errors(exc),
        ) from exc


def _format_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Convert Pydantic ValidationError into a list of error dicts.

    Each dict has:
        path:     dotted YAML path (e.g. "scheduling.horizon.days")
        message:  human-readable error description
        type:     Pydantic error type code
        input:    the actual value that failed validation
    """
    result = []
    for err in exc.errors():
        loc = err.get("loc", ())
        result.append({
            "path": ".".join(str(part) for part in loc),
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
            "input": err.get("input"),
        })
    return result


__all__ = [
    "DefaultsSchema",
    "ChannelYamlSchema",
    "SchemaValidationError",
    "validate_defaults",
    "validate_channel_yaml",
]
