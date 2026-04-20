// AIR vNext — AirSession implementation.
//
// Orchestrates the three-phase startup (AttachOutput → AssignContent →
// OpenAir). Each phase is distinct and guarded by preconditions on the
// previous phases having succeeded. Owned member groups are explicitly
// separated (sink group / content group / on-air group) so a future
// device-centric retune can swap content without touching the sink.
//
// Threading:
//   - AttachOutput/AssignContent/OpenAir/Close run on the calling thread
//     (today the gRPC handler thread). They are non-blocking — no encode
//     work happens inline.
//   - EncodeLoop runs on encode_thread_, started by OpenAir() and joined
//     by Close().

#include "air_session.hpp"

#include <unistd.h>

#include <chrono>
#include <iostream>
#include <utility>

#include "bootstrap_content_gate.hpp"
#include "egress_pacer.hpp"
#include "file_source_producer.hpp"
#include "mpeg_ts_encoder.hpp"
#include "socket_emitter.hpp"
#include "standard_normalizer.hpp"

namespace retrovue::air {

namespace {

int64_t MonoUs() {
  const auto now = std::chrono::steady_clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::microseconds>(now).count();
}

// Default lifecycle observer: structured stderr line, key=value.
// Parseable by grep/awk. Used by soak tooling and ad-hoc ops.
void DefaultLifecycleObserver(const StateTransitionEvent& e) {
  std::cerr << "[air.lifecycle]"
            << " mono_us=" << e.mono_us
            << " from=" << ToString(e.from)
            << " to=" << ToString(e.to)
            << " reason=" << (e.reason_class.empty() ? "-" : e.reason_class)
            << std::endl;
}

}  // namespace

const char* ToString(SessionState s) {
  switch (s) {
    case SessionState::Warming:     return "Warming";
    case SessionState::Ready:       return "Ready";
    case SessionState::OnAir:       return "OnAir";
    case SessionState::Stopping:    return "Stopping";
    case SessionState::FailedStart: return "FailedStart";
  }
  return "Unknown";
}

AirSession::AirSession() : lifecycle_observer_(&DefaultLifecycleObserver) {}

AirSession::~AirSession() { Close(); }

void AirSession::SetLifecycleObserver(LifecycleObserver obs) {
  lifecycle_observer_ = obs ? std::move(obs) : LifecycleObserver(&DefaultLifecycleObserver);
}

void AirSession::TransitionTo(SessionState to, const char* reason_class) {
  const SessionState from = state_.exchange(to);
  if (from == to) return;  // no-op
  if (lifecycle_observer_) {
    StateTransitionEvent e{
        .mono_us = MonoUs(),
        .from = from,
        .to = to,
        .reason_class = reason_class ? reason_class : "",
    };
    lifecycle_observer_(e);
  }
}

bool AirSession::AttachOutput(int fd) {
  // Preconditions: no output attached, fd is valid.
  if (emitter_ != nullptr || owned_fd_ >= 0) return false;
  if (fd < 0) return false;

  owned_fd_ = fd;
  emitter_ = std::make_unique<SocketEmitter>(fd);
  return true;
}

bool AirSession::AssignContent(const std::string& input_path,
                               const ChannelCanonical& canonical) {
  // Preconditions: output attached, content not yet assigned.
  if (emitter_ == nullptr) return false;
  if (source_ != nullptr) return false;
  if (!canonical.IsValid()) return false;

  canonical_ = canonical;

  // Legacy mode: synthesize an active_block_ with a generated block_id so
  // downstream queue accounting (QueueDepth, GetSessionStatus) treats this
  // session uniformly with queue-based sessions.
  Block legacy_block;
  legacy_block.block_id = "legacy:" + input_path;
  legacy_block.asset_uri = input_path;
  legacy_block.canonical = canonical;
  {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    active_block_ = std::move(legacy_block);
  }

  // Channel audio block: ~ one video-frame-period of samples at the
  // channel audio rate. For 30000/1001 video at 48kHz audio, this is
  // ~1601 samples. Hardcoded for now (matches existing tests).
  audio_samples_per_block_ = 1601;

  // Build FileSourceProducer.
  auto source = std::make_unique<FileSourceProducer>(
      FileSourceProducer::Config{.file_path = input_path});
  if (!source->Prepare()) return false;
  if (!source->Activate()) return false;

  // Build StandardNormalizer, matching the pattern from encoder_smoke_test.
  auto normalizer = std::make_unique<StandardNormalizer>(
      canonical_, source->VideoFrameRate(), source->VideoWidth(),
      source->VideoHeight(), source->AudioSampleRate(), source.get(),
      ChannelOrigin{.source_pts_anchor_us = 0,
                    .channel_pts_anchor_us = 0},
      audio_samples_per_block_);

  // Build + open MpegTsEncoder with a callback that writes to emitter_.
  auto encoder = std::make_unique<MpegTsEncoder>();
  MpegTsEncoderConfig cfg{
      .video_width = canonical_.video.width,
      .video_height = canonical_.video.height,
      .video_fps_num = static_cast<int>(canonical_.video.frame_rate.num),
      .video_fps_den = static_cast<int>(canonical_.video.frame_rate.den),
      .video_bitrate_bps = 4'000'000,
      .audio_sample_rate = canonical_.audio.sample_rate,
      .audio_channels = canonical_.audio.channels,
      .audio_bitrate_bps = 192'000,
  };
  SocketEmitter* emitter_ptr = emitter_.get();
  if (!encoder->Open(cfg, [emitter_ptr](const uint8_t* buf, int n) {
        return emitter_ptr->Write(buf, n);
      })) {
    return false;
  }

  // Commit. Everything constructed successfully; install in member state.
  source_ = std::move(source);
  normalizer_ = std::move(normalizer);
  encoder_ = std::move(encoder);
  return true;
}

bool AirSession::SeedActiveBlock(const Block& block) {
  // Phase B: wrap AssignContent with block-centric entry. Extract asset_uri
  // and canonical from the Block; call the existing AssignContent to build
  // source/normalizer/encoder; then record the full block in active_block_
  // (overwriting the synthesized legacy_block AssignContent would install).
  if (block.asset_uri.empty()) return false;
  if (!block.canonical.IsValid()) return false;

  if (!AssignContent(block.asset_uri, block.canonical)) return false;

  // Replace the synthesized legacy_block with the real supplied Block.
  std::lock_guard<std::mutex> lk(queue_mutex_);
  active_block_ = block;
  return true;
}

bool AirSession::AddQueuedBlock(const Block& block,
                                const std::string& /*predecessor_id*/,
                                std::string* reason_out) {
  // Phase B scope: simple append. No predecessor validation yet (that's
  // Phase C when pull/supply ordering matters). No mutation-state checks
  // (revisions/retirements are separate RPCs).
  std::lock_guard<std::mutex> lk(queue_mutex_);
  if (!active_block_.has_value() && source_ == nullptr) {
    if (reason_out) *reason_out = "NO_SESSION";
    return false;
  }
  queued_blocks_.push_back(block);
  return true;
}

int32_t AirSession::QueueDepth() const {
  std::lock_guard<std::mutex> lk(queue_mutex_);
  int32_t depth = 0;
  if (active_block_.has_value()) ++depth;
  depth += static_cast<int32_t>(queued_blocks_.size());
  return depth;
}

bool AirSession::OpenAir() {
  // Preconditions: output + content attached, not already on air.
  if (emitter_ == nullptr) return false;
  if (source_ == nullptr || normalizer_ == nullptr || encoder_ == nullptr) {
    return false;
  }
  if (encode_thread_.joinable()) return false;

  pacer_ = std::make_unique<EgressPacer>();
  gate_ = std::make_unique<BootstrapContentGate>();
  stopping_.store(false);
  state_.store(SessionState::Warming);
  warming_duration_us_.store(-1);
  bootstrap_total_duration_us_.store(-1);
  warmup_video_.clear();
  warmup_audio_.clear();
  encode_thread_ = std::thread([this]() { EncodeLoop(); });
  return true;
}

void AirSession::FailStart(const char* reason_class) {
  {
    std::lock_guard<std::mutex> lock(failed_start_mutex_);
    failed_start_reason_ = reason_class;
  }
  TransitionTo(SessionState::FailedStart, reason_class);
}

void AirSession::EncodeLoop() {
  const int64_t warming_entered_mono_us = MonoUs();
  TransitionTo(SessionState::Warming, "openair");

  // ---- Phase 1: WARMING — pre-buffer frames; byte path HELD CLOSED. ----
  // Pull from normalizer into the warmup deques. Evaluate the gate every
  // tick. Exit this phase when gate fires (→ Ready) or source EOFs before
  // readiness (→ FailedStart).
  while (!stopping_.load() && !gate_->HasFired()) {
    auto vf = normalizer_->PullVideo();
    if (!vf.has_value()) {
      // Source EOF before gate could fire. The content is too short to
      // satisfy the warmup floor — treat as FailedStart per design doc.
      FailStart("SOURCE_EOF_DURING_WARMUP");
      return;
    }
    warmup_video_.push_back(std::move(*vf));
    auto ab = normalizer_->PullAudio();
    if (ab.has_value()) warmup_audio_.push_back(std::move(*ab));

    BootstrapContentGate::ReadinessSnapshot snapshot{
        .video_buffer_depth = warmup_video_.size(),
        .audio_buffer_depth = warmup_audio_.size(),
        // TODO: when FileSourceProducer exposes health signal, wire here.
        .decoder_healthy = true,
    };
    if (gate_->Evaluate(snapshot) == BootstrapContentGate::Verdict::Ready) {
      warming_duration_us_.store(MonoUs() - warming_entered_mono_us);
      TransitionTo(SessionState::Ready, "gate_fired");
      break;
    }
  }

  if (stopping_.load()) return;                              // external Close()
  if (state_.load() == SessionState::FailedStart) return;    // bootstrap fail

  // ---- Phase 2: READY → ON_AIR — transient, one-step transition. ----
  // Per design guardrail, Ready is not a long-lived mode. Record the
  // bootstrap total and move to OnAir immediately.
  const int64_t on_air_entered_mono_us = MonoUs();
  bootstrap_total_duration_us_.store(on_air_entered_mono_us - warming_entered_mono_us);
  TransitionTo(SessionState::OnAir, "first_emit");

  // ---- Phase 3: ON_AIR — drain warmup buffer, then continue pulling. ----
  // Frames are fed into the encoder for the first time here. First byte on
  // wire is content, per lifecycle memory.
  while (!stopping_.load()) {
    std::optional<VideoFrame> vf_opt;
    if (!warmup_video_.empty()) {
      vf_opt = std::move(warmup_video_.front());
      warmup_video_.pop_front();
    } else {
      vf_opt = normalizer_->PullVideo();
    }
    if (!vf_opt.has_value()) break;  // natural EOF

    pacer_->WaitFor(vf_opt->pts_us_relative);
    if (!encoder_->EncodeVideo(*vf_opt)) break;
    frames_encoded_.fetch_add(1);

    std::optional<AudioBlock> ab_opt;
    if (!warmup_audio_.empty()) {
      ab_opt = std::move(warmup_audio_.front());
      warmup_audio_.pop_front();
    } else {
      ab_opt = normalizer_->PullAudio();
    }
    if (ab_opt.has_value()) encoder_->EncodeAudio(*ab_opt);
  }

  // Drain a few extra audio blocks so the interleaver has enough audio
  // to cover the video span on final flush.
  for (int extra = 0; extra < 10; ++extra) {
    auto ab = normalizer_->PullAudio();
    if (!ab.has_value()) break;
    encoder_->EncodeAudio(*ab);
  }
  if (encoder_) encoder_->Flush();
}

void AirSession::Close() {
  // Transition to Stopping unless we're already in a terminal failure
  // state (FailedStart must not be overwritten). Stopping is terminal.
  if (state_.load() != SessionState::FailedStart) {
    TransitionTo(SessionState::Stopping, "close");
  }
  stopping_.store(true);
  if (encode_thread_.joinable()) {
    encode_thread_.join();
  }
  if (encoder_) {
    encoder_->Close();
  }
  if (owned_fd_ >= 0) {
    ::close(owned_fd_);
    owned_fd_ = -1;
  }
  // Retire source after the encode thread has stopped pulling from it.
  if (source_) {
    source_->Retire();
  }
  encoder_.reset();
  pacer_.reset();
  gate_.reset();
  normalizer_.reset();
  source_.reset();
  emitter_.reset();
  warmup_video_.clear();
  warmup_audio_.clear();
  frames_encoded_.store(0);
  stopping_.store(false);
  // Clear execution queue on session end.
  {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    active_block_.reset();
    queued_blocks_.clear();
  }
  // Note: state_ stays at Stopping (or FailedStart). Terminal — do not
  // reset to Warming. A new session uses a new AirSession instance.
}

std::string AirSession::FailedStartReason() const {
  std::lock_guard<std::mutex> lock(failed_start_mutex_);
  return failed_start_reason_;
}

int64_t AirSession::BytesWritten() const {
  return emitter_ ? emitter_->BytesWrittenTotal() : 0;
}

int64_t AirSession::BytesDropped() const {
  return emitter_ ? emitter_->BytesDroppedTotal() : 0;
}

int64_t AirSession::PacerSleepMs() const {
  return pacer_ ? (pacer_->TotalSleepUs() / 1000) : 0;
}

int64_t AirSession::PacerLateReleases() const {
  return pacer_ ? pacer_->LateReleases() : 0;
}

}  // namespace retrovue::air
