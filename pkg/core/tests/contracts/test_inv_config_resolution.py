"""
Contract tests for Configuration Resolution.

Contract: docs/contracts/configuration_resolution.md

Invariants tested:
    INV-CONFIG-IMMUTABLE-001  — Resolved config is frozen after creation
    INV-CONFIG-IDENTITY-001   — Stable identity within a channel activation

Merge rules tested (§3):
    §3.1  Recursive dict merge
    §3.2  Scalar override
    §3.3  List replacement (NOT merge)
    §3.4  Null override clears default
    §3.5  Type preservation

Validation rules tested (§6):
    §6.1  Unknown keys in governed domains → rejected
    §6.2  Type mismatches → rejected
    §6.3  Structural mismatches (scalar vs dict) → rejected
    §6.4  Missing defaults → error
    §6.5  Missing channel config → defaults only
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from types import MappingProxyType

import pytest
import yaml

from retrovue.config.config_loader import (
    _deep_freeze,
    load_defaults,
    reset_defaults_cache,
)
from retrovue.config.merge import (
    StructuralMismatchError,
    TypeMismatchError,
    UnknownKeyError,
    deep_merge,
)
from retrovue.config.resolver import resolve_channel_config, resolve_defaults_only
from retrovue.config.testing import (
    load_defaults_unvalidated,
    resolve_channel_unvalidated,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the global defaults cache before each test."""
    reset_defaults_cache()
    yield
    reset_defaults_cache()


@pytest.fixture()
def defaults_yaml(tmp_path: Path) -> Path:
    """Write a minimal defaults.yaml and return its path."""
    content = textwrap.dedent("""\
        scheduling:
          broadcast_day_start_hour: 6
          grid_minutes:
            network_television: 30
            premium_movie: 15
          block_defaults:
            slots: 1
            progression: "sequential"
        playout:
          timing:
            min_prefeed_lead_time_ms: 5000
          transitions:
            default_fade_duration_ms: 500
            default_type: "TRANSITION_NONE"
        channel:
          linger_seconds: 20
          encoding:
            video_bitrate_bps: 8000000
            aspect_policy: "preserve"
          recovery:
            base_delay_seconds: 1.0
            max_attempts: 5
        hls:
          segmenter:
            target_duration_ms: 6000
            max_gop_ms: 1000
          ring:
            capacity: 7
            manifest_window: 3
          session:
            timeout_ms: 30000
        streaming:
          buffers:
            client_buffer_bytes: 4000000
        system:
          ports:
            program_director: 8000
          log_level: "INFO"
        integrations:
          plex:
            device_id: "RVUE1234"
            tuner_count: 8
        air:
          metrics_port: 9308
          buffers:
            default_frames: 60
    """)
    p = tmp_path / "defaults.yaml"
    p.write_text(content)
    return p


@pytest.fixture()
def channel_yaml(tmp_path: Path) -> Path:
    """Write a minimal channel YAML and return its path."""
    content = textwrap.dedent("""\
        channel: hbo
        number: 201
        name: "Home Box Office"
        channel_type: premium

        channel:
          linger_seconds: 60
          encoding:
            video_bitrate_bps: 12000000

        hls:
          segmenter:
            target_duration_ms: 4000

        pools:
          movies_r:
            match:
              type: movie
              rating: R
    """)
    p = tmp_path / "hbo.yaml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# §2: Default-only config (no channel overrides)
# ---------------------------------------------------------------------------

class TestDefaultsOnly:
    """When no channel YAML is provided, all defaults are present."""

    def test_defaults_only_returns_all_keys(self, defaults_yaml: Path):
        cfg = load_defaults_unvalidated(defaults_yaml)
        assert "scheduling" in cfg
        assert "playout" in cfg
        assert "channel" in cfg
        assert "hls" in cfg
        assert "streaming" in cfg
        assert "system" in cfg
        assert "integrations" in cfg
        assert "air" in cfg

    def test_defaults_only_values_match(self, defaults_yaml: Path):
        cfg = load_defaults_unvalidated(defaults_yaml)
        assert cfg["scheduling"]["broadcast_day_start_hour"] == 6
        assert cfg["channel"]["linger_seconds"] == 20
        assert cfg["hls"]["segmenter"]["target_duration_ms"] == 6000


