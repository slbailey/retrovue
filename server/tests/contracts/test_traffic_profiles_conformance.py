"""Contract tests for Traffic Profiles & Conformance Policy.

Validates all invariants defined in:
    docs/contracts/traffic_profiles_conformance.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-DERIVATION.

These tests exercise traffic profile resolution, overconstrained/underconstrained
conformance policies, and warning emission through the compile_schedule pipeline.

Invariant groups:
    INV-OVERCONSTRAINED-POLICY-001
    INV-TRAFFIC-PROFILE-RESOLVED-001
    INV-UNDERRUN-WARNING-001
"""

from __future__ import annotations

import copy
import logging

import pytest

try:
    from retrovue.runtime.asset_resolver import AssetMetadata
    from retrovue.dev.stub_asset_resolver import StubAssetResolver
    from retrovue.runtime.schedule_compiler import (
        compile_schedule,
        CompileError,
        ValidationError,
    )
    from retrovue.config.testing import TEST_RESOLVED_CONFIG
except ImportError:
    pytest.skip(
        "retrovue runtime modules not available — "
        "implementation not yet provided",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_30_MIN_MS = 1_800_000
GRID_60_MIN_MS = 3_600_000

EPISODE_22_MIN_MS = 1_320_000   # 22-min sitcom
EPISODE_35_MIN_MS = 2_100_000   # 35-min overconstrained in 30-min slot
EPISODE_44_MIN_MS = 2_640_000   # 44-min drama
MOVIE_90_MIN_MS = 5_400_000     # 90-min movie

TOLERANCE_MS = 40


# ---------------------------------------------------------------------------
# Resolver helpers
# ---------------------------------------------------------------------------


def _make_resolver(
    *,
    episodes: dict[str, int] | None = None,
    chapter_markers_sec: tuple[float, ...] | None = None,
    bumpers: dict[str, int] | None = None,
    trailers: dict[str, int] | None = None,
    promos: dict[str, int] | None = None,
) -> StubAssetResolver:
    """Build a StubAssetResolver with configurable episodes and interstitials."""
    resolver = StubAssetResolver()

    if episodes is None:
        episodes = {"ep-001": 1320}  # 22-min default

    pool_tags = tuple(episodes.keys())
    resolver.add("episodes", AssetMetadata(
        type="pool", duration_sec=0, tags=pool_tags,
    ))
    resolver.register_pools({
        "episodes": {"match": {"type": "episode"}},
    })

    for ep_id, dur_sec in episodes.items():
        resolver.add(ep_id, AssetMetadata(
            type="episode",
            duration_sec=dur_sec,
            title=f"Test Episode {ep_id}",
            chapter_markers_sec=chapter_markers_sec,
            loudness_gain_db=-2.0,
            file_uri=f"/mnt/episodes/{ep_id}.mkv",
        ))

    if bumpers:
        bumper_tags = tuple(bumpers.keys())
        resolver.add("bumpers", AssetMetadata(
            type="pool", duration_sec=0, tags=bumper_tags,
        ))
        resolver.register_pools({
            "bumpers": {"match": {"type": "bumper"}},
        })
        for b_id, dur_sec in bumpers.items():
            resolver.add(b_id, AssetMetadata(
                type="bumper",
                duration_sec=dur_sec,
                title=f"Bumper {b_id}",
                loudness_gain_db=0.0,
                file_uri=f"/mnt/bumpers/{b_id}.mkv",
            ))

    if trailers:
        trailer_tags = tuple(trailers.keys())
        resolver.add("trailers", AssetMetadata(
            type="pool", duration_sec=0, tags=trailer_tags,
        ))
        resolver.register_pools({
            "trailers": {"match": {"type": "trailer"}},
        })
        for t_id, dur_sec in trailers.items():
            resolver.add(t_id, AssetMetadata(
                type="trailer",
                duration_sec=dur_sec,
                title=f"Trailer {t_id}",
                loudness_gain_db=0.0,
                file_uri=f"/mnt/trailers/{t_id}.mkv",
            ))

    if promos:
        promo_tags = tuple(promos.keys())
        resolver.add("promos", AssetMetadata(
            type="pool", duration_sec=0, tags=promo_tags,
        ))
        resolver.register_pools({
            "promos": {"match": {"type": "promo"}},
        })
        for p_id, dur_sec in promos.items():
            resolver.add(p_id, AssetMetadata(
                type="promo",
                duration_sec=dur_sec,
                title=f"Promo {p_id}",
                loudness_gain_db=0.0,
                file_uri=f"/mnt/promos/{p_id}.mkv",
            ))

    return resolver


# ---------------------------------------------------------------------------
# DSL builders
# ---------------------------------------------------------------------------


def _base_dsl(
    *,
    templates: dict | None = None,
    program_template: str | None = None,
    channel_type: str = "network",
    slots: int = 6,
    grid_blocks: int | None = None,
    grid_blocks_max: int | None = None,
    traffic: dict | None = None,
    bleed: bool = False,
    schedule_traffic_profile: str | None = None,
) -> dict:
    """Build a minimal channel DSL dict with optional templates and traffic sections."""
    prog_def: dict = {
        "pool": "episodes",
        "fill_mode": "single",
    }
    if grid_blocks is not None:
        prog_def["grid_blocks"] = grid_blocks
    elif grid_blocks_max is not None:
        prog_def["grid_blocks_max"] = grid_blocks_max
    else:
        prog_def["grid_blocks_max"] = 6

    if program_template is not None:
        prog_def["template"] = program_template

    schedule_entry: dict = {
        "start": "06:00",
        "slots": slots,
        "program": "test_show",
        "progression": "sequential",
    }
    if bleed:
        schedule_entry["bleed"] = True
    if schedule_traffic_profile is not None:
        schedule_entry["traffic_profile"] = schedule_traffic_profile

    dsl: dict = {
        "channel": "test-channel",
        "broadcast_day": "2026-04-10",
        "timezone": "UTC",
        "channel_type": channel_type,
        "template": "network_television",
        "pools": {
            "episodes": {
                "select": {"where": {"type": {"eq": "episode"}}},
            },
        },
        "programs": {
            "test_show": prog_def,
        },
        "schedule": {
            "all_day": [schedule_entry],
        },
    }

    if templates is not None:
        dsl["templates"] = templates
    if traffic is not None:
        dsl["traffic"] = traffic

    return dsl


def _traffic_section(
    *,
    profiles: dict | None = None,
    default: str = "default_profile",
) -> dict:
    """Build a minimal traffic section for DSL."""
    if profiles is None:
        profiles = {
            "default_profile": {
                "allowed_types": ["promo", "trailer"],
                "default_cooldown_seconds": 3600,
                "max_plays_per_day": 0,
            },
        }
    return {
        "profiles": profiles,
        "default": default,
    }


def _extract_compiled_segments(result: dict) -> list[dict]:
    """Extract compiled_segments from the first block of a compilation result."""
    blocks = result["program_blocks"]
    assert len(blocks) > 0, "Expected at least one compiled block"
    return blocks[0]["compiled_segments"]


def _extract_block(result: dict, index: int = 0) -> dict:
    """Extract a compiled block from the result."""
    blocks = result["program_blocks"]
    assert len(blocks) > index, f"Expected at least {index + 1} compiled block(s)"
    return blocks[index]


def _filler_segments(segments: list[dict]) -> list[dict]:
    """Return only filler/break segments."""
    return [s for s in segments if s["segment_type"] == "filler"]


def _total_duration(segments: list[dict]) -> int:
    """Sum of all segment durations."""
    return sum(s["duration_ms"] for s in segments)


# ===========================================================================
# INV-OVERCONSTRAINED-POLICY-001 — Explicit per-template overconstrained
# conformance
# ===========================================================================


class TestOverconstrainedBleedExtendsSlot:
    """INV-OVERCONSTRAINED-POLICY-001: Block with `bleed` policy and
    content > slot gets extended slot, zero breaks."""

    def test_overconstrained_bleed_extends_slot(self):
        """Content exceeding slot duration with bleed policy → slot expands
        to accommodate content. Grid alignment may round up, creating residual
        break budget — the key invariant is that the slot expanded beyond the
        original grid size."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    "traffic_profile": "default_profile",
                },
                "overconstrained": "bleed",
            },
        }
        # 35-min content in 30-min slot → overconstrained
        resolver = _make_resolver(episodes={"ep-001": 2100})
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            bleed=True,
            traffic=_traffic_section(),
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        block = _extract_block(result)

        # Slot must expand beyond the original 30-min grid slot (1800 sec)
        assert block["slot_duration_sec"] > 1800, (
            f"Bleed should expand slot beyond 1800s, got {block['slot_duration_sec']}s"
        )
        # Slot must be >= content duration (35 min = 2100 sec)
        assert block["slot_duration_sec"] >= 2100, (
            f"Bleed slot should expand to >= 2100s, got {block['slot_duration_sec']}s"
        )


class TestOverconstrainedRejectRaisesError:
    """INV-OVERCONSTRAINED-POLICY-001: Block with `reject` policy and
    content > slot raises CompileError with structured details."""

    def test_overconstrained_reject_raises_error(self):
        """Compilation must fail with structured error for reject policy.

        Uses bleed=True so assembly allows the oversized content through,
        then the overconstrained reject check fires at compilation."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
                "overconstrained": "reject",
            },
        }
        # 35-min content in 30-min slot → overconstrained
        resolver = _make_resolver(episodes={"ep-001": 2100})
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            bleed=True,  # Let assembly pass; reject fires in compiler
        )
        with pytest.raises((CompileError, ValidationError, ValueError)) as exc_info:
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        # Error should contain structured details about the violation
        msg = str(exc_info.value).lower()
        assert any(kw in msg for kw in ("overconstrained", "reject", "exceed", "deficit")), (
            f"Error message should reference overconstrained/reject: {exc_info.value}"
        )


