"""Contract tests: INV-SC-PRESENTATION-MIDROLL-001

_resolve_presentation_ref MUST extract the midroll key from a presentation
block and attach it as presentation_midroll on the resolved program definition.

This change is additive — preroll and postroll behavior must be unchanged.
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.schedule_compiler import _resolve_presentation_ref
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _pres_defs_with_midroll():
    """Presentation defs with midroll on a sitcom_30 program."""
    return {
        "programs": {
            "sitcom_30": {
                "midroll": [
                    {
                        "type": "traffic",
                        "profile": "sitcom",
                        "fill": "remaining",
                        "placement": {
                            "fallback": {
                                "strategy": "weighted_positions",
                                "positions": [0.30, 0.72],
                                "weights": [1, 1],
                            }
                        },
                    }
                ],
            },
        },
    }


def _pres_defs_full():
    """Presentation defs with preroll, postroll, AND midroll."""
    return {
        "programs": {
            "movies": {
                "preroll": [{"pool": "intros"}, {"pool": "ratings_cards"}],
                "postroll": [
                    {"pool": "coming_up_next_promos"},
                    {"type": "traffic", "profile": "hbo_premium", "fill": "remaining"},
                    {"pool": "station_ids"},
                ],
                "midroll": [
                    {
                        "type": "traffic",
                        "placement": {
                            "fallback": {
                                "positions": [0.33, 0.66],
                                "weights": [1.0, 1.0],
                            }
                        },
                    }
                ],
            },
        },
    }


def _pres_defs_no_midroll():
    """Presentation defs with preroll and postroll but no midroll."""
    return {
        "programs": {
            "movies": {
                "preroll": [{"pool": "intros"}],
                "postroll": [{"pool": "station_ids"}],
            },
        },
    }


def _prog_def(ref: str = "sitcom_30"):
    return {
        "pool": "cheers",
        "fill_mode": "single",
        "grid_blocks_max": 1,
        "presentation": ref,
    }


# ---------------------------------------------------------------------------
# INV-SC-PRESENTATION-MIDROLL-001: midroll extracted and attached
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestMidrollExtracted:
    """_resolve_presentation_ref extracts midroll from pres_block."""

    def test_midroll_present_in_resolved(self):
        """When pres_block has midroll, resolved dict has presentation_midroll."""
        resolved = _resolve_presentation_ref(
            _prog_def("sitcom_30"), _pres_defs_with_midroll(),
        )
        assert "presentation_midroll" in resolved
        assert isinstance(resolved["presentation_midroll"], list)
        assert len(resolved["presentation_midroll"]) == 1

    def test_midroll_content_preserved(self):
        """Midroll entry structure is passed through unchanged."""
        resolved = _resolve_presentation_ref(
            _prog_def("sitcom_30"), _pres_defs_with_midroll(),
        )
        midroll = resolved["presentation_midroll"]
        entry = midroll[0]
        assert entry["type"] == "traffic"
        assert entry["placement"]["fallback"]["positions"] == [0.30, 0.72]
        assert entry["placement"]["fallback"]["weights"] == [1, 1]

    def test_midroll_absent_produces_none_or_empty(self):
        """When pres_block has no midroll, presentation_midroll is None or []."""
        resolved = _resolve_presentation_ref(
            _prog_def("movies"), _pres_defs_no_midroll(),
        )
        midroll = resolved.get("presentation_midroll")
        assert midroll is None or midroll == [], (
            f"Missing midroll must produce None or [], got {midroll!r}"
        )


@pytest.mark.contract
class TestMidrollDoesNotAffectPrerollPostroll:
    """Adding midroll extraction must not change preroll/postroll behavior."""

    def test_preroll_unchanged_with_midroll(self):
        """Preroll resolution unaffected when midroll is present."""
        resolved = _resolve_presentation_ref(
            _prog_def("movies"), _pres_defs_full(),
        )
        preroll = resolved.get("presentation", [])
        assert len(preroll) == 2
        assert preroll[0] == {"pool": "intros"}
        assert preroll[1] == {"pool": "ratings_cards"}

    def test_postroll_unchanged_with_midroll(self):
        """Postroll resolution unaffected when midroll is present."""
        resolved = _resolve_presentation_ref(
            _prog_def("movies"), _pres_defs_full(),
        )
        postroll = resolved.get("presentation_postroll", [])
        assert len(postroll) == 3
        traffic_entries = [
            e for e in postroll
            if isinstance(e, dict) and e.get("type") == "traffic"
        ]
        assert len(traffic_entries) == 1

    def test_preroll_unchanged_without_midroll(self):
        """Preroll resolution unaffected when midroll is absent."""
        resolved = _resolve_presentation_ref(
            _prog_def("movies"), _pres_defs_no_midroll(),
        )
        preroll = resolved.get("presentation", [])
        assert len(preroll) == 1

    def test_postroll_unchanged_without_midroll(self):
        """Postroll resolution unaffected when midroll is absent."""
        resolved = _resolve_presentation_ref(
            _prog_def("movies"), _pres_defs_no_midroll(),
        )
        postroll = resolved.get("presentation_postroll", [])
        assert len(postroll) == 1


@pytest.mark.contract
class TestMidrollEdgeCases:
    """Edge cases for midroll extraction."""

    def test_no_presentation_ref_no_midroll(self):
        """Program with no presentation ref gets no midroll."""
        prog_def = {"pool": "cheers", "fill_mode": "single", "grid_blocks_max": 1}
        resolved = _resolve_presentation_ref(prog_def, _pres_defs_with_midroll())
        assert "presentation_midroll" not in resolved

    def test_presentation_defs_none_no_midroll(self):
        """Null presentation_defs produces no midroll."""
        resolved = _resolve_presentation_ref(_prog_def("sitcom_30"), None)
        assert "presentation_midroll" not in resolved

    def test_unresolvable_ref_no_midroll(self):
        """Ref that doesn't match any presentation block gets no midroll."""
        resolved = _resolve_presentation_ref(
            _prog_def("nonexistent"), _pres_defs_with_midroll(),
        )
        midroll = resolved.get("presentation_midroll")
        assert midroll is None or midroll == []