# ---------------------------------------------------------------------------
# §3.2: Scalar override
# ---------------------------------------------------------------------------

class TestScalarOverride:
    """Channel scalar values replace defaults."""

    def test_scalar_override_replaces_default(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        assert cfg["channel"]["linger_seconds"] == 60  # was 20

    def test_sibling_keys_preserved(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        # encoding.aspect_policy is not overridden by the channel
        assert cfg["channel"]["encoding"]["aspect_policy"] == "preserve"


# ---------------------------------------------------------------------------
# §3.1: Nested override (dict merge)
# ---------------------------------------------------------------------------

class TestNestedDictMerge:
    """Dictionaries merge recursively; untouched siblings preserved."""

    def test_nested_override_preserves_siblings(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        # Channel overrides video_bitrate_bps but not aspect_policy
        assert cfg["channel"]["encoding"]["video_bitrate_bps"] == 12000000
        assert cfg["channel"]["encoding"]["aspect_policy"] == "preserve"

    def test_untouched_subtree_inherited(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        # Channel does not touch recovery at all
        assert cfg["channel"]["recovery"]["base_delay_seconds"] == 1.0
        assert cfg["channel"]["recovery"]["max_attempts"] == 5

    def test_deep_nested_override(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        # hls.segmenter.target_duration_ms overridden, max_gop_ms preserved
        assert cfg["hls"]["segmenter"]["target_duration_ms"] == 4000
        assert cfg["hls"]["segmenter"]["max_gop_ms"] == 1000


# ---------------------------------------------------------------------------
# §3.3: List replacement
# ---------------------------------------------------------------------------

class TestListReplacement:
    """Lists are fully replaced, NOT merged."""

    def test_list_replaced_entirely(self, defaults_yaml: Path, tmp_path: Path):
        # Add a list to defaults
        defaults_data = yaml.safe_load(defaults_yaml.read_text())
        defaults_data["integrations"]["plex"]["allowed_profiles"] = ["a", "b", "c"]
        defaults_yaml.write_text(yaml.dump(defaults_data))

        channel_content = textwrap.dedent("""\
            channel: test
            integrations:
              plex:
                allowed_profiles: ["x"]
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        cfg = resolve_channel_unvalidated(ch_path, defaults_yaml)
        # Entire list replaced — not ["a", "b", "c", "x"]
        profiles = cfg["integrations"]["plex"]["allowed_profiles"]
        assert list(profiles) == ["x"]


# ---------------------------------------------------------------------------
# §3.4: Null override behavior
# ---------------------------------------------------------------------------

class TestNullOverride:
    """Explicit null in channel overrides clears the default."""

    def test_null_clears_default(self, defaults_yaml: Path, tmp_path: Path):
        channel_content = textwrap.dedent("""\
            channel: test
            channel:
              linger_seconds: null
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        cfg = resolve_channel_unvalidated(ch_path, defaults_yaml)
        assert cfg["channel"]["linger_seconds"] is None

    def test_absent_key_inherits_default(
        self, defaults_yaml: Path, tmp_path: Path,
    ):
        # `channel: test` is the identifier (string); it collides with
        # the governed `channel` domain (dict), so the resolver stores
        # the identifier as `channel_id` and preserves the domain dict.
        channel_content = textwrap.dedent("""\
            channel: test
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        cfg = resolve_channel_unvalidated(ch_path, defaults_yaml)
        assert cfg["channel"]["linger_seconds"] == 20  # default, not None
        assert cfg["channel_id"] == "test"  # identifier preserved


# ---------------------------------------------------------------------------
# §6.1: Unknown key rejection
# ---------------------------------------------------------------------------

class TestUnknownKeyRejection:
    """Unknown keys within governed domains are rejected."""

    def test_unknown_key_in_governed_domain_raises(
        self, defaults_yaml: Path, tmp_path: Path,
    ):
        channel_content = textwrap.dedent("""\
            channel: test
            channel:
              linger_seconds: 20
              nonexistent_key: 42
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        with pytest.raises(UnknownKeyError, match="nonexistent_key"):
            resolve_channel_unvalidated(ch_path, defaults_yaml)

    def test_passthrough_keys_accepted(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        """Channel-specific domain keys (pools, programs, etc.) pass through."""
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        assert "pools" in cfg
        assert "movies_r" in cfg["pools"]


# ---------------------------------------------------------------------------
# §6.2: Type mismatch rejection
# ---------------------------------------------------------------------------

class TestTypeMismatchRejection:
    """Type mismatches are rejected."""

    def test_string_overriding_int_raises(
        self, defaults_yaml: Path, tmp_path: Path,
    ):
        channel_content = textwrap.dedent("""\
            channel: test
            channel:
              linger_seconds: "not_a_number"
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        with pytest.raises(TypeMismatchError, match="linger_seconds"):
            resolve_channel_unvalidated(ch_path, defaults_yaml)

    def test_bool_overriding_int_raises(
        self, defaults_yaml: Path, tmp_path: Path,
    ):
        channel_content = textwrap.dedent("""\
            channel: test
            hls:
              segmenter:
                target_duration_ms: true
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        with pytest.raises(TypeMismatchError, match="target_duration_ms"):
            resolve_channel_unvalidated(ch_path, defaults_yaml)

    def test_int_overriding_float_accepted(
        self, defaults_yaml: Path, tmp_path: Path,
    ):
        """int widening to float is accepted per §6.2."""
        channel_content = textwrap.dedent("""\
            channel: test
            channel:
              recovery:
                base_delay_seconds: 2
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        cfg = resolve_channel_unvalidated(ch_path, defaults_yaml)
        assert cfg["channel"]["recovery"]["base_delay_seconds"] == 2


# ---------------------------------------------------------------------------
# §6.3: Structural mismatch rejection
# ---------------------------------------------------------------------------

class TestStructuralMismatchRejection:
    """Scalar vs dict conflicts are rejected."""

    def test_scalar_overriding_dict_raises(
        self, defaults_yaml: Path, tmp_path: Path,
    ):
        channel_content = textwrap.dedent("""\
            channel: test
            channel:
              encoding: "flat_string"
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        with pytest.raises(StructuralMismatchError, match="encoding"):
            resolve_channel_unvalidated(ch_path, defaults_yaml)

    def test_dict_overriding_scalar_raises(
        self, defaults_yaml: Path, tmp_path: Path,
    ):
        channel_content = textwrap.dedent("""\
            channel: test
            channel:
              linger_seconds:
                min: 10
                max: 60
        """)
        ch_path = tmp_path / "test.yaml"
        ch_path.write_text(channel_content)

        with pytest.raises(StructuralMismatchError, match="linger_seconds"):
            resolve_channel_unvalidated(ch_path, defaults_yaml)


# ---------------------------------------------------------------------------
# INV-CONFIG-IMMUTABLE-001: Immutability
# ---------------------------------------------------------------------------

class TestImmutability:
    """Resolved config must be read-only (MappingProxyType)."""

    def test_resolved_config_is_frozen(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        assert isinstance(cfg, MappingProxyType)

    def test_nested_dicts_are_frozen(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        assert isinstance(cfg["channel"], MappingProxyType)
        assert isinstance(cfg["channel"]["encoding"], MappingProxyType)
        assert isinstance(cfg["hls"]["segmenter"], MappingProxyType)

    def test_mutation_raises(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        with pytest.raises(TypeError):
            cfg["channel"] = {}  # type: ignore[index]

    def test_nested_mutation_raises(
        self, defaults_yaml: Path, channel_yaml: Path,
    ):
        cfg = resolve_channel_unvalidated(channel_yaml, defaults_yaml)
        with pytest.raises(TypeError):
            cfg["channel"]["linger_seconds"] = 999  # type: ignore[index]

    def test_lists_frozen_as_tuples(self, defaults_yaml: Path, tmp_path: Path):
        defaults_data = yaml.safe_load(defaults_yaml.read_text())
        defaults_data["integrations"]["plex"]["profiles"] = ["a", "b"]
        defaults_yaml.write_text(yaml.dump(defaults_data))

        cfg = load_defaults_unvalidated(defaults_yaml)
        assert isinstance(cfg["integrations"]["plex"]["profiles"], tuple)


# ---------------------------------------------------------------------------
# §6.4 / §6.5: Missing file handling
# ---------------------------------------------------------------------------

class TestMissingFiles:
    """Missing defaults = error.  Missing channel = defaults only."""

    def test_missing_defaults_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_defaults(tmp_path / "nonexistent.yaml")

    def test_missing_channel_raises(self, defaults_yaml: Path, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            resolve_channel_unvalidated(
                tmp_path / "ghost.yaml",
                defaults_yaml,
            )


# ---------------------------------------------------------------------------
# Deep freeze utility
# ---------------------------------------------------------------------------

class TestDeepFreeze:
    """Unit tests for the _deep_freeze utility."""

    def test_dict_becomes_mapping_proxy(self):
        result = _deep_freeze({"a": 1})
        assert isinstance(result, MappingProxyType)
        assert result["a"] == 1

    def test_nested_dict_frozen(self):
        result = _deep_freeze({"a": {"b": 2}})
        assert isinstance(result["a"], MappingProxyType)

    def test_list_becomes_tuple(self):
        result = _deep_freeze({"a": [1, 2, 3]})
        assert isinstance(result["a"], tuple)
        assert result["a"] == (1, 2, 3)

    def test_scalars_unchanged(self):
        result = _deep_freeze({"i": 42, "f": 3.14, "s": "hello", "b": True})
        assert result["i"] == 42
        assert result["f"] == 3.14
        assert result["s"] == "hello"
        assert result["b"] is True


# ---------------------------------------------------------------------------
# Merge unit tests (direct deep_merge calls)
# ---------------------------------------------------------------------------

class TestDeepMergeDirect:
    """Direct unit tests for deep_merge without file I/O."""

    def test_empty_overrides_returns_defaults(self):
        defaults = {"a": 1, "b": {"c": 2}}
        result = deep_merge(defaults, {})
        assert result == {"a": 1, "b": {"c": 2}}

    def test_passthrough_keys_outside_governed(self):
        defaults = {"scheduling": {"x": 1}}
        overrides = {"pools": {"foo": "bar"}}
        result = deep_merge(
            defaults, overrides,
            governed_keys=frozenset({"scheduling"}),
        )
        assert result["pools"] == {"foo": "bar"}
        assert result["scheduling"]["x"] == 1

    def test_unknown_key_inside_governed_raises(self):
        defaults = {"scheduling": {"x": 1}}
        overrides = {"scheduling": {"x": 1, "bogus": 99}}
        with pytest.raises(UnknownKeyError, match="bogus"):
            deep_merge(
                defaults, overrides,
                governed_keys=frozenset({"scheduling"}),
            )


# ---------------------------------------------------------------------------
# Integration: real defaults.yaml
# ---------------------------------------------------------------------------

class TestRealDefaultsYaml:
    """Smoke test against the actual config/defaults.yaml on disk."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_file(self):
        p = Path("/opt/retrovue/config/defaults.yaml")
        if not p.exists():
            pytest.skip("config/defaults.yaml not present")

    def test_loads_without_error(self):
        cfg = load_defaults(Path("/opt/retrovue/config/defaults.yaml"))
        assert isinstance(cfg, MappingProxyType)
        assert "scheduling" in cfg
        assert "air" in cfg

    def test_real_channel_hbo(self):
        p = Path("/opt/retrovue/config/channels/hbo.yaml")
        if not p.exists():
            pytest.skip("hbo.yaml not present")
        cfg = resolve_channel_config(
            p,
            defaults_path=Path("/opt/retrovue/config/defaults.yaml"),
        )
        assert cfg["channel_type"] == "premium"
        assert cfg["channel_id"] == "hbo"  # identifier from `channel: hbo`
        assert "pools" in cfg
        assert "scheduling" in cfg  # from defaults
        assert isinstance(cfg["channel"], MappingProxyType)  # governed domain preserved