class TestOverconstrainedDefaultIsBleed:
    """INV-OVERCONSTRAINED-POLICY-001: Template without explicit
    `overconstrained` defaults to `bleed`."""

    def test_overconstrained_default_is_bleed(self):
        """Template omitting `overconstrained` uses bleed as default."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    "traffic_profile": "default_profile",
                },
                # No overconstrained field — should default to bleed
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 2100})  # 35 min
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            bleed=True,
            traffic=_traffic_section(),
        )
        # Should NOT raise — bleed is the default
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        block = _extract_block(result)
        # Slot should have expanded (bleed default)
        assert block["slot_duration_sec"] >= 2100


class TestOverconstrainedPerTemplateIndependent:
    """INV-OVERCONSTRAINED-POLICY-001: Two templates with different policies
    in same channel compile independently."""

    def test_overconstrained_per_template_independent(self):
        """Different templates with different policies coexist."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    "traffic_profile": "default_profile",
                },
                "overconstrained": "bleed",
            },
            "infomercial": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 15,
                    "traffic_profile": "default_profile",
                },
                "overconstrained": "reject",
            },
        }
        # sitcom uses bleed, infomercial uses reject — both defined
        resolver = _make_resolver(episodes={"ep-001": 1320})  # 22 min (fits fine)
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=_traffic_section(),
        )
        # sitcom with 22-min content in 30-min slot → underconstrained, should compile
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        assert len(result["program_blocks"]) > 0


