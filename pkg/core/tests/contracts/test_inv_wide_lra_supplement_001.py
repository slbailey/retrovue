"""
Contract Tests: INV-WIDE-LRA-SUPPLEMENT-001, INV-LOUDNESS-LRA-PERSISTENCE-001
Design reference: docs/design/WIDE_LRA_NORMALIZATION.md

INV-WIDE-LRA-SUPPLEMENT-001:
  Wide-LRA content MAY receive a bounded supplemental normalization gain
  when the normalization policy determines it improves dialogue intelligibility.
  1. Supplement is non-negative and bounded: 0 <= supplement <= MAX_SUPPLEMENT_DB
  2. Supplement is zero when LRA is absent or below qualifying threshold
  3. Supplement is monotonically non-decreasing with LRA
  4. Broadcast-native (narrow LRA) content is unaffected

INV-LOUDNESS-LRA-PERSISTENCE-001:
  Loudness enrichment MUST persist LRA when available.
  1. loudness_range_lu stored in probed payload when ebur128 reports LRA
  2. Assets with loudness but missing loudness_range_lu eligible for re-enrichment
  3. loudness_range_lu does not cross Core/AIR boundary

All tests are deterministic and require no media files or AIR process.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from retrovue.adapters.enrichers.loudness_enricher import (
    LoudnessEnricher,
    TARGET_LUFS,
    compute_gain_db,
    get_gain_db_from_probed,
    needs_loudness_measurement,
    LRA_THRESHOLD,
    SUPPLEMENT_SCALE,
    MAX_SUPPLEMENT_DB,
)
from retrovue.adapters.importers.base import DiscoveredItem


# ---------------------------------------------------------------------------
# INV-WIDE-LRA-SUPPLEMENT-001 Rule 2: Zero supplement when LRA absent/below
# ---------------------------------------------------------------------------


class TestSupplementZeroBelowThreshold:
    """Supplement MUST be zero when LRA is absent or below threshold."""

    def test_no_lra(self) -> None:
        """LRA=None → supplement is zero, gain equals base."""
        assert compute_gain_db(-22.1) == pytest.approx(TARGET_LUFS - (-22.1))
        assert compute_gain_db(-22.1, lra_lu=None) == pytest.approx(TARGET_LUFS - (-22.1))

    def test_lra_below_threshold(self) -> None:
        """LRA below threshold → supplement is zero."""
        base = TARGET_LUFS - (-24.5)
        assert compute_gain_db(-24.5, lra_lu=9.0) == pytest.approx(base)

    def test_lra_at_threshold(self) -> None:
        """LRA exactly at threshold → supplement is zero."""
        base = TARGET_LUFS - (-25.0)
        assert compute_gain_db(-25.0, lra_lu=LRA_THRESHOLD) == pytest.approx(base)

    def test_broadcast_native_unaffected(self) -> None:
        """Cheers-class broadcast content (LRA 9.0) gets no supplement."""
        no_lra = compute_gain_db(-24.5)
        with_lra = compute_gain_db(-24.5, lra_lu=9.0)
        assert no_lra == pytest.approx(with_lra)


# ---------------------------------------------------------------------------
# INV-WIDE-LRA-SUPPLEMENT-001 Rule 1: Supplement positive and bounded
# ---------------------------------------------------------------------------


class TestSupplementBounded:
    """Supplement MUST be non-negative and bounded by MAX_SUPPLEMENT_DB."""

    def test_supplement_positive_above_threshold(self) -> None:
        """LRA above threshold → gain is higher than base (supplement > 0)."""
        base = TARGET_LUFS - (-22.1)
        with_supplement = compute_gain_db(-22.1, lra_lu=21.1)
        assert with_supplement > base

    def test_supplement_bounded_by_max(self) -> None:
        """Extreme LRA → supplement capped at MAX_SUPPLEMENT_DB."""
        base = TARGET_LUFS - (-22.0)
        # LRA = 100 LU (absurd) should still cap
        with_extreme = compute_gain_db(-22.0, lra_lu=100.0)
        supplement = with_extreme - base
        assert supplement == pytest.approx(MAX_SUPPLEMENT_DB)

    def test_supplement_never_negative(self) -> None:
        """Supplement is never negative for any LRA value."""
        for lra in [0.0, 5.0, 10.0, 14.9, 15.0, 15.1, 20.0, 30.0]:
            base = TARGET_LUFS - (-25.0)
            with_lra = compute_gain_db(-25.0, lra_lu=lra)
            assert with_lra >= base, f"Negative supplement at LRA={lra}"


# ---------------------------------------------------------------------------
# INV-WIDE-LRA-SUPPLEMENT-001 Rule 3: Monotonically non-decreasing
# ---------------------------------------------------------------------------


class TestSupplementMonotonic:
    """Supplement MUST be monotonically non-decreasing with LRA."""

    def test_monotonic_across_range(self) -> None:
        """Increasing LRA → non-decreasing gain."""
        integrated = -25.0
        prev_gain = compute_gain_db(integrated, lra_lu=0.0)
        for lra in range(1, 40):
            gain = compute_gain_db(integrated, lra_lu=float(lra))
            assert gain >= prev_gain, f"Gain decreased at LRA={lra}"
            prev_gain = gain


# ---------------------------------------------------------------------------
# INV-WIDE-LRA-SUPPLEMENT-001: Known content examples from design doc
# ---------------------------------------------------------------------------


class TestDesignDocExamples:
    """Verify the exact examples from the design document (Section 4.1)."""

    def test_ghostbusters(self) -> None:
        """Ghostbusters: integrated=-22.1, LRA=21.1 → base=-1.9 + supplement=3.05 = 1.15."""
        result = compute_gain_db(-22.1, lra_lu=21.1)
        # base = -24.0 - (-22.1) = -1.9; supplement = (21.1 - 15.0) * 0.5 = 3.05
        assert result == pytest.approx(1.15, abs=0.01)

    def test_babylon5(self) -> None:
        """Babylon 5: integrated=-25.8, LRA=16.0 → base=1.8 + supplement=0.5 = 2.3."""
        result = compute_gain_db(-25.8, lra_lu=16.0)
        # base = -24.0 - (-25.8) = 1.8; supplement = (16.0 - 15.0) * 0.5 = 0.5
        assert result == pytest.approx(2.3, abs=0.01)

    def test_cheers(self) -> None:
        """Cheers: integrated=-24.5, LRA=9.0 → gain=+0.5 (no supplement)."""
        result = compute_gain_db(-24.5, lra_lu=9.0)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_ghostbusters_supplement_value(self) -> None:
        """Ghostbusters supplement is exactly (21.1 - 15.0) * 0.5 = 3.05."""
        base = TARGET_LUFS - (-22.1)  # -1.9
        total = compute_gain_db(-22.1, lra_lu=21.1)
        supplement = total - base
        expected_supplement = (21.1 - LRA_THRESHOLD) * SUPPLEMENT_SCALE
        assert supplement == pytest.approx(expected_supplement)


# ---------------------------------------------------------------------------
# INV-WIDE-LRA-SUPPLEMENT-001: Policy defaults
# ---------------------------------------------------------------------------


class TestPolicyDefaults:
    """Policy defaults match the design document (Section 5)."""

    def test_lra_threshold(self) -> None:
        assert LRA_THRESHOLD == 15.0

    def test_supplement_scale(self) -> None:
        assert SUPPLEMENT_SCALE == 0.5

    def test_max_supplement(self) -> None:
        assert MAX_SUPPLEMENT_DB == 6.0


# ---------------------------------------------------------------------------
# INV-LOUDNESS-LRA-PERSISTENCE-001 Rule 1: LRA stored in probed
# ---------------------------------------------------------------------------


class TestLraPersistence:
    """LRA MUST be stored in probed payload when ebur128 reports it."""

    @patch("retrovue.adapters.enrichers.loudness_enricher.subprocess.run")
    def test_lra_stored_in_probed(self, mock_run: MagicMock) -> None:
        """measure_loudness returns loudness_range_lu when ebur128 reports LRA."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr=(
                "[Parsed_ebur128_0 @ 0x1234] Summary:\n"
                "\n"
                "  Integrated loudness:\n"
                "    I:         -22.1 LUFS\n"
                "    Threshold: -32.1 LUFS\n"
                "\n"
                "  Loudness range:\n"
                "    LRA:        21.1 LU\n"
                "    LRA low:   -38.4 LUFS\n"
                "    LRA high:  -17.3 LUFS\n"
            ),
        )
        enricher = LoudnessEnricher()
        result = enricher.measure_loudness("/tmp/test.mp4")
        assert result["loudness_range_lu"] == pytest.approx(21.1)

    @patch("retrovue.adapters.enrichers.loudness_enricher.subprocess.run")
    def test_lra_absent_when_not_reported(self, mock_run: MagicMock) -> None:
        """measure_loudness omits loudness_range_lu when ebur128 doesn't report LRA."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr=(
                "[Parsed_ebur128_0 @ 0x1234] Summary:\n"
                "\n"
                "  Integrated loudness:\n"
                "    I:         -20.3 LUFS\n"
                "    Threshold: -30.3 LUFS\n"
            ),
        )
        enricher = LoudnessEnricher()
        result = enricher.measure_loudness("/tmp/test.mp4")
        assert "loudness_range_lu" not in result

    @patch("retrovue.adapters.enrichers.loudness_enricher.subprocess.run")
    def test_gain_db_includes_supplement_when_lra_present(self, mock_run: MagicMock) -> None:
        """gain_db in probed reflects supplement when LRA exceeds threshold."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr=(
                "[Parsed_ebur128_0 @ 0x1234] Summary:\n"
                "\n"
                "  Integrated loudness:\n"
                "    I:         -22.1 LUFS\n"
                "    Threshold: -32.1 LUFS\n"
                "\n"
                "  Loudness range:\n"
                "    LRA:        21.1 LU\n"
                "    LRA low:   -38.4 LUFS\n"
                "    LRA high:  -17.3 LUFS\n"
            ),
        )
        enricher = LoudnessEnricher()
        result = enricher.measure_loudness("/tmp/test.mp4")
        # base_gain = -24.0 - (-22.1) = -1.9
        # supplement = (21.1 - 15.0) * 0.5 = 3.05
        # total = -1.9 + 3.05 = 1.15
        expected = compute_gain_db(-22.1, lra_lu=21.1)
        assert result["gain_db"] == pytest.approx(expected)

    @patch("retrovue.adapters.enrichers.loudness_enricher.subprocess.run")
    def test_enricher_probed_has_lra(self, mock_run: MagicMock) -> None:
        """LoudnessEnricher.enrich persists loudness_range_lu to probed payload."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr=(
                "[Parsed_ebur128_0 @ 0x1234] Summary:\n"
                "\n"
                "  Integrated loudness:\n"
                "    I:         -22.1 LUFS\n"
                "    Threshold: -32.1 LUFS\n"
                "\n"
                "  Loudness range:\n"
                "    LRA:        21.1 LU\n"
                "    LRA low:   -38.4 LUFS\n"
                "    LRA high:  -17.3 LUFS\n"
            ),
        )
        enricher = LoudnessEnricher()
        item = DiscoveredItem(path_uri="/tmp/test.mp4", probed={})
        result = enricher.enrich(item)
        assert result.probed["loudness"]["loudness_range_lu"] == pytest.approx(21.1)


# ---------------------------------------------------------------------------
# INV-LOUDNESS-LRA-PERSISTENCE-001 Rule 2: Re-enrichment trigger
# ---------------------------------------------------------------------------


class TestReEnrichmentTrigger:
    """Assets with loudness but missing LRA MUST be eligible for re-enrichment."""

    def test_needs_measurement_when_lra_missing(self) -> None:
        """Probed has gain_db but no loudness_range_lu → needs re-measurement."""
        probed = {"loudness": {"integrated_lufs": -20.3, "gain_db": -3.7, "target_lufs": -24.0}}
        assert needs_loudness_measurement(probed) is True

    def test_no_measurement_when_lra_present(self) -> None:
        """Probed has gain_db AND loudness_range_lu → no re-measurement needed."""
        probed = {
            "loudness": {
                "integrated_lufs": -22.1,
                "gain_db": 1.15,
                "target_lufs": -24.0,
                "loudness_range_lu": 21.1,
            }
        }
        assert needs_loudness_measurement(probed) is False

    def test_needs_measurement_when_no_probed(self) -> None:
        """No probed → needs measurement (existing behavior preserved)."""
        assert needs_loudness_measurement(None) is True

    def test_needs_measurement_when_no_loudness(self) -> None:
        """Probed without loudness key → needs measurement (existing behavior preserved)."""
        assert needs_loudness_measurement({"duration_ms": 120000}) is True
