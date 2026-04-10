"""
Contract tests for INV-CUN-FEATURE-FLAG-001: CUN feature gate.

CUN synthesis MUST be gated by channel-level `features.coming_up_next`.
When false or absent, no CUN segments placed, no render jobs created.

Tests cover:
- Schema: features and continuity.coming_up_next validation
- Behavioral: optional_presentation produces zero CUN segments when not declared
- Behavioral: optional_presentation produces CUN segments when declared
- Default: features.coming_up_next defaults to False
"""

from __future__ import annotations

import pytest

from retrovue.config.schema import (
    ChannelFeatures,
    SchemaValidationError,
    validate_channel_yaml,
)
from retrovue.runtime.optional_presentation import evaluate_optional_presentation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def base_channel() -> dict:
    """Minimal valid channel YAML dict."""
    return {
        "channel_id": "test-cun-ch",
        "number": 42,
        "name": "CUN Test Channel",
    }


@pytest.fixture()
def cun_template() -> dict:
    """A valid CUN template entry."""
    return {
        "id": "default",
        "background": "assets/templates/cun/retro_loop_01.mp4",
        "text_area": {"x": 120, "y": 680, "width": 1680, "height": 200},
        "font": "assets/fonts/retro_display.ttf",
        "font_size": 64,
        "font_color": "white",
        "fade_in_ms": 500,
        "fade_out_ms": 500,
    }


@pytest.fixture()
def full_cun_channel(base_channel: dict, cun_template: dict) -> dict:
    """Channel with CUN fully enabled and configured."""
    base_channel["features"] = {"coming_up_next": True}
    base_channel["continuity"] = {
        "coming_up_next": {
            "duration_ms": 10000,
            "render_deadline_margin_ms": 30000,
            "templates": [cun_template],
        }
    }
    return base_channel


def _make_blocks(count: int = 3) -> list[dict]:
    """Build minimal block list for optional_presentation testing."""
    blocks = []
    for i in range(count):
        blocks.append({
            "start_utc_ms": 1000000 + i * 1800000,
            "slot_duration_ms": 1800000,
            "title": f"Program {i + 1}",
            "compiled_segments": [
                {
                    "segment_type": "content",
                    "asset_id": f"asset-{i}",
                    "duration_ms": 1500000,
                },
                {
                    "segment_type": "filler",
                    "asset_id": "filler-default",
                    "duration_ms": 300000,
                },
            ],
        })
    return blocks


# ===========================================================================
# Schema: features.coming_up_next flag
# ===========================================================================

class TestCunFeatureFlagSchema:

    def test_feature_flag_true_accepted(self, full_cun_channel: dict):
        validate_channel_yaml(full_cun_channel)

    def test_feature_flag_false_accepted(self, base_channel: dict):
        base_channel["features"] = {"coming_up_next": False}
        validate_channel_yaml(base_channel)

    def test_no_features_section_backwards_compatible(self, base_channel: dict):
        assert "features" not in base_channel
        validate_channel_yaml(base_channel)

    def test_feature_flag_wrong_type_raises(self, base_channel: dict):
        base_channel["features"] = {"coming_up_next": "yes"}
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(base_channel)
        assert any(
            "coming_up_next" in e["path"] for e in exc_info.value.errors
        )

    def test_features_default_is_false(self):
        """INV-CUN-FEATURE-FLAG-001: default value of coming_up_next is False."""
        features = ChannelFeatures()
        assert features.coming_up_next is False


# ===========================================================================
# Schema: continuity.coming_up_next block
# ===========================================================================

class TestCunContinuitySchema:

    def test_valid_continuity_block_accepted(self, full_cun_channel: dict):
        validate_channel_yaml(full_cun_channel)

    def test_duration_ms_required(self, full_cun_channel: dict):
        del full_cun_channel["continuity"]["coming_up_next"]["duration_ms"]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(full_cun_channel)
        assert any("duration_ms" in e["path"] for e in exc_info.value.errors)

    def test_render_deadline_margin_ms_required(self, full_cun_channel: dict):
        del full_cun_channel["continuity"]["coming_up_next"]["render_deadline_margin_ms"]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(full_cun_channel)
        assert any(
            "render_deadline_margin_ms" in e["path"]
            for e in exc_info.value.errors
        )

    def test_templates_required(self, full_cun_channel: dict):
        del full_cun_channel["continuity"]["coming_up_next"]["templates"]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(full_cun_channel)
        assert any("templates" in e["path"] for e in exc_info.value.errors)

    def test_empty_templates_list_raises(self, full_cun_channel: dict):
        """At least one template is required."""
        full_cun_channel["continuity"]["coming_up_next"]["templates"] = []
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(full_cun_channel)
        assert any(
            "template" in e["message"].lower()
            for e in exc_info.value.errors
        )

    def test_duration_ms_wrong_type_raises(self, full_cun_channel: dict):
        full_cun_channel["continuity"]["coming_up_next"]["duration_ms"] = "ten"
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(full_cun_channel)
        assert any("duration_ms" in e["path"] for e in exc_info.value.errors)

    def test_continuity_without_cun_passes(self, base_channel: dict):
        """continuity section can exist without coming_up_next."""
        base_channel["continuity"] = {}
        validate_channel_yaml(base_channel)


# ===========================================================================
# Schema: CUN template entry validation
# ===========================================================================