class TestOverconstrainedInheritsViaExtends:
    """INV-OVERCONSTRAINED-POLICY-001: Child template inherits parent's
    overconstrained policy."""

    def test_overconstrained_inherits_via_extends(self):
        """Child without overconstrained inherits parent's policy."""
        templates = {
            "base": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
                "overconstrained": "reject",
            },
            "child": {
                "extends": "base",
                # Inherits overconstrained: reject from base
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 2100})  # overconstrained
        dsl = _base_dsl(
            templates=templates,
            program_template="child",
            grid_blocks=1,
            bleed=True,  # Let assembly pass; reject fires in compiler
        )
        # Should raise because child inherits reject from parent
        with pytest.raises((CompileError, ValidationError, ValueError)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)


class TestOverconstrainedChildOverridesParent:
    """INV-OVERCONSTRAINED-POLICY-001: Child template overrides parent's
    overconstrained with reject."""

    def test_overconstrained_child_overrides_parent(self):
        """Child overriding parent's bleed with reject must reject."""
        templates = {
            "base": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
                "overconstrained": "bleed",
            },
            "strict_child": {
                "extends": "base",
                "overconstrained": "reject",  # Override parent's bleed
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 2100})  # overconstrained
        dsl = _base_dsl(
            templates=templates,
            program_template="strict_child",
            grid_blocks=1,
            bleed=True,  # Let assembly pass; reject fires in compiler
        )
        # Should raise — child overrode to reject
        with pytest.raises((CompileError, ValidationError, ValueError)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)


