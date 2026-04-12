"""Contract tests for no stale HLS window after channel stop.

A stopped channel must not retain old segment-window state that can be served
on reconnect attempts.
"""

import inspect
import textwrap


def test_stop_channel_clears_hls_segment_ring_and_resets_segmenter():
    from retrovue.runtime.channel_manager import ChannelManager

    src = textwrap.dedent(inspect.getsource(ChannelManager.stop_channel))

    assert "self._hls_segment_ring.clear()" in src, (
        "INV-HLS-LIFECYCLE-SEGMENT-READY-001 violated: stop_channel() must clear "
        "segment ring to prevent stale manifest windows"
    )
    assert "self._update_hls_segment_counter()" in src, (
        "stop_channel() must persist next segment index before restart"
    )
    assert "self._reset_hls_segmenter_for_restart()" in src, (
        "stop_channel() must reset segmenter parser state for next activation"
    )
