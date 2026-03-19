"""Structural contract checks for conditional HLS diagnostic mode."""

import inspect
import textwrap


def test_program_director_has_conditional_hls_diag_mode_controls():
    from retrovue.runtime.program_director import ProgramDirector

    src = textwrap.dedent(inspect.getsource(ProgramDirector))
    assert "_hls_diag_mode_until" in src
    assert "def _hls_diag_trigger" in src
    assert "def _hls_diag_is_active" in src
    assert "def _hls_diag_record" in src


def test_segmenter_emits_audit_diag_event_hook():
    from retrovue.runtime.hls.segmenter import HlsSegmenter

    src = textwrap.dedent(inspect.getsource(HlsSegmenter._finalize_segment))
    assert "INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001" in src
    assert "self._diag(" in src


def test_channel_manager_wires_segmenter_diagnostic_hook():
    from retrovue.runtime.channel_manager import ChannelManager

    src = textwrap.dedent(inspect.getsource(ChannelManager._init_hls_state))
    assert "diagnostic_hook" in src
    assert "hls_diag_event" in src


def test_segment_404_branch_triggers_first_unexpected_404_diag():
    from retrovue.runtime.program_director import ProgramDirector

    src = textwrap.dedent(inspect.getsource(ProgramDirector._register_endpoints))
    assert "unexpected_segment_404_first" in src
    assert "requested_index" in src
    assert "oldest_index" in src
    assert "newest_index" in src
    assert "media_sequence" in src
    assert "playlist_hash" in src