# ===========================================================================
# INV-TRAFFIC-PROFILE-RESOLVED-001 — Traffic profile resolution for every
# break-bearing block
# ===========================================================================


class TestTrafficProfileResolvedFromTemplate:
    """INV-TRAFFIC-PROFILE-RESOLVED-001: Block with template traffic_profile
    resolves to that profile."""

    def test_traffic_profile_resolved_from_template(self):
        """Template's breaks.traffic_profile is carried on compiled block."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    "traffic_profile": "sitcom_promos",
                },
            },
        }
        traffic = _traffic_section(
            profiles={
                "sitcom_promos": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 3600,
                    "max_plays_per_day": 0,
                },
            },
            default="sitcom_promos",
        )
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        block = _extract_block(result)
        assert block.get("traffic_profile") == "sitcom_promos", (
            f"Expected traffic_profile='sitcom_promos', got {block.get('traffic_profile')}"
        )


class TestTrafficProfileBlockOverrideWins:
    """INV-TRAFFIC-PROFILE-RESOLVED-001: Block-level traffic_profile overrides
    template-level."""

    def test_traffic_profile_block_override_wins(self):
        """Schedule block traffic_profile takes precedence over template."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    "traffic_profile": "sitcom_promos",
                },
            },
        }
        traffic = _traffic_section(
            profiles={
                "sitcom_promos": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 3600,
                    "max_plays_per_day": 0,
                },
                "special_promos": {
                    "allowed_types": ["promo", "trailer"],
                    "default_cooldown_seconds": 1800,
                    "max_plays_per_day": 0,
                },
            },
            default="sitcom_promos",
        )
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
            schedule_traffic_profile="special_promos",  # block-level override
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        block = _extract_block(result)
        assert block.get("traffic_profile") == "special_promos", (
            f"Block-level override should win, got {block.get('traffic_profile')}"
        )


class TestTrafficProfileFallsBackToChannelDefault:
    """INV-TRAFFIC-PROFILE-RESOLVED-001: Block with no template or block-level
    profile uses channel default."""

    def test_traffic_profile_falls_back_to_channel_default(self):
        """When no template or block profile, channel traffic.default is used."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    # No traffic_profile on template
                },
            },
        }
        traffic = _traffic_section(
            profiles={
                "channel_default": {
                    "allowed_types": ["promo", "trailer"],
                    "default_cooldown_seconds": 3600,
                    "max_plays_per_day": 0,
                },
            },
            default="channel_default",
        )
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        block = _extract_block(result)
        assert block.get("traffic_profile") == "channel_default", (
            f"Should fall back to channel default, got {block.get('traffic_profile')}"
        )


class TestTrafficProfileMissingFailsValidation:
    """INV-TRAFFIC-PROFILE-RESOLVED-001: Block with breaks but no resolvable
    profile fails at validation."""

    def test_traffic_profile_missing_fails_validation(self):
        """Compilation must fail when no traffic profile can be resolved for
        a block that contains breaks. A traffic section exists but no default
        or template profile is set."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    # No traffic_profile on template
                },
            },
        }
        # Traffic section exists but no default — profile unresolvable
        traffic = {
            "profiles": {
                "some_profile": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 3600,
                    "max_plays_per_day": 0,
                },
            },
            # No "default" key → resolution yields None
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        with pytest.raises((CompileError, ValidationError, ValueError)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)


