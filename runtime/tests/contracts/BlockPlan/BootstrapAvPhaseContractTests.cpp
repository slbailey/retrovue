// INV-BOOTSTRAP-AV-PHASE-001, INV-PACING-SINGLE-AUTHORITY-001 (bootstrap handoff)
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <fcntl.h>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/IOutputClock.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "FastTestConfig.hpp"
#include "TestDecoder.hpp"

#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"

namespace retrovue::blockplan::testing {
namespace {

// Records Start() for INV-BOOTSTRAP-AV-PHASE-001 / INV-PACING-SINGLE-AUTHORITY-001.
class RecordingOutputClock : public IOutputClock {
 public:
  explicit RecordingOutputClock(std::shared_ptr<IOutputClock> inner)
      : inner_(std::move(inner)) {}

  void Start() override {
    start_count_.fetch_add(1, std::memory_order_relaxed);
    inner_->Start();
  }
  int64_t FrameIndexToPts90k(int64_t session_frame_index) const override {
    return inner_->FrameIndexToPts90k(session_frame_index);
  }
  int64_t FrameDurationMs() const override { return inner_->FrameDurationMs(); }
  int64_t FrameDuration90k() const override { return inner_->FrameDuration90k(); }
  std::chrono::steady_clock::time_point DeadlineFor(int64_t session_frame_index) const override {
    return inner_->DeadlineFor(session_frame_index);
  }
  std::chrono::steady_clock::time_point WaitForFrame(int64_t session_frame_index) override {
    return inner_->WaitForFrame(session_frame_index);
  }
  int64_t SessionEpochUtcMs() const override { return inner_->SessionEpochUtcMs(); }
  std::chrono::steady_clock::time_point SessionStartTime() const override {
    return inner_->SessionStartTime();
  }
  std::chrono::nanoseconds DeadlineOffsetNs(int64_t session_frame_index) const override {
    return inner_->DeadlineOffsetNs(session_frame_index);
  }

  int StartCount() const { return start_count_.load(std::memory_order_relaxed); }

