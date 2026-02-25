"""Contract: PAD is a first-class producer that primes audio before emission.

Tests the claim that PAD (black + silence) in the playout path:
- Is a first-class producer (not an inline fallback)
- Primes audio before first emission (audio depth > 0 at first tick)
- Can produce at least one silent audio frame buffer
- Advances audio PTS monotonically across frames
- Remains audio-primed when switching into PAD at a seam

This test is implemented in Core (Python). If the PAD producer lives in AIR (C++)
and cannot be instantiated from Python, the test fails at resolution and reports
the responsible component (AIR PadProducer).
"""

import pytest


def test_pad_producer_exists_and_can_be_started_in_isolation():
    """PAD playout component must exist in the runtime and be startable without ChannelManager."""
    # Resolve the class that represents PAD in the playout path.
    # In Core we only have segment_type="pad" in plans; the actual producer is in AIR.
    pad_producer_class = None
    try:
        from retrovue.runtime import channel_manager
        if hasattr(channel_manager, "PadProducer"):
            pad_producer_class = channel_manager.PadProducer
    except ImportError:
        pass
    try:
        from retrovue.runtime import playout_session
        if hasattr(playout_session, "PadProducer"):
            pad_producer_class = playout_session.PadProducer
    except ImportError:
        pass
    if pad_producer_class is None:
        pytest.fail(
            "PAD producer not found in Core runtime. "
            "PadProducer is implemented in AIR (C++, pkg/air PadProducer.hpp); "
            "Core only sends SEGMENT_TYPE_PAD in BlockPlans. "
            "This contract cannot be exercised from Python — use pkg/air/tests/contracts/BlockPlan/PadProducerContractTests.cpp."
        )
    assert pad_producer_class is not None, "PadProducer class must exist"


def test_pad_reports_audio_primed_before_first_emission():
    """Immediately after init (before any frame emission), PAD must report audio primed or depth > 0."""
    pad_producer_class = None
    try:
        from retrovue.runtime import channel_manager
        if hasattr(channel_manager, "PadProducer"):
            pad_producer_class = channel_manager.PadProducer
    except ImportError:
        pass
    if pad_producer_class is None:
        pytest.skip("PadProducer not in Core; see test_pad_producer_exists_and_can_be_started_in_isolation")
    # Minimal format: 640x480, 30/1 fps
    producer = pad_producer_class(640, 480, 30, 1)
    producer.start()
    try:
        audio_primed = getattr(producer, "audio_primed", None) or getattr(producer, "is_audio_primed", None)
        audio_depth = getattr(producer, "audio_depth_ms", None) or getattr(producer, "audio_depth", None)
        assert (audio_primed is True or (audio_depth is not None and audio_depth > 0)), (
            "PAD must report audio primed or audio depth > 0 before first emission"
        )
    finally:
        if hasattr(producer, "stop"):
            producer.stop()


def test_pad_produces_at_least_one_silent_audio_frame_buffer():
    """PAD must be able to produce at least one silent audio frame buffer."""
    pad_producer_class = None
    try:
        from retrovue.runtime import channel_manager
        if hasattr(channel_manager, "PadProducer"):
            pad_producer_class = channel_manager.PadProducer
    except ImportError:
        pass
    if pad_producer_class is None:
        pytest.skip("PadProducer not in Core")
    producer = pad_producer_class(640, 480, 30, 1)
    producer.start()
    try:
        # Expect something like get_audio_frame(), produce_audio(), or pull one tick
        frame = None
        if hasattr(producer, "get_silence_frame"):
            frame = producer.get_silence_frame()
        elif hasattr(producer, "SilenceTemplate"):
            frame = producer.SilenceTemplate()
        elif hasattr(producer, "produce_frame"):
            out = producer.produce_frame()
            frame = getattr(out, "audio", None) or out
        assert frame is not None and (hasattr(frame, "data") or hasattr(frame, "nb_samples") or (isinstance(frame, (list, bytes)) and len(frame) > 0)), (
            "PAD must produce at least one silent audio frame buffer (no decoder-only / zero-sample path)"
        )
    finally:
        if hasattr(producer, "stop"):
            producer.stop()


def test_pad_audio_pts_advances_monotonically():
    """Audio PTS must advance monotonically across at least 3 generated frames."""
    pad_producer_class = None
    try:
        from retrovue.runtime import channel_manager
        if hasattr(channel_manager, "PadProducer"):
            pad_producer_class = channel_manager.PadProducer
    except ImportError:
        pass
    if pad_producer_class is None:
        pytest.skip("PadProducer not in Core")
    producer = pad_producer_class(640, 480, 30, 1)
    producer.start()
    try:
        pts_list = []
        for _ in range(3):
            out = getattr(producer, "produce_frame", lambda: getattr(producer, "SilenceTemplate", lambda: None)())()
            if out is None:
                break
            af = getattr(out, "audio", None)
            if af is None and hasattr(out, "pts_us"):
                pts_list.append(out.pts_us)
            elif af is not None:
                pts = getattr(af, "pts_us", None) or getattr(af, "pts", None)
                if pts is not None:
                    pts_list.append(pts)
        assert len(pts_list) >= 3, "PAD must produce at least 3 frames with audio PTS"
        for i in range(1, len(pts_list)):
            assert pts_list[i] > pts_list[i - 1], "Audio PTS must advance monotonically"
    finally:
        if hasattr(producer, "stop"):
            producer.stop()


def test_pad_seam_switch_audio_primed_before_first_video():
    """After simulating seam switch into PAD, audio must still be primed before first video frame."""
    pad_producer_class = None
    try:
        from retrovue.runtime import channel_manager
        if hasattr(channel_manager, "PadProducer"):
            pad_producer_class = channel_manager.PadProducer
    except ImportError:
        pass
    if pad_producer_class is None:
        pytest.skip("PadProducer not in Core")
    producer = pad_producer_class(640, 480, 30, 1)
    producer.start()
    try:
        if hasattr(producer, "activate_seam_pad") or hasattr(producer, "switch_to_pad"):
            fn = getattr(producer, "activate_seam_pad", None) or getattr(producer, "switch_to_pad")
            fn()
        depth = getattr(producer, "audio_depth_ms", None) or getattr(producer, "audio_depth", None)
        assert depth is not None and depth > 0, (
            "After seam switch into PAD, audio depth must be > 0 before first video frame"
        )
    finally:
        if hasattr(producer, "stop"):
            producer.stop()
