"""
Test utilities for the configuration system.

Provides:
- make_test_config() / TEST_RESOLVED_CONFIG — in-memory frozen configs
  that satisfy the full schema without loading from disk.
- load_defaults_unvalidated() — loads a YAML file without schema
  validation, for tests that use intentionally incomplete fixtures.
- resolve_channel_unvalidated() — resolves a channel YAML against an
  unvalidated defaults file, for merge-behavior tests.

These helpers exist ONLY in retrovue.config.testing, which is a test-only
module.  Production code MUST NOT import from this module.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any

from retrovue.config.config_loader import (
    _deep_freeze,
    _load_defaults_impl,
    reset_defaults_cache,
)


def make_test_config(**overrides: Any) -> MappingProxyType[str, Any]:
    """Build a minimal frozen config for tests.

    Contains all HIGH + MEDIUM risk defaults so that runtime components
    can be instantiated without hitting fallback paths.  LOW-risk keys
    (diagnostics, logging paths) are omitted — they keep their fallbacks.

    Keyword arguments are merged into the top-level dict (shallow) so
    tests can override individual domains::

        cfg = make_test_config(channel={"linger_seconds": 5})
    """
    base: dict[str, Any] = {
        "scheduling": {
            "broadcast_day_start_hour": 6,
            "compiler_version": "3.0.0",
            "grid_minutes": {
                "network_television": 30,
                "premium_movie": 15,
            },
            "epg_grid_minutes": 30,
            "default_template": "network_television",
            "default_channel_type": "network",
            "default_timezone": "UTC",
            "compiler_seed": 42,
            "horizon": {
                "days": 3,
                "recompile_threshold_hours": 6,
            },
            "resolver": {
                "ttl_seconds": 60.0,
            },
            "block_defaults": {
                "slots": 1,
                "grid_blocks": 1,
                "progression": "sequential",
                "exhaustion_policy": "wrap",
                "fill_mode": "single",
                "bleed": False,
                "schedule_layer": "all_day",
                "start_time": "06:00",
            },
            "frame_tolerance_ms": 40,
            "default_fps_numerator": 30,
            "default_fps_denominator": 1,
        },
        "playout": {
            "timing": {
                "min_prefeed_lead_time_ms": 5000,
                "startup_latency_seconds": 7,
                "scheduling_buffer_seconds": 2.0,
            },
            "pace": {
                "target_hz": 30.0,
                "max_frame_multiplier": 3.0,
            },
            "breaks": {
                "default_count": 3,
            },
            "transitions": {
                "default_fade_duration_ms": 500,
                "default_type": "TRANSITION_NONE",
                "default_duration_ms": 0,
            },
            "default_gain_db": 0.0,
            "grpc": {
                "readiness_timeout_seconds": 10.0,
                "version_timeout_seconds": 2.0,
                "retry_interval_seconds": 0.2,
                "attach_stream_timeout_seconds": 5.0,
                "start_session_timeout_seconds": 10.0,
                "feed_timeout_seconds": 5.0,
                "stop_session_timeout_seconds": 5.0,
                "air_termination_timeout_seconds": 5.0,
                "event_thread_join_timeout_seconds": 2.0,
            },
        },
        "channel": {
            "linger_seconds": 20,
            "teardown_timeout_seconds": 5.0,
            "mock_grid_block_minutes": 30,
            "default_filler_duration_seconds": 3600.0,
            "default_segment_seconds": 10.0,
            "recovery": {
                "base_delay_seconds": 1.0,
                "max_attempts": 5,
                "error_backoff_max_ticks": 112,
            },
            "queue": {
                "depth": 3,
            },
            "health_check_interval_seconds": 1.0,
            "diagnostics": {
                "duration_seconds": 90.0,
                "ring_max_events": 512,
            },
            "startup": {
                "max_workers": 4,
                "concurrency": 4,
            },
            "evidence": {
                "enabled": False,
                "port": 50052,
                "asrun_dir": "/tmp/retrovue-test/asrun",
                "ack_dir": "/tmp/retrovue-test/acks",
                "segment_cache_max": 10,
            },
            "encoding": {
                "video_bitrate_bps": 8000000,
                "aspect_policy": "preserve",
                "blockplan_only": False,
            },
            "default_program_format": {
                "width": 1920,
                "height": 1080,
                "frame_rate": "30000/1001",
                "sample_rate": 48000,
                "audio_channels": 2,
                "aspect_policy": "preserve",
            },
            "filler": {
                "path": "/opt/retrovue/assets/filler.mp4",
                "duration_ms": 3650000,
                "alignment": "start",
            },
        },
        "hls": {
            "segmenter": {
                "target_duration_ms": 6000,
                "max_gop_ms": 1000,
                "max_plausible_pcr_ticks": 5400000,
            },
            "ring": {
                "capacity": 7,
                "manifest_window": 3,
            },
            "session": {
                "timeout_ms": 30000,
                "reap_interval_ms": 10000,
            },
        },
        "streaming": {
            "buffers": {
                "client_buffer_bytes": 4000000,
                "ring_buffer_max_bytes": 8388608,
                "min_client_buffer_bytes": 65536,
                "uds_rcvbuf_bytes": 131072,
            },
            "chunks": {
                "read_chunk_bytes": 32768,
                "legacy_chunk_bytes": 1316,
                "drain_max_bytes": 65536,
            },
            "drain_timeout_seconds": 0.1,
            "upstream_poll_timeout_seconds": 0.05,
            "backpressure": {
                "policy": "drop_oldest",
                "slow_threshold_seconds": 5.0,
                "log_interval_seconds": 5.0,
            },
            "slow_client": {
                "put_timeout_seconds": 3.0,
            },
            "diagnostics": {
                "enabled": False,
                "startup_events": 200,
                "steady_interval": 100,
                "recv_gap_warn_threshold_ms": 40,
                "recv_gap_warn_count": 10,
                "upstream_loop_spike_ms": 50.0,
            },
            "ffmpeg": {
                "read_from_files_live": True,
                "probe_size": "10M",
                "analyze_duration": "2M",
                "enable_resend_headers": True,
                "enable_initial_discontinuity": True,
            },
        },
        "system": {
            "ports": {
                "program_director": 8000,
                "channel_manager": 9000,
            },
            "paths": {
                "schedules_dir": "/tmp/retrovue-test/schedules",
                "channels_dir": "/tmp/retrovue-test/channels",
                "sqlite_path": "/tmp/retrovue-test/retrovue.db",
                "sidecar_schema": "docs/metadata/sidecar-schema.json",
            },
            "database": {
                "pool_size": 5,
                "max_overflow": 10,
                "pool_timeout_seconds": 30,
                "connect_timeout_seconds": 30,
            },
            "log_level": "INFO",
            "environment": "test",
            "processor_job_retention_days": 30,
            "metrics": {
                "sample_hz": 2.0,
                "aggregation_window_seconds": 1.0,
            },
            "enrichment": {
                "loudness_max_supplement_db": 6.0,
                "loudness_timeout_seconds": 600,
                "ffprobe_timeout_seconds": 30,
                "max_content_duration_ms": 10800000,
            },
            "traffic": {
                "default_cooldown_seconds": 3600,
                "max_plays_per_day": 0,
            },
            "playlist_builder": {
                "warn_on_first_missing_tier2_only": True,
            },
        },
        "integrations": {
            "plex": {
                "device_id": "RVUE1234",
                "friendly_name": "RetroVue",
                "tuner_count": 8,
                "firmware_version": "20200101",
            },
            "iptv": {
                "default_timezone": "America/New_York",
            },
        },
        "air": {
            "grpc": {
                "bind_address": "0.0.0.0:50051",
                "enable_reflection": True,
            },
            "metrics_port": 9308,
            "api_version": "1.0.0",
            "buffers": {
                "default_frames": 60,
                "min_video_depth": 2,
                "min_depth_for_drop": 5,
                "min_audio_seam_ms": 200,
            },
            "prefeed": {
                "min_lead_time_ms": 5000,
                "max_poll_attempts": 200,
            },
            "tick": {
                "max_null_run": 10,
                "max_total_decodes": 60,
                "max_prime_wallclock_ms": 2000,
            },
            "pipeline": {
                "min_audio_prime_ms": 500,
                "min_segment_swap_audio_ms": 500,
                "min_segment_swap_video_frames": 2,
                "min_segment_prep_headroom_ms": 250,
                "min_segment_prep_headroom_frames": 8,
                "max_wait_ms": 2000,
            },
            "producer": {
                "max_audio_frames_per_tick": 8,
                "max_opportunistic_drain_frames": 2,
                "max_media_duration_hours": 4,
            },
            "decoder": {
                "max_pending_audio_frames": 120,
                "max_eagain_retries": 4,
            },
            "evidence": {
                "spool_root": "/tmp/retrovue-test/evidence_spool",
                "flush_interval_ms": 250,
                "flush_records_max": 50,
                "max_spool_bytes": 0,
                "schema_version": 1,
                "max_backoff_ms": 5000,
            },
        },
    }

    # Apply overrides (shallow merge at top level).
    for key, value in overrides.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value

    return _deep_freeze(base)


# Pre-built instance for tests that don't need customization.
TEST_RESOLVED_CONFIG = make_test_config()


def load_defaults_unvalidated(path: str | Path) -> MappingProxyType[str, Any]:
    """Load a defaults YAML file WITHOUT schema validation.

    For tests that use intentionally incomplete or malformed fixture files
    to exercise merge behavior.  Resets the singleton cache before and after
    loading so it does not pollute other tests.

    Production code MUST NOT call this function.
    """
    reset_defaults_cache()
    try:
        return _load_defaults_impl(path, _validate=False)
    finally:
        reset_defaults_cache()


def resolve_channel_unvalidated(
    channel_path: str | Path,
    defaults_path: str | Path,
) -> MappingProxyType[str, Any]:
    """Resolve a channel YAML without schema validation on either input.

    For tests that exercise merge semantics with intentionally incomplete
    fixture files.  Resets the singleton cache before and after.

    Production code MUST NOT call this function.
    """
    import yaml
    from retrovue.config.merge import deep_merge
    from retrovue.config.config_loader import GOVERNED_DOMAINS

    reset_defaults_cache()
    try:
        defaults = _load_defaults_impl(defaults_path, _validate=False)

        channel_data = yaml.safe_load(Path(channel_path).read_text(encoding="utf-8"))
        if not isinstance(channel_data, dict):
            raise ValueError(f"Channel YAML must be a mapping: {channel_path}")

        governed_overrides: dict[str, Any] = {}
        passthrough: dict[str, Any] = {}

        for key, value in channel_data.items():
            if key in GOVERNED_DOMAINS and isinstance(value, dict):
                governed_overrides[key] = value
            else:
                passthrough[key] = value

        merged = deep_merge(defaults, governed_overrides, governed_keys=GOVERNED_DOMAINS)

        for key, value in passthrough.items():
            if key in GOVERNED_DOMAINS and key in merged:
                merged[f"{key}_id"] = value
            else:
                merged[key] = value

        return _deep_freeze(merged)
    finally:
        reset_defaults_cache()


__all__ = [
    "make_test_config",
    "TEST_RESOLVED_CONFIG",
    "load_defaults_unvalidated",
    "resolve_channel_unvalidated",
]