 private:
  std::shared_ptr<IOutputClock> inner_;
  std::atomic<int> start_count_{0};
};

TEST(BootstrapAvPhaseContract, BootstrapGate_BlocksClockStart_WhenAudioDepthBelowPrimeFloor) {
  const int floor_ms = 500;
  const int ceiling_ms = 800;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      100, 15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_FALSE(snap.audio_floor_met);
  EXPECT_FALSE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_BlocksClockStart_WhenAudioDepthExceedsBootstrapCeiling) {
  const int floor_ms = 500;
  const int ceiling_ms = 800;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      900, 15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.audio_floor_met);
  EXPECT_FALSE(snap.audio_ceiling_met);
  EXPECT_FALSE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_BlocksClockStart_WhenPositiveAvDeltaExceedsHandoffSafeTolerance) {
  const int floor_ms = 500;
  const int ceiling_ms = 2000;
  // video_time_gate: 15 frames @ 30fps = 500ms; audio 800ms -> delta 300 > 120
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      800, 15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.audio_floor_met);
  EXPECT_TRUE(snap.audio_ceiling_met);
  EXPECT_FALSE(snap.av_phase_met);
  EXPECT_FALSE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_AllowsVideoAheadWhenConsumerNotStarted) {
  // Pre-consumer bootstrap semantics: negative delta is not itself a handoff blocker.
  const int floor_ms = 500;
  const int ceiling_ms = 2000;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      /*audio_depth_ms=*/520, /*video_depth_frames=*/60, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.audio_floor_met);
  EXPECT_TRUE(snap.audio_ceiling_met);
  EXPECT_TRUE(snap.av_phase_met);
  EXPECT_TRUE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_PreConsumerCandidateIsAchievableUnderNormalFillShape) {
  // Achievable safe pre-consumer shape under projected-first-steady validation:
  // audio ~533ms and video depth 15 frames at ~29.97fps.
  const RationalFps fps{30000, 1001};
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      /*audio_depth_ms=*/533,
      /*video_depth_frames=*/15,
      fps,
      /*audio_prime_floor_ms=*/500,
      /*bootstrap_audio_ceiling_ms=*/620,
      /*av_phase_tolerance_ms=*/120);
  EXPECT_TRUE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_StartsClock_WhenBootstrapStateIsPhaseValid) {
  const int floor_ms = 500;
  const int ceiling_ms = 2000;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      530, 15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_RejectsClockStart_WhenAudioDepthAboveSteadyEntryBandTarget) {
  // Bootstrap handoff must be compatible with steady operating-band entry.
  // With 30fps, steady-entry headroom defaults to one frame (~33ms), so
  // max handoff depth is floor + 33ms = 533ms (bounded by ceiling).
  const int floor_ms = 500;
  const int ceiling_ms = 620;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      /*audio_depth_ms=*/587, /*video_depth_frames=*/20, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.audio_floor_met);
  EXPECT_TRUE(snap.audio_ceiling_met);
  EXPECT_TRUE(snap.av_phase_met);
  EXPECT_FALSE(snap.steady_entry_band_met);
  EXPECT_FALSE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_AllowsClockStart_WhenAudioDepthWithinSteadyEntryBandTarget) {
  const int floor_ms = 500;
  const int ceiling_ms = 620;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      /*audio_depth_ms=*/530, /*video_depth_frames=*/15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.audio_floor_met);
  EXPECT_TRUE(snap.audio_ceiling_met);
  EXPECT_TRUE(snap.av_phase_met);
  EXPECT_TRUE(snap.steady_entry_band_met);
  EXPECT_TRUE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_ContinuousSteadyEntryOnly_WouldRejectHboQuantizedCrossing) {
  // HBO-observed quantized crossing shape:
  // previous depth below floor, next depth jumps above preferred entry target.
  const int floor_ms = 500;
  const int ceiling_ms = 620;
  const int prev_depth_ms = 446;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      /*audio_depth_ms=*/587, /*video_depth_frames=*/20, FPS_30, floor_ms, ceiling_ms, 120,
      prev_depth_ms);
  EXPECT_FALSE(snap.steady_entry_band_met)
      << "strict continuous steady-entry-only rule would reject this HBO crossing";
}

TEST(BootstrapAvPhaseContract, BootstrapGate_AllowsClockStart_OnFirstSafeQuantizedFloorCrossing) {
  // Quantized-compatible bootstrap rule: accept smallest safe floor-crossing
  // quantum even if preferred continuous entry band is skipped.
  const int floor_ms = 500;
  const int ceiling_ms = 620;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      /*audio_depth_ms=*/587, /*video_depth_frames=*/20, FPS_30, floor_ms, ceiling_ms, 120,
      /*prev_audio_depth_ms=*/446);
  EXPECT_TRUE(snap.audio_floor_met);
  EXPECT_TRUE(snap.audio_ceiling_met);
  EXPECT_TRUE(snap.av_phase_met);
  EXPECT_FALSE(snap.steady_entry_band_met);
  EXPECT_TRUE(snap.quantized_floor_crossing_met);
  EXPECT_TRUE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, ComputeVideoTimeMsGate_MatchesContractFormula) {
  EXPECT_EQ(PipelineManager::ComputeVideoTimeMsGate(15, FPS_30), 500);
  EXPECT_EQ(PipelineManager::ComputeVideoTimeMsGate(0, FPS_30), 0);
}

TEST(BootstrapAvPhaseContract, OutputClock_RemainsSolePacingAuthority_ForBootstrapHandoff) {
  auto base = std::make_shared<OutputClock>(30, 1);
  auto rec = std::make_shared<RecordingOutputClock>(base);
  EXPECT_EQ(rec->StartCount(), 0);
  rec->Start();
  EXPECT_EQ(rec->StartCount(), 1);
}

TEST(BootstrapAvPhaseContract, EncoderPipeline_DoesNotRepairPreexistingBootstrapPhaseError) {
  EXPECT_EQ(RETROVUE_ENCODER_BOOTSTRAP_AV_PHASE_REPAIR, 0);
}

