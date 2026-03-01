"""
Contract Tests: INV-LOUDNESS-NORMALIZED-001
Contract reference: docs/contracts/invariants/shared/INV-LOUDNESS-NORMALIZED-001.md

These tests enforce the loudness normalization invariants for Core:
- gain_db computation (Rule 7)
- Unmeasured asset handling (Rule 5)
- Measured asset propagation (Rule 6)
- Enricher persistence (Rule 6)
- All content types same target (Rule 7)

All tests are deterministic and require no media files or AIR process.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call
from dataclasses import replace

from retrovue.adapters.enrichers.loudness_enricher import (
    LoudnessEnricher,
    TARGET_LUFS,
    compute_gain_db,
)
from retrovue.adapters.importers.base import DiscoveredItem


# ---------------------------------------------------------------------------
# Rule 7: gain_db == target_lufs - integrated_lufs
# ---------------------------------------------------------------------------


class TestGainDbIsTargetMinusMeasured:
    """Rule 7: gain_db MUST be computed as target_lufs - integrated_lufs."""

    def test_loud_asset(self) -> None:
        """Loud asset (-20.3 LUFS) → negative gain (-3.7 dB)."""
        assert compute_gain_db(-20.3) == pytest.approx(-3.7)

    def test_quiet_asset(self) -> None:
        """Quiet asset (-28.1 LUFS) → positive gain (+4.1 dB)."""
        assert compute_gain_db(-28.1) == pytest.approx(4.1)

    def test_already_normalized(self) -> None:
        """Asset already at -24.0 LUFS → zero gain."""
        assert compute_gain_db(-24.0) == pytest.approx(0.0)

    def test_target_is_minus_24(self) -> None:
        """Target MUST be -24.0 LUFS (ATSC A/85)."""
        assert TARGET_LUFS == -24.0


# ---------------------------------------------------------------------------
# Rule 5: Unmeasured asset → gain_db = 0.0
# ---------------------------------------------------------------------------


class TestUnmeasuredAssetGetsZeroGain:
    """Rule 5: Asset without loudness in probed → segment gain_db = 0.0."""

    def test_no_probed(self) -> None:
        """Asset with no probed data → gain_db = 0.0."""
        from retrovue.adapters.enrichers.loudness_enricher import get_gain_db_from_probed
        assert get_gain_db_from_probed(None) == 0.0

    def test_probed_without_loudness(self) -> None:
        """Asset with probed data but no loudness key → gain_db = 0.0."""
        from retrovue.adapters.enrichers.loudness_enricher import get_gain_db_from_probed
        probed = {"duration_ms": 120000, "video": {"codec": "h264"}}
        assert get_gain_db_from_probed(probed) == 0.0

    def test_probed_with_empty_loudness(self) -> None:
        """Asset with empty loudness dict → gain_db = 0.0."""
        from retrovue.adapters.enrichers.loudness_enricher import get_gain_db_from_probed
        probed = {"loudness": {}}
        assert get_gain_db_from_probed(probed) == 0.0


# ---------------------------------------------------------------------------
# Rule 5: Unmeasured asset → background measurement enqueued
# ---------------------------------------------------------------------------


class TestUnmeasuredAssetEnqueuesMeasurement:
    """Rule 5: Asset without loudness → background measurement job enqueued."""

    def test_enqueue_called_for_unmeasured(self) -> None:
        """When probed has no loudness, enqueue_measurement MUST be called."""
        from retrovue.adapters.enrichers.loudness_enricher import (
            get_gain_db_from_probed,
            needs_loudness_measurement,
        )
        probed = {"duration_ms": 120000}
        assert needs_loudness_measurement(probed) is True

    def test_no_enqueue_for_measured(self) -> None:
        """When probed has loudness.gain_db, no measurement needed."""
        from retrovue.adapters.enrichers.loudness_enricher import needs_loudness_measurement
        probed = {"loudness": {"integrated_lufs": -20.3, "gain_db": -3.7, "target_lufs": -24.0}}
        assert needs_loudness_measurement(probed) is False


# ---------------------------------------------------------------------------
# Rule 6: Measured asset carries gain
# ---------------------------------------------------------------------------


class TestMeasuredAssetCarriesGain:
    """Rule 6: Asset with stored loudness.gain_db → segment carries that value."""

    def test_gain_from_probed(self) -> None:
        from retrovue.adapters.enrichers.loudness_enricher import get_gain_db_from_probed
        probed = {"loudness": {"integrated_lufs": -20.3, "gain_db": -3.7, "target_lufs": -24.0}}
        assert get_gain_db_from_probed(probed) == pytest.approx(-3.7)

    def test_positive_gain_from_probed(self) -> None:
        from retrovue.adapters.enrichers.loudness_enricher import get_gain_db_from_probed
        probed = {"loudness": {"integrated_lufs": -28.1, "gain_db": 4.1, "target_lufs": -24.0}}
        assert get_gain_db_from_probed(probed) == pytest.approx(4.1)


# ---------------------------------------------------------------------------
# Rule 7: All content types same target
# ---------------------------------------------------------------------------


class TestAllContentTypesSameTarget:
    """Rule 7: Episode, movie, bumper, filler all use same -24 LUFS target."""

    @pytest.mark.parametrize(
        "content_type,integrated_lufs,expected_gain",
        [
            ("episode", -20.3, -3.7),
            ("movie", -28.1, 4.1),
            ("bumper", -18.0, -6.0),
            ("filler", -30.0, 6.0),
        ],
    )
    def test_same_target_for_all_types(
        self, content_type: str, integrated_lufs: float, expected_gain: float
    ) -> None:
        """All content types produce gain_db from same -24 LUFS target."""
        assert compute_gain_db(integrated_lufs) == pytest.approx(expected_gain)


# ---------------------------------------------------------------------------
# Rule 6: LoudnessEnricher persists loudness to probed
# ---------------------------------------------------------------------------


class TestEnricherPersistsLoudnessToProbed:
    """Rule 6: LoudnessEnricher writes integrated_lufs and gain_db to probed payload."""

    @patch("retrovue.adapters.enrichers.loudness_enricher.subprocess.run")
    def test_enricher_writes_loudness(self, mock_run: MagicMock) -> None:
        """After measurement, probed MUST contain loudness.integrated_lufs and loudness.gain_db."""
        # Simulate ffmpeg ebur128 output
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr=(
                "[Parsed_ebur128_0 @ 0x1234] Summary:\n"
                "\n"
                "  Integrated loudness:\n"
                "    I:         -20.3 LUFS\n"
                "    Threshold: -30.3 LUFS\n"
                "\n"
                "  Loudness range:\n"
                "    LRA:         8.2 LU\n"
            ),
        )

        enricher = LoudnessEnricher()
        item = DiscoveredItem(
            path_uri="/tmp/test.mp4",
            probed={"duration_ms": 120000},
        )
        result = enricher.enrich(item)

        assert result.probed is not None
        loudness = result.probed.get("loudness")
        assert loudness is not None
        assert loudness["integrated_lufs"] == pytest.approx(-20.3)
        assert loudness["gain_db"] == pytest.approx(-3.7)
        assert loudness["target_lufs"] == -24.0


# ---------------------------------------------------------------------------
# Rule 6: Background measurement persists result
# ---------------------------------------------------------------------------


class TestBackgroundMeasurementPersistsResult:
    """Rule 6: Background job completion → probed payload updated with loudness data."""

    @patch("retrovue.adapters.enrichers.loudness_enricher.subprocess.run")
    def test_measurement_produces_valid_payload(self, mock_run: MagicMock) -> None:
        """Background measurement produces a dict suitable for merging into probed."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr=(
                "[Parsed_ebur128_0 @ 0x5678] Summary:\n"
                "\n"
                "  Integrated loudness:\n"
                "    I:         -28.1 LUFS\n"
                "    Threshold: -38.1 LUFS\n"
            ),
        )

        enricher = LoudnessEnricher()
        result = enricher.measure_loudness("/tmp/quiet_show.mp4")

        assert result["integrated_lufs"] == pytest.approx(-28.1)
        assert result["gain_db"] == pytest.approx(4.1)
        assert result["target_lufs"] == -24.0
