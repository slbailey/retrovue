"""
Runtime behavior tests for INV-FIVS-PTS-CONSISTENCY (slope-based formulation).

Contract: pkg/air/docs/contracts/playout/INV-FIVS-PTS-CONSISTENCY.md

These tests validate the emission-path integration layer (PTSDriftLogger):
  - Rate limiting: max 1 PTS_DRIFT_DETECTED per second per asset
  - Segment boundary reset on segment_id change
  - Frame emission unaffected by drift detection
  - Cadence repeat filtering (was_decoded=False excluded)

The slope validator (PTSSlopeValidator) is tested separately in
test_inv_fivs_pts_consistency.py. These tests cover the runtime wrapper.
"""

from __future__ import annotations

import dataclasses
import logging
import sys
from pathlib import Path

# Add pkg/air to sys.path so we can import the playout module.
_AIR_ROOT = Path(__file__).resolve().parents[2]
if str(_AIR_ROOT) not in sys.path:
    sys.path.insert(0, str(_AIR_ROOT))

from playout.pts_drift_logger import PTSDriftLogger


# ---------------------------------------------------------------------------
# Minimal frame for testing.
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Frame:
    pts_us: int
    was_decoded: bool = True


# Constants.
DELTA_24FPS_US = 1_000_000 // 24  # 41666 µs
DELTA_30FPS_US = 1_000_000 // 30  # 33333 µs

# Small window for tests.
TEST_WINDOW = 4


def _make_consistent_frames(count: int, delta_us: int, start_pts: int = 0) -> list[Frame]:
    """Generate `count` frames with consistent PTS spacing."""
    frames = []
    pts = start_pts
    for _ in range(count):
        frames.append(Frame(pts_us=pts))
        pts += delta_us
    return frames


# ===========================================================================
# Test 1: Rate limiting
# ===========================================================================

class TestRateLimiting:
    """PTS_DRIFT_DETECTED must be logged at most once per second per asset."""

    def test_rate_limiting_suppresses_within_one_second(self, caplog):
        """Many drifted frames within 1 second produce only one log."""
        clock_time = [0.0]

        def fake_clock() -> float:
            return clock_time[0]

        dl = PTSDriftLogger(clock=fake_clock, slope_window=TEST_WINDOW)

        # Establish slope with consistent frames.
        frames = _make_consistent_frames(TEST_WINDOW + 1, DELTA_24FPS_US)
        for f in frames:
            dl.validate_and_log(f, asset_uri="test")

        # Now feed 10 drifted frames (2× normal delta) within 100ms.
        last_pts = frames[-1].pts_us
        with caplog.at_level(logging.WARNING, logger="retrovue.air.playout"):
            for i in range(10):
                bad_pts = last_pts + (i + 1) * 2 * DELTA_24FPS_US
                dl.validate_and_log(
                    Frame(pts_us=bad_pts),
                    asset_uri="test",
                )
                clock_time[0] += 0.01  # 10ms per frame

        drift_records = [
            r for r in caplog.records if "PTS_DRIFT_DETECTED" in r.message
        ]
        assert len(drift_records) == 1, (
            f"Expected 1 PTS_DRIFT_DETECTED log within 100ms, got {len(drift_records)}"
        )

    def test_rate_limiting_allows_after_one_second(self, caplog):
        """A second log is allowed after 1 second has elapsed."""
        clock_time = [0.0]

        def fake_clock() -> float:
            return clock_time[0]

        dl = PTSDriftLogger(clock=fake_clock, slope_window=TEST_WINDOW)

        # Establish slope.
        frames = _make_consistent_frames(TEST_WINDOW + 1, DELTA_24FPS_US)
        for f in frames:
            dl.validate_and_log(f, asset_uri="test")

        last_pts = frames[-1].pts_us

        with caplog.at_level(logging.WARNING, logger="retrovue.air.playout"):
            # First drifted frame at t=0.
            dl.validate_and_log(
                Frame(pts_us=last_pts + 5 * DELTA_24FPS_US),
                asset_uri="test",
            )

            # Second at t=0.5 — suppressed.
            clock_time[0] = 0.5
            dl.validate_and_log(
                Frame(pts_us=last_pts + 10 * DELTA_24FPS_US),
                asset_uri="test",
            )

            # Third at t=1.1 — allowed.
            clock_time[0] = 1.1
            dl.validate_and_log(
                Frame(pts_us=last_pts + 15 * DELTA_24FPS_US),
                asset_uri="test",
            )

        drift_records = [
            r for r in caplog.records if "PTS_DRIFT_DETECTED" in r.message
        ]
        assert len(drift_records) == 2, (
            f"Expected 2 PTS_DRIFT_DETECTED logs (t=0, t=1.1), got {len(drift_records)}"
        )


# ===========================================================================
# Test 2: Frame emission unaffected
# ===========================================================================