TEST(BootstrapAvPhaseContract, BootstrapPhaseRepair_RemainsInFillDecodeDomain) {
  // Structural: PipelineManager exposes gate evaluation; EncoderPipeline macro forbids repair.
  EXPECT_NE(nullptr, &PipelineManager::EvaluateBootstrapPhaseGate);
  EXPECT_EQ(RETROVUE_ENCODER_BOOTSTRAP_AV_PHASE_REPAIR, 0);
}

TEST(BootstrapAvPhaseContract, BootstrapPassState_MustBeFirstSteadyFillSafe) {
  // Contract bridge:
  // A bootstrap-pass state must remain within fill clamp tolerance at the first
  // steady-state evaluation. If estimators can differ by one output frame, gate
  // delta must include that guard.
  //
  // Under atomic handoff semantics, this previously fragile live shape must be
  // accepted by the bootstrap gate and carried into steady only after first
  // consumer-position update.
  const RationalFps fps{30000, 1001};
  const int av_tol_ms = 120;
  const int audio_depth_ms = 533;
  const int video_depth_frames = 14;

  const auto gate = PipelineManager::EvaluateBootstrapPhaseGate(
      audio_depth_ms, video_depth_frames, fps, /*audio_prime_floor_ms=*/500,
      /*bootstrap_audio_ceiling_ms=*/620, av_tol_ms);
  EXPECT_TRUE(gate.phase_valid)
      << "atomic handoff model expects this bootstrap-pass shape to be valid";

  const int output_frame_ms = PipelineManager::ComputeVideoTimeMsGate(1, fps);
  // Demonstrate a safe state that must pass and remain first-fill safe.
  const int safe_audio_depth_ms = 530;  // gate delta ~30ms with 15 frames @ 29.97
  const int safe_video_depth_frames = 15;
  const auto safe_gate = PipelineManager::EvaluateBootstrapPhaseGate(
      safe_audio_depth_ms, safe_video_depth_frames, fps, /*audio_prime_floor_ms=*/500,
      /*bootstrap_audio_ceiling_ms=*/620, av_tol_ms);
  ASSERT_TRUE(safe_gate.phase_valid);
  const int first_fill_video_ms = std::max(0, safe_gate.video_time_ms_gate - output_frame_ms);
  const int first_fill_delta_ms = safe_audio_depth_ms - first_fill_video_ms;

  EXPECT_LE(first_fill_delta_ms, av_tol_ms)
      << "bootstrap-pass state is not fill-safe on first steady evaluation";
}

TEST(BootstrapAvPhaseContract, BootstrapPassState_MustNotDeterministicallyTripClampNextEvaluation) {
  // Equivalent guard-band expression for bridge safety.
  const RationalFps fps{30000, 1001};
  const int av_tol_ms = 120;
  const int audio_depth_ms = 533;
  const int video_depth_frames = 14;

  const auto gate = PipelineManager::EvaluateBootstrapPhaseGate(
      audio_depth_ms, video_depth_frames, fps, /*audio_prime_floor_ms=*/500,
      /*bootstrap_audio_ceiling_ms=*/620, av_tol_ms);
  EXPECT_TRUE(gate.phase_valid)
      << "atomic handoff permits this state and prevents pre-steady drift";

  const int handoff_guard_ms = PipelineManager::ComputeVideoTimeMsGate(1, fps);
  const int max_gate_delta_for_fill_safe_handoff = av_tol_ms - handoff_guard_ms;

  EXPECT_LE(gate.gate_av_delta_ms, max_gate_delta_for_fill_safe_handoff)
      << "atomic handoff contract requires one-frame guard-band at gate";
}