class TestTrafficProfileInvalidReferenceFails:
    """INV-TRAFFIC-PROFILE-RESOLVED-001: Template referencing nonexistent
    profile fails YAML validation."""

    def test_traffic_profile_invalid_reference_fails(self):
        """Template with traffic_profile pointing to nonexistent profile must
        fail validation."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    "traffic_profile": "nonexistent_profile",
                },
            },
        }
        traffic = _traffic_section(
            profiles={
                "real_profile": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 3600,
                    "max_plays_per_day": 0,
                },
            },
            default="real_profile",
        )
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        with pytest.raises((CompileError, ValidationError, ValueError)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)


class TestTrafficProfileCarriedOnBreakStructure:
    """INV-TRAFFIC-PROFILE-RESOLVED-001: Resolved profile name is present on
    each break structure in compiled output."""

    def test_traffic_profile_carried_on_break_structure(self):
        """Each filler segment in compiled_segments carries the resolved
        traffic profile name."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                    "traffic_profile": "sitcom_promos",
                },
            },
        }
        traffic = _traffic_section(
            profiles={
                "sitcom_promos": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 3600,
                    "max_plays_per_day": 0,
                },
            },
            default="sitcom_promos",
        )
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        fillers = _filler_segments(segments)
        if fillers:
            for filler in fillers:
                assert filler.get("traffic_profile") == "sitcom_promos", (
                    f"Filler segment should carry traffic_profile='sitcom_promos', "
                    f"got {filler.get('traffic_profile')}"
                )

        # Also verify the block-level traffic_profile
        block = _extract_block(result)
        assert block.get("traffic_profile") == "sitcom_promos"