class TestFrameEmissionUnaffected:
    """Frame emission must always occur, even with drift."""

    def test_emit_fn_called_for_every_frame(self):
        """emit_fn is called for every frame, drifted or not."""
        dl = PTSDriftLogger(slope_window=TEST_WINDOW)
        emitted: list[Frame] = []

        # Establish slope.
        frames = _make_consistent_frames(TEST_WINDOW + 1, DELTA_24FPS_US)
        for f in frames:
            dl.validate_and_log(f, emit_fn=emitted.append)

        # Mix of good and drifted frames.
        last_pts = frames[-1].pts_us
        for i in range(10):
            pts = last_pts + DELTA_24FPS_US if i % 2 == 0 else last_pts + 5 * DELTA_24FPS_US
            dl.validate_and_log(Frame(pts_us=pts), emit_fn=emitted.append)
            last_pts = pts

        total = TEST_WINDOW + 1 + 10
        assert len(emitted) == total, (
            f"Expected {total} frames emitted, got {len(emitted)}"
        )

    def test_emitted_frame_is_same_object(self):
        """The returned frame must be the same object passed in."""
        dl = PTSDriftLogger(slope_window=TEST_WINDOW)

        # Establish slope.
        frames = _make_consistent_frames(TEST_WINDOW + 1, DELTA_24FPS_US)
        for f in frames:
            dl.validate_and_log(f)

        # Drifted frame.
        frame = Frame(pts_us=frames[-1].pts_us + 10 * DELTA_24FPS_US)
        returned_frame, _ = dl.validate_and_log(frame)
        assert returned_frame is frame


# ===========================================================================
# Test 3: Segment boundary reset
# ===========================================================================

class TestSegmentBoundaryReset:
    """Slope state must reset when segment_id changes."""

    def test_segment_boundary_resets_slope(self, caplog):
        """Changing segment_id resets slope. New segment re-establishes its own."""
        dl = PTSDriftLogger(slope_window=TEST_WINDOW)

        # Segment 0: establish 24fps slope.
        frames_a = _make_consistent_frames(TEST_WINDOW + 1, DELTA_24FPS_US)
        for f in frames_a:
            dl.validate_and_log(f, segment_id=0)

        # Segment 1: establish 30fps slope (completely different cadence).
        # Without reset, the 30fps deltas would trigger drift against 24fps slope.
        frames_b = _make_consistent_frames(TEST_WINDOW + 1, DELTA_30FPS_US, start_pts=5_000_000)

        with caplog.at_level(logging.WARNING, logger="retrovue.air.playout"):
            for f in frames_b:
                dl.validate_and_log(f, segment_id=1)

            # Additional 30fps frames — should all pass.
            last_pts = frames_b[-1].pts_us
            for _ in range(5):
                last_pts += DELTA_30FPS_US
                dl.validate_and_log(Frame(pts_us=last_pts), segment_id=1)

        drift_records = [
            r for r in caplog.records if "PTS_DRIFT_DETECTED" in r.message
        ]
        assert len(drift_records) == 0, (
            f"Expected 0 drift after segment boundary reset, got {len(drift_records)}"
        )

    def test_no_reset_without_segment_change(self, caplog):
        """Without segment_id change, slope carries over (drift detected)."""
        clock_time = [0.0]

        def fake_clock() -> float:
            return clock_time[0]

        dl = PTSDriftLogger(clock=fake_clock, slope_window=TEST_WINDOW)

        # Establish 24fps slope in segment 0.
        frames = _make_consistent_frames(TEST_WINDOW + 1, DELTA_24FPS_US)
        for f in frames:
            dl.validate_and_log(f, segment_id=0)

        # Feed a frame with 3× normal delta (same segment) — drift expected.
        last_pts = frames[-1].pts_us
        with caplog.at_level(logging.WARNING, logger="retrovue.air.playout"):
            dl.validate_and_log(
                Frame(pts_us=last_pts + 3 * DELTA_24FPS_US),
                segment_id=0,
                asset_uri="same",
            )

        drift_records = [
            r for r in caplog.records if "PTS_DRIFT_DETECTED" in r.message
        ]
        assert len(drift_records) == 1, (
            f"Expected 1 drift (no segment reset), got {len(drift_records)}"
        )


# ===========================================================================
# Test 4: Cadence repeats excluded
# ===========================================================================

class TestCadenceRepeatsExcluded:
    """Frames with was_decoded=False must not affect slope measurement."""

    def test_cadence_repeats_ignored(self):
        """Cadence repeat frames (was_decoded=False) are passed through
        without contributing to slope state."""
        dl = PTSDriftLogger(slope_window=TEST_WINDOW)

        # Establish slope with real decodes.
        frames = _make_consistent_frames(TEST_WINDOW + 1, DELTA_24FPS_US)
        for f in frames:
            dl.validate_and_log(f)

        last_pts = frames[-1].pts_us

        # Interleave cadence repeats — these should be invisible to slope.
        for _ in range(5):
            # Cadence repeat (same PTS, was_decoded=False).
            repeat = Frame(pts_us=last_pts, was_decoded=False)
            _, event = dl.validate_and_log(repeat)
            assert event is None, "Cadence repeat should not trigger drift"

            # Real decode with correct delta.
            last_pts += DELTA_24FPS_US
            real = Frame(pts_us=last_pts, was_decoded=True)
            _, event = dl.validate_and_log(real)
            assert event is None, (
                f"Real decode with correct delta should not trigger drift, got {event}"
            )