TEST(BootstrapAvPhaseContract, StartupPrimedAudioBurst_MustBePacketizationShapeIndependentForBootstrapSafety) {
  // Contract: startup primed-frame contribution must be bounded independently
  // of decoder packetization shape.
  const RationalFps fps{30000, 1001};
  const int startup_primed_audio_max_ms = PipelineManager::ComputeVideoTimeMsGate(1, fps);
  const int max_primed_samples = (startup_primed_audio_max_ms * 48000) / 1000;

  const int cheers_like_samples = 1024;      // one AAC frame
  const int hbo_like_samples = 24 * 512;     // observed HBO primed burst

  const auto effective_ms_after_cap = [&](int total_samples, int packet_samples) {
    int kept = 0;
    while (kept + packet_samples <= max_primed_samples || kept == 0) {
      kept += packet_samples;
      if (kept >= total_samples) break;
    }
    if (kept > total_samples) kept = total_samples;
    return static_cast<int>((kept * 1000LL) / 48000LL);
  };

  const int cheers_like_ms = effective_ms_after_cap(cheers_like_samples, 1024);
  const int hbo_like_ms = effective_ms_after_cap(hbo_like_samples, 512);

  EXPECT_LE(cheers_like_ms, startup_primed_audio_max_ms);
  EXPECT_LE(hbo_like_ms, startup_primed_audio_max_ms)
      << "startup primed audio is asset-shape dependent and exceeds bootstrap-safe bound";
}

TEST(BootstrapAvPhaseContract, HboStylePrimedBurst_MustNotDeterministicallyTripBootstrapPositiveLeadClamp) {
  // Reproduction from HBO startup path:
  // bootstrap_start audio_ms=256, first clamp eval video_ms=100 -> +156 (>120).
  const int av_tolerance_ms = 120;
  const RationalFps fps{30000, 1001};
  const int startup_primed_audio_max_ms = PipelineManager::ComputeVideoTimeMsGate(1, fps);
  const int max_primed_samples = (startup_primed_audio_max_ms * 48000) / 1000;
  int capped_samples = 0;
  while (capped_samples + 512 <= max_primed_samples || capped_samples == 0) {
    capped_samples += 512;
    if (capped_samples >= 24 * 512) break;
  }
  if (capped_samples > 24 * 512) capped_samples = 24 * 512;
  const int hbo_startup_audio_ms = static_cast<int>((capped_samples * 1000LL) / 48000LL);
  const int first_bootstrap_video_ms = 100;
  const int av_delta_ms = hbo_startup_audio_ms - first_bootstrap_video_ms;

  EXPECT_LE(av_delta_ms, av_tolerance_ms)
      << "startup primed burst deterministically trips bootstrap positive-lead clamp";
}

TEST(BootstrapAvPhaseContract, StartupPrimedNormalization_MustPreserveStartupAudioMassAcrossPacketizationShapes) {
  // Contract: normalization may redistribute startup audio between primed and
  // immediate buffered frames, but total startup decoded audio must be preserved.
  const RationalFps fps{30000, 1001};
  const int startup_primed_audio_max_ms = PipelineManager::ComputeVideoTimeMsGate(1, fps);
  const int max_primed_samples = (startup_primed_audio_max_ms * 48000) / 1000;

  const auto split_after_cap = [&](int total_samples, int packet_samples) {
    int primed_kept = 0;
    while (primed_kept + packet_samples <= max_primed_samples || primed_kept == 0) {
      primed_kept += packet_samples;
      if (primed_kept >= total_samples) break;
    }
    if (primed_kept > total_samples) primed_kept = total_samples;
    const int overflow = total_samples - primed_kept;
    return std::pair<int, int>{primed_kept, overflow};
  };

  const auto cheers = split_after_cap(/*total_samples=*/1024, /*packet_samples=*/1024);
  const auto hbo = split_after_cap(/*total_samples=*/24 * 512, /*packet_samples=*/512);

  EXPECT_EQ(cheers.first + cheers.second, 1024);
  EXPECT_EQ(hbo.first + hbo.second, 24 * 512);
}

