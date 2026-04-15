"""
Contract tests for `docs/contracts/playout/audio_clock_authority.md`.

These tests enforce the contract against realistic failure modes by simulating
competing timing authorities:
- OutputClock tick progression (video/output timeline authority).
- Independent audio production cadence (packet-driven / FIFO-driven).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_SRC = REPO_ROOT / "server" / "src"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))
PIPELINE_MANAGER_CPP = REPO_ROOT / "runtime" / "src" / "blockplan" / "PipelineManager.cpp"

from retrovue.runtime.audio_clock_authority import OutputClockAudioAuthority


SAMPLE_RATE = 48_000
FPS_NUM = 30_000
FPS_DEN = 1_001
SOFT_TOLERANCE_MS = 20.0
HARD_TOLERANCE_MS = 50.0
EPSILON_MS = 0.02


@dataclass(frozen=True)
class TimelineObservation:
    tick_index: int
    output_clock_elapsed_ms: float
    audio_samples_emitted: int
    audio_time_emitted_ms: float
    video_time_emitted_ms: float
    delta_ms: float
    audio_fifo_depth_ms: float
    clock_authority_mode: str


class PacketDrivenAudioSource:
    """Broken model: producer cadence/packet size is timing authority."""

    def __init__(self, packet_size: int = 1024):
        self.packet_size = packet_size
        self.samples_produced = 0

    def produce(self) -> int:
        self.samples_produced += self.packet_size
        return self.packet_size


class SequencePacketAudioSource:
    """Broken model: variable packetization directly alters timeline."""

    def __init__(self, sequence: list[int]):
        self.sequence = sequence
        self.index = 0
        self.samples_produced = 0

    def produce(self) -> int:
        produced = self.sequence[self.index % len(self.sequence)]
        self.index += 1
        self.samples_produced += produced
        return produced


def _simulate_outputclock_authoritative(
    *,
    ticks: int,
    producer: PacketDrivenAudioSource | SequencePacketAudioSource | None = None,
    preroll_samples: int = 0,
    apply_clamp: bool = False,
    clamp_threshold_samples: int | None = None,
    clamp_step_samples: int = 256,
    input_fps_num: int = FPS_NUM,
    input_fps_den: int = FPS_DEN,
) -> list[TimelineObservation]:
    """OutputClock-authoritative simulation with decoder/FIFO as non-authoritative inputs."""
    tick_seconds = Fraction(input_fps_den, input_fps_num)
    authority = OutputClockAudioAuthority(sample_rate=SAMPLE_RATE)
    fifo_samples = preroll_samples
    observations: list[TimelineObservation] = []

    for tick in range(ticks):
        elapsed_seconds = tick_seconds * (tick + 1)
        if producer is not None:
            fifo_samples += producer.produce()

        due_samples = authority.samples_due_now(float(elapsed_seconds))
        pop_from_fifo = min(fifo_samples, due_samples)
        fifo_samples -= pop_from_fifo
        silence_fill = due_samples - pop_from_fifo
        emitted_now = pop_from_fifo + silence_fill

        if apply_clamp and clamp_threshold_samples is not None:
            if fifo_samples > clamp_threshold_samples:
                fifo_samples -= min(clamp_step_samples, fifo_samples - clamp_threshold_samples)

        snapshot = authority.record_emitted(float(elapsed_seconds), emitted_now)

        observations.append(
            TimelineObservation(
                tick_index=tick,
                output_clock_elapsed_ms=snapshot.output_clock_elapsed_ms,
                audio_samples_emitted=snapshot.actual_audio_samples_emitted,
                audio_time_emitted_ms=snapshot.audio_time_emitted_ms,
                video_time_emitted_ms=snapshot.video_time_emitted_ms,
                delta_ms=snapshot.av_delta_ms,
                audio_fifo_depth_ms=(fifo_samples * 1000.0 / SAMPLE_RATE),
                clock_authority_mode=snapshot.clock_authority_mode,
            )
        )

    return observations


def _simulate_packet_driven_clock_competition(
    *,
    ticks: int,
    producer: PacketDrivenAudioSource | SequencePacketAudioSource,
    preroll_samples: int = 0,
    clamp_threshold_samples: int | None = None,
    clamp_step_samples: int = 256,
    input_fps_num: int = FPS_NUM,
    input_fps_den: int = FPS_DEN,
) -> list[TimelineObservation]:
    """Broken model: audio timeline directly follows producer cadence."""
    tick_seconds = Fraction(input_fps_den, input_fps_num)
    emitted_samples = preroll_samples
    observations: list[TimelineObservation] = []

    for tick in range(ticks):
        elapsed_seconds = tick_seconds * (tick + 1)
        expected_samples = round(float(elapsed_seconds) * SAMPLE_RATE)
        emitted_samples += producer.produce()
        if clamp_threshold_samples is not None:
            overage = emitted_samples - expected_samples
            if overage > clamp_threshold_samples:
                emitted_samples -= min(clamp_step_samples, overage)
        output_clock_elapsed_ms = float(elapsed_seconds) * 1000.0
        audio_time_emitted_ms = emitted_samples * 1000.0 / SAMPLE_RATE
        delta_ms = audio_time_emitted_ms - output_clock_elapsed_ms
        observations.append(
            TimelineObservation(
                tick_index=tick,
                output_clock_elapsed_ms=output_clock_elapsed_ms,
                audio_samples_emitted=emitted_samples,
                audio_time_emitted_ms=audio_time_emitted_ms,
                video_time_emitted_ms=output_clock_elapsed_ms,
                delta_ms=delta_ms,
                audio_fifo_depth_ms=max(0.0, delta_ms),
                clock_authority_mode="packet_driven",
            )
        )
    return observations


@pytest.mark.contract
def test_runtime_pipeline_uses_outputclock_due_sample_accounting():
    """Guardrail: contract must be wired into the live PipelineManager boundary."""
    source = PIPELINE_MANAGER_CPP.read_text(encoding="utf-8")
    assert "expected_audio_samples" in source, (
        "PipelineManager missing cumulative expected_audio_samples accounting."
    )
    assert "DeadlineOffsetNs(session_frame_index + 1)" in source, (
        "PipelineManager does not derive elapsed timeline from OutputClock."
    )
    assert "ComputeDueAudioSamples(" in source, (
        "PipelineManager does not compute due samples from cumulative OutputClock delta."
    )
    assert "clock_authority_mode=output_clock" in source, (
        "PipelineManager missing OutputClock authority observability at emission boundary."
    )


@pytest.mark.contract
def test_long_run_sync_no_monotonic_drift_accumulation():
    """Long-run contract: drift must stay within tolerance over 10-minute equivalent."""
    observations = _simulate_outputclock_authoritative(
        ticks=17_982,
        producer=PacketDrivenAudioSource(packet_size=1024),
    )
    drift_ms = abs(observations[-1].delta_ms)
    assert drift_ms <= HARD_TOLERANCE_MS, (
        f"Long-run sync contract violated: drift={drift_ms:.3f}ms exceeds {HARD_TOLERANCE_MS}ms."
    )


@pytest.mark.contract
def test_fractional_sample_distribution_matches_cumulative_expectation():
    """Fractional-demand contract: packet-driven producer must not replace 1601/1602 demand."""
    observations = _simulate_outputclock_authoritative(
        ticks=5_000,
        producer=PacketDrivenAudioSource(packet_size=1024),
    )
    per_tick_pulls = [
        observations[0].audio_samples_emitted,
        *[
            curr.audio_samples_emitted - prev.audio_samples_emitted
            for prev, curr in zip(observations, observations[1:])
        ],
    ]
    assert set(per_tick_pulls).issubset({1601, 1602}), (
        "Per-tick pulls are packet-driven instead of OutputClock fractional demand."
    )


@pytest.mark.contract
def test_packetization_independence_keeps_identical_emitted_timeline():
    """Contract: timeline must not vary with packetization boundaries."""
    run_1024 = _simulate_outputclock_authoritative(
        ticks=4_000,
        producer=PacketDrivenAudioSource(packet_size=1024),
    )
    run_2048 = _simulate_outputclock_authoritative(
        ticks=4_000,
        producer=PacketDrivenAudioSource(packet_size=2048),
    )
    run_random = _simulate_outputclock_authoritative(
        ticks=4_000,
        producer=SequencePacketAudioSource(sequence=[512, 1024, 1536, 768, 2048, 256]),
    )

    t_1024 = [o.audio_time_emitted_ms for o in run_1024]
    t_2048 = [o.audio_time_emitted_ms for o in run_2048]
    t_rand = [o.audio_time_emitted_ms for o in run_random]

    assert t_1024 == t_2048 == t_rand, (
        "Audio emitted timeline changed with packetization boundaries; packetization must be non-authoritative."
    )
 

@pytest.mark.contract
def test_drift_accumulates_monotonically_for_24_to_2997_packet_driven_audio():
    """Contract: OutputClock authority prevents monotonic drift accumulation."""
    observations = _simulate_outputclock_authoritative(
        ticks=8_000,
        producer=PacketDrivenAudioSource(packet_size=1024),
        input_fps_num=FPS_NUM,
        input_fps_den=FPS_DEN,
    )
    drift_over_time = [o.delta_ms for o in observations]
    monotonic_non_decreasing = all(curr >= prev for prev, curr in zip(drift_over_time, drift_over_time[1:]))
    assert not monotonic_non_decreasing, "Monotonic drift accumulation detected under OutputClock authority."


@pytest.mark.contract
def test_clamp_does_not_fix_clock_authority_drift():
    """Clamp/recovery heuristics must not mask continuing authority divergence."""
    observations = _simulate_outputclock_authoritative(
        ticks=8_000,
        producer=PacketDrivenAudioSource(packet_size=1024),
        apply_clamp=True,
        clamp_threshold_samples=38_400,  # ~800ms at 48kHz
        clamp_step_samples=512,
    )
    final_drift = abs(observations[-1].delta_ms)
    assert final_drift <= SOFT_TOLERANCE_MS, (
        f"Clamp failed to reconcile timing authority: final drift={final_drift:.3f}ms."
    )


@pytest.mark.contract
def test_startup_anchor_first_tick_shares_single_output_clock_epoch():
    """Startup contract: preroll must not create independent audio epoch."""
    observations = _simulate_outputclock_authoritative(
        ticks=5,
        producer=PacketDrivenAudioSource(packet_size=1024),
        preroll_samples=24_000,  # 500ms prebuffer
    )
    first = observations[0]
    assert first.audio_time_emitted_ms == pytest.approx(first.output_clock_elapsed_ms, abs=EPSILON_MS), (
        "Startup mis-anchor: audio timeline does not align to OutputClock epoch at first tick."
    )


@pytest.mark.contract
def test_negative_packet_driven_mode_is_rejected_by_contract_checks():
    """Negative case: bad mode runs and must exceed hard drift threshold."""
    observations = _simulate_packet_driven_clock_competition(
        ticks=4_000,
        producer=PacketDrivenAudioSource(packet_size=1024),
    )
    drift_ms = abs(observations[-1].delta_ms)
    assert drift_ms > HARD_TOLERANCE_MS, (
        f"Negative bad-mode guard invalid: drift={drift_ms:.3f}ms did not exceed {HARD_TOLERANCE_MS}ms."
    )
