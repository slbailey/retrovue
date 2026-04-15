"""OutputClock-authoritative audio timing model.

This module defines cumulative sample accounting for playout audio emission:
`expected_audio_samples = round(output_clock_elapsed_seconds * sample_rate)`.
Emission authority is derived from OutputClock elapsed time only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioTimingSnapshot:
    """Per-tick accounting snapshot for observability and contracts."""

    output_clock_elapsed_ms: float
    expected_audio_samples: int
    actual_audio_samples_emitted: int
    audio_sample_error: int
    audio_time_emitted_ms: float
    video_time_emitted_ms: float
    av_delta_ms: float
    clock_authority_mode: str


class OutputClockAudioAuthority:
    """Cumulative audio emission authority derived from OutputClock elapsed time."""

    def __init__(self, sample_rate: int = 48_000) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self.sample_rate = sample_rate
        self.actual_audio_samples_emitted = 0
        self.clock_authority_mode = "output_clock"

    def expected_audio_samples(self, output_clock_elapsed_seconds: float) -> int:
        """Return cumulative expected audio samples for elapsed OutputClock time."""
        if output_clock_elapsed_seconds < 0.0:
            raise ValueError("output_clock_elapsed_seconds must be non-negative")
        return round(output_clock_elapsed_seconds * self.sample_rate)

    def samples_due_now(self, output_clock_elapsed_seconds: float) -> int:
        """Return authoritative samples due at the current tick."""
        expected = self.expected_audio_samples(output_clock_elapsed_seconds)
        due = expected - self.actual_audio_samples_emitted
        return max(0, due)

    def record_emitted(
        self,
        output_clock_elapsed_seconds: float,
        emitted_now_samples: int,
    ) -> AudioTimingSnapshot:
        """Advance accounting after encoding for a tick."""
        if emitted_now_samples < 0:
            raise ValueError("emitted_now_samples must be non-negative")

        self.actual_audio_samples_emitted += emitted_now_samples
        expected = self.expected_audio_samples(output_clock_elapsed_seconds)
        error = expected - self.actual_audio_samples_emitted
        output_clock_elapsed_ms = output_clock_elapsed_seconds * 1000.0
        audio_time_emitted_ms = self.actual_audio_samples_emitted * 1000.0 / self.sample_rate
        video_time_emitted_ms = output_clock_elapsed_ms

        return AudioTimingSnapshot(
            output_clock_elapsed_ms=output_clock_elapsed_ms,
            expected_audio_samples=expected,
            actual_audio_samples_emitted=self.actual_audio_samples_emitted,
            audio_sample_error=error,
            audio_time_emitted_ms=audio_time_emitted_ms,
            video_time_emitted_ms=video_time_emitted_ms,
            av_delta_ms=audio_time_emitted_ms - video_time_emitted_ms,
            clock_authority_mode=self.clock_authority_mode,
        )