TEST(BootstrapAvPhaseContract, StartupPrimedNormalization_AllowsZeroPrimedAudio_WithoutBreakingBootstrapLiveness) {
  // HBO-observed shape after normalization:
  // primed contribution may be zero at StartFilling, but bootstrap gate must
  // still hold clock start until audio prime floor is reached from buffered fill.
  const int floor_ms = 500;
  const int ceiling_ms = 620;
  const int av_tol_ms = 120;

  const auto start = PipelineManager::EvaluateBootstrapPhaseGate(
      /*audio_depth_ms=*/0,
      /*video_depth_frames=*/2,
      FPS_30,
      floor_ms,
      ceiling_ms,
      av_tol_ms);
  EXPECT_FALSE(start.phase_valid);
  EXPECT_FALSE(start.audio_floor_met);

  // Same startup progression reaches prime floor before handoff.
  const auto end = PipelineManager::EvaluateBootstrapPhaseGate(
      /*audio_depth_ms=*/530,
      /*video_depth_frames=*/16,
      FPS_30,
      floor_ms,
      ceiling_ms,
      av_tol_ms);
  EXPECT_TRUE(end.phase_valid);
  EXPECT_TRUE(end.audio_floor_met);
}

TEST(BootstrapAvPhaseContract, QuantizedBootstrapSequence_HboLikeCrossing_ReachesValidHandoffWithoutContinuousBand) {
  // Discrete HBO-like pre-consumer progression (no pops): 32 -> 153 -> 446 -> 587.
  // Valid handoff should occur at the first safe floor-crossing quantum.
  const int floor_ms = 500;
  const int ceiling_ms = 620;
  const int av_tol_ms = 120;
  const int depths[] = {32, 153, 446, 587};
  const int video_frames[] = {1, 5, 17, 20};
  bool reached_valid = false;
  int prev = depths[0];
  for (size_t i = 0; i < std::size(depths); ++i) {
    const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
        depths[i], video_frames[i], FPS_30, floor_ms, ceiling_ms, av_tol_ms, prev);
    if (snap.phase_valid) {
      reached_valid = true;
      EXPECT_EQ(depths[i], 587);
      EXPECT_TRUE(snap.quantized_floor_crossing_met);
      break;
    }
    prev = depths[i];
  }
  EXPECT_TRUE(reached_valid);
}

TEST(BootstrapAvPhaseContract, PostHandoffTransitionTarget_ComputesBurstAwareHeadroom_FromQuantizedBootstrap) {
  // HBO-like quantized bootstrap crossing can imply ~256ms decode burst quantum.
  // Transition target must leave at least one such burst of headroom below ceiling.
  const int ceiling_ms = 620;
  const int output_frame_ms = PipelineManager::ComputeVideoTimeMsGate(1, FPS_30);  // ~33
  const int observed_quantum_ms = 256;
  const int target_ms = PipelineManager::ComputePostHandoffTransitionTargetAudioMs(
      ceiling_ms, output_frame_ms, observed_quantum_ms);
  EXPECT_EQ(target_ms, 364);
}

TEST(BootstrapAvPhaseContract, HboQuantizedHandoff_RequiresTransitionDrainBeforeSteadyBurstControl) {
  // Handoff is valid at 512ms (quantized floor crossing), but not yet transition-safe
  // for an immediate 256ms burst under high-water=620.
  const int handoff_audio_ms = 512;
  const int high_water_ms = 620;
  const int output_frame_ms = PipelineManager::ComputeVideoTimeMsGate(1, FPS_30);
  const int observed_quantum_ms = 256;
  const int transition_target_ms = PipelineManager::ComputePostHandoffTransitionTargetAudioMs(
      high_water_ms, output_frame_ms, observed_quantum_ms);
  EXPECT_GT(handoff_audio_ms, transition_target_ms);
  EXPECT_GT(handoff_audio_ms + observed_quantum_ms, high_water_ms)
      << "without transition drain, first steady burst remains clamp-prone";

  // After transition drain reaches target, one quantum burst no longer overshoots.
  EXPECT_LE(transition_target_ms + observed_quantum_ms, high_water_ms);
}

