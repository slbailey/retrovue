"""Structural contract checks for conditional HLS diagnostic mode."""

import inspect
import textwrap


def test_program_director_has_conditional_hls_diag_mode_controls():
    """PD must expose HLS diag controls via delegate methods.

    After 4c refactor, state lives in HlsDiagnosticsState; PD retains the
    four public delegate methods. The internal field _hls_diag_mode_until
    no longer exists in PD — it now lives in HlsDiagnosticsState.mode_until.
    This test checks the delegate surface, which is the real invariant.
    """
    from retrovue.runtime.program_director import ProgramDirector, HlsDiagnosticsState

    pd_src = textwrap.dedent(inspect.getsource(ProgramDirector))
    # PD retains the four delegate methods
    assert "def _hls_diag_trigger" in pd_src
    assert "def _hls_diag_is_active" in pd_src
    assert "def _hls_diag_record" in pd_src
    assert "def _hls_diag_note_reconnect_attempt" in pd_src

    # Expiry is managed in HlsDiagnosticsState.mode_until (single authority)
    state_src = textwrap.dedent(inspect.getsource(HlsDiagnosticsState))
    assert "mode_until" in state_src
    assert "def is_active" in state_src
    assert "def trigger" in state_src


def test_hls_diagnostics_state_auto_expiry_is_sole_mechanism():
    """Auto-expiry via monotonic clock must be the only way diag mode ends.

    No manual reset, clear, or disable path is permitted. Checked by ensuring
    HlsDiagnosticsState has no method that sets mode_until[x] to 0 or deletes it.
    """
    from retrovue.runtime.program_director import HlsDiagnosticsState

    state_src = textwrap.dedent(inspect.getsource(HlsDiagnosticsState))
    # No method may zero or delete mode_until entries (would suppress diagnostics)
    assert "mode_until[" not in state_src.replace("mode_until[channel_id] = max(", "REPLACED")
    # The only write to mode_until[channel_id] must be the max() extend in trigger()
    assert "mode_until[channel_id] = max(prev, now + self.duration_s)" in state_src


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
