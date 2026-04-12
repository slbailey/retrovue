"""
Contract tests for configuration schema validation.

Validates:
- Valid defaults.yaml passes schema
- Missing required domains → error
- Wrong types → error with path
- Extra/unknown keys → error
- Null values in non-nullable fields → error
- Valid channel YAML passes schema
- Missing channel identifiers → error
- Invalid channel number → error
- Error messages include path and helpful context
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from retrovue.config.schema import (
    SchemaValidationError,
    validate_channel_yaml,
    validate_defaults,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def valid_defaults() -> dict:
    """Load the real defaults.yaml as a dict for mutation tests."""
    p = Path("/opt/retrovue/config/defaults.yaml")
    if not p.exists():
        pytest.skip("config/defaults.yaml not present")
    return yaml.safe_load(p.read_text())


@pytest.fixture()
def valid_channel() -> dict:
    """Minimal valid channel YAML dict."""
    return {
        "channel_id": "test-ch",
        "number": 1,
        "name": "Test Channel",
    }


# ---------------------------------------------------------------------------
# defaults.yaml — valid
# ---------------------------------------------------------------------------

class TestDefaultsValid:

    def test_real_defaults_yaml_passes(self, valid_defaults: dict):
        validate_defaults(valid_defaults)  # no exception

    def test_all_required_domains_present(self, valid_defaults: dict):
        for domain in ("scheduling", "playout", "channel", "hls",
                       "streaming", "system", "integrations", "air"):
            assert domain in valid_defaults


# ---------------------------------------------------------------------------
# defaults.yaml — missing domains
# ---------------------------------------------------------------------------

class TestDefaultsMissingDomains:

    def test_missing_scheduling_raises(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        del data["scheduling"]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        assert any("scheduling" in e["path"] for e in exc_info.value.errors)

    def test_missing_channel_raises(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        del data["channel"]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        assert any("channel" in e["path"] for e in exc_info.value.errors)

    def test_missing_nested_section_raises(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        del data["channel"]["recovery"]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        assert any("recovery" in e["path"] for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# defaults.yaml — wrong types
# ---------------------------------------------------------------------------

class TestDefaultsWrongTypes:

    def test_string_where_int_expected(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["scheduling"]["broadcast_day_start_hour"] = "six"
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        errs = exc_info.value.errors
        assert any("broadcast_day_start_hour" in e["path"] for e in errs)

    def test_int_where_bool_expected(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["channel"]["evidence"]["enabled"] = 42
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        errs = exc_info.value.errors
        assert any("enabled" in e["path"] for e in errs)

    def test_string_where_float_expected(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["playout"]["pace"]["target_hz"] = "fast"
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        assert any("target_hz" in e["path"] for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# defaults.yaml — unknown keys
# ---------------------------------------------------------------------------

class TestDefaultsUnknownKeys:

    def test_extra_top_level_key_raises(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["nonexistent_domain"] = {"foo": 1}
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        assert any("nonexistent_domain" in e["path"] for e in exc_info.value.errors)

    def test_extra_nested_key_raises(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["channel"]["bogus_key"] = 42
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        assert any("bogus_key" in e["path"] for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# defaults.yaml — null values
# ---------------------------------------------------------------------------

class TestDefaultsNullValues:

    def test_null_in_non_nullable_field(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["channel"]["linger_seconds"] = None
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        assert any("linger_seconds" in e["path"] for e in exc_info.value.errors)

    def test_null_compiler_seed_is_allowed(self, valid_defaults: dict):
        """compiler_seed is explicitly nullable (null = non-deterministic)."""
        data = copy.deepcopy(valid_defaults)
        data["scheduling"]["compiler_seed"] = None
        validate_defaults(data)  # no exception


# ---------------------------------------------------------------------------
# Channel YAML — valid
# ---------------------------------------------------------------------------

class TestChannelValid:

    def test_minimal_channel_passes(self, valid_channel: dict):
        validate_channel_yaml(valid_channel)  # no exception

    def test_full_channel_passes(self):
        data = {
            "channel_id": "hbo",
            "number": 201,
            "name": "Home Box Office",
            "channel_type": "premium",
            "timezone": "America/New_York",
            "format": {
                "video": {"width": 1280, "height": 720},
                "audio": {"sample_rate": 48000, "channels": 2},
            },
            "pools": {"movies": {"match": {"type": "movie"}}},
            "programs": {"hbo_movies": {"pool": "movies"}},
            "schedule": {"all_day": [{"start": "06:00", "slots": 48}]},
            "traffic": {"default_profile": "hbo"},
        }
        validate_channel_yaml(data)  # no exception

    def test_legacy_channel_key_passes(self):
        """Legacy 'channel:' is accepted (though deprecated)."""
        data = {"channel": "test", "number": 1}
        validate_channel_yaml(data)  # no exception

    def test_legacy_channel_number_passes(self):
        """Legacy 'channel_number:' is accepted (though deprecated)."""
        data = {"channel_id": "test", "channel_number": 1}
        validate_channel_yaml(data)  # no exception


# ---------------------------------------------------------------------------
# Channel YAML — missing required identifiers
# ---------------------------------------------------------------------------

class TestChannelMissingIdentifiers:

    def test_missing_channel_id_and_channel_raises(self):
        data = {"number": 1, "name": "No ID"}
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(data)
        assert any("channel_id" in e["message"] or "channel" in e["message"]
                    for e in exc_info.value.errors)

    def test_missing_number_and_channel_number_raises(self):
        data = {"channel_id": "test", "name": "No Number"}
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(data)
        assert any("number" in e["message"] for e in exc_info.value.errors)

    def test_negative_number_raises(self):
        data = {"channel_id": "test", "number": -1}
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(data)
        assert any("positive" in e["message"] for e in exc_info.value.errors)

    def test_zero_number_raises(self):
        data = {"channel_id": "test", "number": 0}
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(data)
        assert any("positive" in e["message"] for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# Channel YAML — format section type errors
# ---------------------------------------------------------------------------

class TestChannelFormatTypes:

    def test_format_video_width_wrong_type(self):
        data = {
            "channel_id": "test",
            "number": 1,
            "format": {"video": {"width": "big"}},
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(data)
        assert any("width" in e["path"] for e in exc_info.value.errors)

    def test_format_grid_minutes_wrong_type(self):
        data = {
            "channel_id": "test",
            "number": 1,
            "format": {"grid_minutes": "thirty"},
        }
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(data)
        assert any("grid_minutes" in e["path"] for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# Error message quality
# ---------------------------------------------------------------------------

class TestErrorQuality:

    def test_error_includes_path(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["hls"]["segmenter"]["target_duration_ms"] = "not_a_number"
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        errs = exc_info.value.errors
        paths = [e["path"] for e in errs]
        assert any("hls.segmenter.target_duration_ms" in p for p in paths)

    def test_error_includes_message(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["hls"]["segmenter"]["target_duration_ms"] = "not_a_number"
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        errs = exc_info.value.errors
        assert all(e["message"] for e in errs)  # all have non-empty messages

    def test_error_includes_input(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["hls"]["segmenter"]["target_duration_ms"] = "not_a_number"
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        errs = exc_info.value.errors
        assert any(e["input"] == "not_a_number" for e in errs)

    def test_multiple_errors_reported(self, valid_defaults: dict):
        data = copy.deepcopy(valid_defaults)
        data["hls"]["segmenter"]["target_duration_ms"] = "bad"
        data["channel"]["linger_seconds"] = "also_bad"
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_defaults(data)
        assert len(exc_info.value.errors) >= 2