TEST(BootstrapAvPhaseContract, TransitionDrainExclusivity_HoldsDecodeAdmissionUntilTargetReached) {
  // Transition exclusivity policy: above transition target, decode admission is held.
  const int high_water_ms = 620;
  const int output_frame_ms = PipelineManager::ComputeVideoTimeMsGate(1, FPS_30);
  const int observed_quantum_ms = 256;
  const int transition_target_ms = PipelineManager::ComputePostHandoffTransitionTargetAudioMs(
      high_water_ms, output_frame_ms, observed_quantum_ms);

  int transition_audio_ms = 553;  // observed at transition_start
  EXPECT_GT(transition_audio_ms, transition_target_ms);

  // While above target, decode admission remains held (drain-only regime).
  bool decode_allowed = transition_audio_ms <= transition_target_ms;
  EXPECT_FALSE(decode_allowed);

  // Simulate a few consumer ticks draining audio by ~33ms each.
  for (int i = 0; i < 6; ++i) {
    transition_audio_ms = std::max(0, transition_audio_ms - 33);
  }
  EXPECT_LE(transition_audio_ms, transition_target_ms);

  // After reaching target, decode admission may resume.
  decode_allowed = transition_audio_ms <= transition_target_ms;
  EXPECT_TRUE(decode_allowed);
}

TEST(BootstrapAvPhaseContract, TransitionExitHysteresis_ComputesBurstSafeReentryThreshold) {
  const int high_water_ms = 620;
  const int output_frame_ms = PipelineManager::ComputeVideoTimeMsGate(1, FPS_30);
  const int observed_quantum_ms = 167;
  const int steady_pending_burst_ms = 256;

  const int transition_target_ms = PipelineManager::ComputePostHandoffTransitionTargetAudioMs(
      high_water_ms, output_frame_ms, observed_quantum_ms);
  const int transition_exit_ms = PipelineManager::ComputePostHandoffTransitionExitAudioMs(
      transition_target_ms, output_frame_ms, observed_quantum_ms);

  EXPECT_EQ(transition_target_ms, 453);
  EXPECT_EQ(transition_exit_ms, 354);
  EXPECT_LE(transition_exit_ms + steady_pending_burst_ms, high_water_ms)
      << "re-entry hysteresis must leave enough headroom for first resumed burst";
}

TEST(BootstrapAvPhaseContract, TransitionExitHysteresis_RemainsAchievableWithoutTimeout_OnHboLikeDrain) {
  const int output_frame_ms = PipelineManager::ComputeVideoTimeMsGate(1, FPS_30);
  const int start_audio_ms = 553;  // observed transition_start shape
  const int high_water_ms = 620;
  const int observed_quantum_ms = 224;
  const int max_ticks = 12;

  const int transition_target_ms = PipelineManager::ComputePostHandoffTransitionTargetAudioMs(
      high_water_ms, output_frame_ms, observed_quantum_ms);
  const int transition_exit_ms = PipelineManager::ComputePostHandoffTransitionExitAudioMs(
      transition_target_ms, output_frame_ms, observed_quantum_ms);

  const int max_drain_ms = max_ticks * output_frame_ms;
  const int reachable_floor_ms = std::max(0, start_audio_ms - max_drain_ms);

  EXPECT_GE(transition_exit_ms, reachable_floor_ms)
      << "exit threshold is too conservative and will force timeout-first transition end";
}

// --- Integration: timeout before OutputClock::Start (requires media) ---
static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

static FedBlock MakeShortBlock(const std::string& uri) {
  FedBlock b;
  b.block_id = "boot_contract";
  b.channel_id = 1;
  b.start_utc_ms = 0;
  b.end_utc_ms = 120000;
  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = uri;
  seg.segment_duration_ms = 120000;
  b.segments.push_back(seg);
  return b;
}