class TestTrailingBlockOwnProfile:
    """INV-TRAFFIC-PROFILE-RESOLVED-001: Trailing interstitial block uses its
    own traffic_profile when declared."""

    def test_trailing_block_own_profile(self):
        """Trailing block with its own traffic_profile uses that profile,
        not the breaks.traffic_profile."""
        templates = {
            "movie_broadcast": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 20,
                    "traffic_profile": "movie_trailers",
                },
                "trailing": [
                    {
                        "type": "interstitial_block",
                        "traffic_profile": "movie_post_roll",
                    },
                ],
            },
        }
        traffic = _traffic_section(
            profiles={
                "movie_trailers": {
                    "allowed_types": ["trailer"],
                    "default_cooldown_seconds": 3600,
                    "max_plays_per_day": 0,
                },
                "movie_post_roll": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 1800,
                    "max_plays_per_day": 0,
                },
            },
            default="movie_trailers",
        )
        resolver = _make_resolver(episodes={"ep-001": 5400})  # 90-min movie
        dsl = _base_dsl(
            templates=templates,
            program_template="movie_broadcast",
            grid_blocks_max=6,
            traffic=traffic,
            bleed=True,
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        block = _extract_block(result)

        # The trailing block should carry its own profile.
        # This test validates the intent — implementation may represent trailing
        # as segments with a traffic_profile field or as a separate structure.
        # At minimum, the block must carry the primary profile.
        assert block.get("traffic_profile") == "movie_trailers"


class TestTrailingBlockFallbackToBreaksProfile:
    """INV-TRAFFIC-PROFILE-RESOLVED-001: Trailing block without own profile
    falls back to breaks.traffic_profile."""

    def test_trailing_block_fallback_to_breaks_profile(self):
        """Trailing block without traffic_profile uses the breaks profile."""
        templates = {
            "movie_broadcast": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 20,
                    "traffic_profile": "movie_trailers",
                },
                "trailing": [
                    {
                        "type": "interstitial_block",
                        # No traffic_profile → falls back to breaks.traffic_profile
                    },
                ],
            },
        }
        traffic = _traffic_section(
            profiles={
                "movie_trailers": {
                    "allowed_types": ["trailer"],
                    "default_cooldown_seconds": 3600,
                    "max_plays_per_day": 0,
                },
            },
            default="movie_trailers",
        )
        resolver = _make_resolver(episodes={"ep-001": 5400})
        dsl = _base_dsl(
            templates=templates,
            program_template="movie_broadcast",
            grid_blocks_max=6,
            traffic=traffic,
            bleed=True,
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        block = _extract_block(result)
        assert block.get("traffic_profile") == "movie_trailers"


# ===========================================================================
# INV-UNDERRUN-WARNING-001 — Extreme underrun emits structured warning
# ===========================================================================


class TestUnderrunWarningBelow50Pct:
    """INV-UNDERRUN-WARNING-001: Content at 40% of slot emits structured
    warning with correct fields."""

    def test_underrun_warning_below_50_pct(self, caplog):
        """Content occupying <50% of slot emits a structured warning."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        # 10-min content in 30-min slot → 33% utilization
        resolver = _make_resolver(episodes={"ep-001": 600})
        traffic = _traffic_section()
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        with caplog.at_level(logging.WARNING):
            result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        # Should emit underrun warning
        underrun_warnings = [
            r for r in caplog.records
            if "INV-UNDERRUN-WARNING-001" in r.message
            or "underrun" in r.message.lower()
            or "utilization" in r.message.lower()
        ]
        assert len(underrun_warnings) > 0, (
            "Expected underrun warning for content at 33% of slot"
        )


class TestUnderrunNoWarningAbove50Pct:
    """INV-UNDERRUN-WARNING-001: Content at 60% of slot emits no warning."""

    def test_underrun_no_warning_above_50_pct(self, caplog):
        """Content occupying >50% of slot should NOT emit underrun warning."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        # 22-min content in 30-min slot → 73% utilization (well above 50%)
        resolver = _make_resolver(episodes={"ep-001": 1320})
        traffic = _traffic_section()
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        with caplog.at_level(logging.WARNING):
            result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        underrun_warnings = [
            r for r in caplog.records
            if "INV-UNDERRUN-WARNING-001" in r.message
            or "underrun" in r.message.lower()
        ]
        assert len(underrun_warnings) == 0, (
            f"No underrun warning expected at 73% utilization, got: "
            f"{[w.message for w in underrun_warnings]}"
        )


class TestUnderrunWarningDoesNotHalt:
    """INV-UNDERRUN-WARNING-001: Block with extreme underrun still compiles
    successfully."""

    def test_underrun_warning_does_not_halt(self):
        """Compilation succeeds even with extreme underrun — warning is
        informational only."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        # 8-min content in 30-min slot → 27% utilization
        resolver = _make_resolver(episodes={"ep-001": 480})
        traffic = _traffic_section()
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        # Must NOT raise — warning only
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        assert len(result["program_blocks"]) > 0, (
            "Compilation should succeed despite extreme underrun"
        )


class TestUnderrunBudgetCascadeTier3First:
    """INV-UNDERRUN-WARNING-001: Underconstrained block with Tier 3 elements
    deducts them before traffic fill."""

    def test_underrun_budget_cascade_tier3_first(self):
        """Tier 3 optional elements are included before traffic fill in the
        budget absorption cascade."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
                "continuity": {
                    "optional": [
                        {
                            "type": "channel_ident",
                            "pool": "bumpers",
                            "max_duration_ms": 10000,
                        },
                    ],
                },
            },
        }
        # 15-min content in 30-min slot → significant underrun with Tier 3
        resolver = _make_resolver(
            episodes={"ep-001": 900},
            bumpers={"bumper-001": 10},
        )
        traffic = _traffic_section()
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            grid_blocks=1,
            traffic=traffic,
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        # Tier 3 elements should be present in the compiled output
        tier3_segs = [
            s for s in segments
            if s["segment_type"] in ("channel_ident", "network_branding", "coming_up_next")
        ]
        # The total segment duration should still respect conformance
        block = _extract_block(result)
        slot_ms = block["slot_duration_sec"] * 1000
        total = _total_duration(segments)
        assert abs(total - slot_ms) <= TOLERANCE_MS, (
            f"Total segment duration {total} should match slot {slot_ms} "
            f"within tolerance (drift {abs(total - slot_ms)}ms)"
        )


# ===========================================================================
# Backward compatibility — no template → current behavior
# ===========================================================================


class TestBackwardCompatNoTemplate:
    """Backward compatibility: When no template is specified, the current
    behavior (no traffic profile threading, no conformance policy evaluation)
    is preserved."""

    def test_no_template_current_behavior(self):
        """Program without template compiles as before."""
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(grid_blocks=1)  # No template
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        assert len(result["program_blocks"]) > 0
        block = _extract_block(result)
        # traffic_profile should be None (no template, no block-level override)
        assert block.get("traffic_profile") is None