class TestCunTemplateSchema:

    def test_template_id_required(self, full_cun_channel: dict):
        full_cun_channel["continuity"]["coming_up_next"]["templates"] = [
            {"background": "foo.mp4"}
        ]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(full_cun_channel)
        assert any("id" in e["path"] for e in exc_info.value.errors)

    def test_template_background_required(self, full_cun_channel: dict):
        full_cun_channel["continuity"]["coming_up_next"]["templates"] = [
            {"id": "default"}
        ]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(full_cun_channel)
        assert any("background" in e["path"] for e in exc_info.value.errors)

    def test_template_text_area_validates_structure(
        self, full_cun_channel: dict, cun_template: dict,
    ):
        bad_template = {
            **cun_template,
            "text_area": {**cun_template["text_area"], "x": "left"},
        }
        full_cun_channel["continuity"]["coming_up_next"]["templates"] = [bad_template]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_channel_yaml(full_cun_channel)
        assert any("x" in e["path"] for e in exc_info.value.errors)


# ===========================================================================
# Behavioral: INV-CUN-FEATURE-FLAG-001 — gate enforcement
# ===========================================================================

class TestCunFeatureFlagBehavior:
    """
    INV-CUN-FEATURE-FLAG-001: The feature flag gate operates at the schedule
    compiler level — when features.coming_up_next is false, the compiler does
    not include coming_up_next in continuity.optional. We validate both
    directions: CUN segments appear when declared, and do not appear when
    omitted.
    """

    def test_cun_segments_appear_when_declared(self):
        """When coming_up_next IS in continuity.optional and feature enabled, CUN segments appear."""
        blocks = _make_blocks(count=3)
        continuity = {
            "optional": [
                {"type": "coming_up_next", "pool": "cun_promos", "max_duration_ms": 10000},
            ],
        }
        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-cun",
            features={"coming_up_next": True},
        )
        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        # CUN in blocks 0 and 1 (last block has no next program)
        assert len(cun_segments) == 2
        for seg in cun_segments:
            assert "next_program_title" in seg

    def test_no_cun_when_not_in_continuity_optional(self):
        """When coming_up_next is NOT in continuity.optional, zero CUN segments."""
        blocks = _make_blocks()
        continuity = {
            "optional": [
                {"type": "channel_ident", "pool": "station_ids", "max_duration_ms": 5000},
            ],
        }
        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-cun",
        )
        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segments) == 0

    def test_no_cun_when_continuity_optional_empty(self):
        """Empty continuity.optional list -> zero CUN segments."""
        blocks = _make_blocks()
        continuity = {"optional": []}
        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-cun",
        )
        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segments) == 0

    def test_cun_last_block_omitted(self):
        """Last block never gets CUN (no next program to announce)."""
        blocks = _make_blocks(count=2)
        continuity = {
            "optional": [
                {"type": "coming_up_next", "pool": "cun_promos", "max_duration_ms": 10000},
            ],
        }
        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-cun",
            features={"coming_up_next": True},
        )
        last_block_cun = [
            seg
            for seg in result[-1]["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(last_block_cun) == 0


# ===========================================================================
# Behavioral: INV-CUN-FEATURE-FLAG-001 — features parameter gate
# ===========================================================================

class TestCunFeatureFlagGate:
    """
    INV-CUN-FEATURE-FLAG-001: evaluate_optional_presentation accepts a
    features dict. When features.coming_up_next is False, CUN segments
    MUST NOT be placed even if coming_up_next is declared in
    continuity.optional.
    """

    def test_feature_flag_false_blocks_cun(self):
        """features.coming_up_next=False → zero CUN even when declared."""
        blocks = _make_blocks(count=3)
        continuity = {
            "optional": [
                {"type": "coming_up_next", "pool": "cun_promos", "max_duration_ms": 10000},
            ],
        }
        features = {"coming_up_next": False}
        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-cun",
            features=features,
        )
        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segments) == 0

    def test_feature_flag_true_allows_cun(self):
        """features.coming_up_next=True → CUN placed normally."""
        blocks = _make_blocks(count=3)
        continuity = {
            "optional": [
                {"type": "coming_up_next", "pool": "cun_promos", "max_duration_ms": 10000},
            ],
        }
        features = {"coming_up_next": True}
        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-cun",
            features=features,
        )
        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segments) == 2

    def test_feature_flag_absent_defaults_to_no_cun(self):
        """No features parameter → CUN skipped (default off)."""
        blocks = _make_blocks(count=3)
        continuity = {
            "optional": [
                {"type": "coming_up_next", "pool": "cun_promos", "max_duration_ms": 10000},
            ],
        }
        # No features parameter — should still work (backwards compat)
        # but default to no CUN
        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-cun",
        )
        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segments) == 0

    def test_feature_flag_does_not_affect_other_tier3(self):
        """features.coming_up_next=False does NOT block channel_ident."""
        blocks = _make_blocks(count=3)
        continuity = {
            "optional": [
                {"type": "channel_ident", "pool": "station_ids", "max_duration_ms": 5000},
                {"type": "coming_up_next", "pool": "cun_promos", "max_duration_ms": 10000},
            ],
        }
        features = {"coming_up_next": False}
        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-cun",
            features=features,
        )
        ident_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "channel_ident"
        ]
        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(ident_segments) == 3  # all blocks get channel_ident
        assert len(cun_segments) == 0    # CUN blocked by feature flag