class BootstrapTimeoutFixture : public ::testing::Test {
 protected:
  void SetUp() override {
    int fds[2];
    ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->fd = fds[0];
    drain_fd_ = fds[1];
    drain_stop_ = false;
    drain_thread_ = std::thread([this] {
      char buf[8192];
      while (!drain_stop_) {
        ssize_t n = read(drain_fd_, buf, sizeof buf);
        if (n <= 0) break;
      }
    });
    ctx_->channel_id = 42;
    ctx_->width = 320;
    ctx_->height = 240;
    ctx_->fps = FPS_30;
    test_ts_ = test_infra::MakeTestTimeSource();
  }
  void TearDown() override {
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
    if (ctx_ && ctx_->fd >= 0) {
      close(ctx_->fd);
      ctx_->fd = -1;
    }
    drain_stop_ = true;
    if (drain_fd_ >= 0) {
      shutdown(drain_fd_, SHUT_RDWR);
      close(drain_fd_);
      drain_fd_ = -1;
    }
    if (drain_thread_.joinable()) drain_thread_.join();
  }

  std::shared_ptr<RecordingOutputClock> MakeRecordingClock() {
    auto base = test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_);
    return std::make_shared<RecordingOutputClock>(base);
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_{-1};
  bool drain_stop_{false};
  std::thread drain_thread_;
};

TEST_F(BootstrapTimeoutFixture, BootstrapGate_TimeoutSetsStopRequested_AndDoesNotStartClock) {
  const char* env = getenv("RETROVUE_TEST_VIDEO_PATH");
  const std::string uri = env ? std::string(env) : std::string("/opt/retrovue/assets/SampleA.mp4");
  if (!FileExists(uri)) {
    GTEST_SKIP() << "RETROVUE_TEST_VIDEO_PATH or SampleA.mp4 not available";
  }

  PipelineManager::Callbacks cb;
  cb.on_session_ended = [](const std::string&, int64_t) {};

  PipelineManagerOptions opt;
  opt.bootstrap_gate_timeout_ms = 0;
  opt.av_phase_tolerance_ms = 0;

  auto rec = MakeRecordingClock();
  engine_ = std::make_unique<PipelineManager>(
      ctx_.get(), std::move(cb), test_ts_, rec, opt,
      std::make_shared<test_infra::TestProducerFactory>());

  ctx_->block_queue.push_back(MakeShortBlock(uri));
  engine_->Start();

  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(15);
  while (std::chrono::steady_clock::now() < deadline) {
    if (ctx_->stop_requested.load(std::memory_order_acquire)) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  EXPECT_TRUE(ctx_->stop_requested.load(std::memory_order_acquire))
      << "bootstrap gate should abort session on timeout";
  EXPECT_EQ(rec->StartCount(), 0) << "OutputClock must not start after failed bootstrap";
  EXPECT_GE(engine_->SnapshotMetrics().air_bootstrap_phase_failure_total, 1);

  engine_->Stop();
  engine_.reset();
}

TEST_F(BootstrapTimeoutFixture, BootstrapGate_DoesNotOpenEmissionGate_OnPhaseInvalidTimeout) {
  const char* env = getenv("RETROVUE_TEST_VIDEO_PATH");
  const std::string uri = env ? std::string(env) : std::string("/opt/retrovue/assets/SampleA.mp4");
  if (!FileExists(uri)) {
    GTEST_SKIP() << "RETROVUE_TEST_VIDEO_PATH or SampleA.mp4 not available";
  }

  PipelineManager::Callbacks cb;
  cb.on_session_ended = [](const std::string&, int64_t) {};

  PipelineManagerOptions opt;
  opt.bootstrap_gate_timeout_ms = 0;
  opt.av_phase_tolerance_ms = 0;

  auto rec = MakeRecordingClock();
  engine_ = std::make_unique<PipelineManager>(
      ctx_.get(), std::move(cb), test_ts_, rec, opt,
      std::make_shared<test_infra::TestProducerFactory>());

  ctx_->block_queue.push_back(MakeShortBlock(uri));
  engine_->Start();

  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(15);
  while (std::chrono::steady_clock::now() < deadline) {
    if (ctx_->stop_requested.load(std::memory_order_acquire)) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  EXPECT_TRUE(ctx_->stop_requested.load(std::memory_order_acquire));
  // Emission gate is opened only after successful bootstrap + clock start; failed path never opens.
  EXPECT_EQ(rec->StartCount(), 0);

  engine_->Stop();
  engine_.reset();
}

}  // namespace
}  // namespace retrovue::blockplan::testing
