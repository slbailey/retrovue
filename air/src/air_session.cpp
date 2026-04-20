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
#include "identity_normalizer.hpp"
#include "mpeg_ts_encoder.hpp"
#include "pad_source_producer.hpp"
#include "segment_fence.hpp"
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

void AirSession::SetSeamEventObserver(SeamEventObserver obs) {
  seam_event_observer_ = std::move(obs);
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

bool AirSession::HasContent() const {
  return active_block_.has_value() &&
         active_block_->segment_count() > 0 &&
         active_block_->IsPrimed(0);
}

bool AirSession::PrimeSegmentSync(BlockRuntime& rt, int32_t segment_index) {
  const auto& seg = rt.block().segments.at(segment_index);
  auto source = std::make_unique<FileSourceProducer>(
      FileSourceProducer::Config{.file_path = seg.asset_uri});
  if (!source->Prepare()) {
    rt.RecordFailure(segment_index, "ASSET_OPEN_FAILED");
    return false;
  }
  if (!source->Activate()) {
    rt.RecordFailure(segment_index, "ACTIVATE_FAILED");
    return false;
  }

  auto normalizer = std::make_unique<StandardNormalizer>(
      rt.block().canonical, source->VideoFrameRate(),
      source->VideoWidth(), source->VideoHeight(),
      source->AudioSampleRate(), source.get(),
      ChannelOrigin{.source_pts_anchor_us = 0, .channel_pts_anchor_us = 0},
      audio_samples_per_block_);

  PrimedSegment primed;
  primed.block_id = rt.block_id();
  primed.segment_index = segment_index;
  primed.source = std::move(source);
  primed.normalizer = std::move(normalizer);
  rt.InstallPrimed(segment_index, std::move(primed));
  return true;
}

bool AirSession::AssignContent(const std::string& input_path,
                               const ChannelCanonical& canonical) {
  // Legacy single-file entry. Synthesizes a one-segment Block and routes
  // through SeedActiveBlock, so all playback flows through BlockRuntime-
  // owned active-segment state. No parallel active-source ownership.
  if (!canonical.IsValid()) return false;
  Block legacy;
  legacy.block_id = "legacy:" + input_path;
  legacy.start_utc_ms = 0;
  legacy.end_utc_ms = 0;
  legacy.canonical = canonical;
  Segment s;
  s.segment_id = "legacy:" + input_path + ":0";
  s.asset_uri = input_path;
  s.asset_start_offset_ms = 0;
  s.duration_ms = 0;  // unknown; legacy mode plays until EOF
  s.segment_index = 0;
  legacy.segments.push_back(std::move(s));
  return SeedActiveBlock(legacy);
}

bool AirSession::SeedActiveBlock(const Block& block) {
  // Preconditions: output attached; not already seeded.
  if (emitter_ == nullptr) return false;
  if (active_block_.has_value()) return false;
  if (block.segments.empty()) return false;
  if (block.segments[0].asset_uri.empty()) return false;
  if (!block.canonical.IsValid()) return false;

  canonical_ = block.canonical;
  // Channel audio block: ~ one video-frame-period of samples at the
  // channel audio rate. For 30000/1001 video at 48kHz audio, this is
  // ~1601 samples. To become canonical-derived in C1.4a successor work.
  audio_samples_per_block_ = 1601;

  // Install BlockRuntime and prime ONLY segment 0 synchronously. OpenAir
  // requires segment 0 primed (first-byte-content invariant). Segments
  // 1..N-1 are left kRaw; the async PrimingPipeline started in OpenAir
  // primes them. This makes "successor late" a real runtime condition
  // (C1.4b) rather than an eager-prime bypass.
  BlockRuntime rt(block);
  if (!PrimeSegmentSync(rt, 0)) return false;

  // Build + open MpegTsEncoder with a callback that writes to emitter_.
  // Single instance; persists across seams (encoder continuity).
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
  encoder_ = std::move(encoder);

  std::lock_guard<std::mutex> lk(queue_mutex_);
  active_block_.emplace(std::move(rt));
  active_segment_index_.store(0);
  return true;
}

bool AirSession::AddQueuedBlock(const Block& block,
                                const std::string& /*predecessor_id*/,
                                std::string* reason_out) {
  // Phase B scope: validate session exists + block has ≥1 segment.
  // Predecessor validation, canonical-mismatch, and mutation-state rules
  // land in Phase C.
  std::lock_guard<std::mutex> lk(queue_mutex_);
  if (!active_block_.has_value()) {
    if (reason_out) *reason_out = "NO_SESSION";
    return false;
  }
  if (block.segments.empty()) {
    if (reason_out) *reason_out = "EMPTY_SEGMENTS";
    return false;
  }
  queued_blocks_.emplace_back(block);
  // If the priming pipeline is running (OpenAir occurred), wake it so
  // the new block's segments get primed eagerly. next_raw currently
  // scans only active_block_ — queued-block priming lands in C2, but
  // this Kick is harmless and keeps the plumbing warm.
  if (priming_pipeline_) priming_pipeline_->Kick();
  return true;
}

int32_t AirSession::QueueDepth() const {
  std::lock_guard<std::mutex> lk(queue_mutex_);
  int32_t depth = 0;
  if (active_block_.has_value()) ++depth;
  depth += static_cast<int32_t>(queued_blocks_.size());
  return depth;
}

int32_t AirSession::SegmentDepth() const {
  std::lock_guard<std::mutex> lk(queue_mutex_);
  int32_t count = 0;
  if (active_block_.has_value()) {
    count += static_cast<int32_t>(active_block_->segment_count());
  }
  for (const auto& br : queued_blocks_) {
    count += static_cast<int32_t>(br.segment_count());
  }
  return count;
}

bool AirSession::OpenAir() {
  // Preconditions: output + active block with segment 0 primed + encoder.
  if (emitter_ == nullptr) return false;
  if (!active_block_.has_value()) return false;
  if (active_block_->segment_count() == 0) return false;
  if (!active_block_->IsPrimed(0)) return false;
  if (encoder_ == nullptr) return false;
  if (encode_thread_.joinable()) return false;

  pacer_ = std::make_unique<EgressPacer>();
  gate_ = std::make_unique<BootstrapContentGate>();
  // SeamController reads readiness directly from BlockRuntime — ownership
  // contract from C1.3. Encode thread is the sole writer to
  // active_segment_index_; readiness lookup is unsynchronized by design
  // (Block state is guarded by queue_mutex_ on the priming-write side).
  seam_controller_ = std::make_unique<SeamController>(
      SeamConfig{},  // default arm_window_us = 1_000_000
      [this]() -> bool {
        std::lock_guard<std::mutex> lk(queue_mutex_);
        if (!active_block_.has_value()) return false;
        const int32_t next = active_segment_index_.load() + 1;
        if (next >= static_cast<int32_t>(active_block_->segment_count())) {
          return false;
        }
        return active_block_->IsPrimed(next);
      });
  if (seam_event_observer_) {
    seam_controller_->SetEventObserver(seam_event_observer_);
  }

  // Async priming pipeline. Enforces INV-SEGMENT-PRIMING-SINGLE-001
  // structurally (single worker). Hooks mutate BlockRuntime state under
  // queue_mutex_; encode-thread readers of State()/IsPrimed() take the
  // same lock during the seam-readiness callback.
  test_prime_call_idx_.store(0);
  PrimingPipeline::Hooks hooks;
  hooks.next_raw = [this]() -> std::optional<PrimingRequest> {
    auto req = FindNextRawSegment();
    if (req.has_value()) {
      int64_t delay_ms = 0;
      if (!test_prime_delays_ms_.empty()) {
        const std::size_t idx = test_prime_call_idx_.fetch_add(1);
        delay_ms = (idx < test_prime_delays_ms_.size())
                       ? test_prime_delays_ms_[idx]
                       : 0;
      } else {
        delay_ms = test_prime_delay_ms_.load();
      }
      if (delay_ms > 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
      }
    }
    return req;
  };
  hooks.on_priming = [this](const std::string& block_id, int32_t idx) {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    if (active_block_.has_value() && active_block_->block_id() == block_id) {
      active_block_->SetState(idx, SegmentPrimeState::kPriming);
    }
  };
  hooks.on_primed = [this](PrimedSegment primed) {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    if (active_block_.has_value() &&
        active_block_->block_id() == primed.block_id) {
      active_block_->InstallPrimed(primed.segment_index, std::move(primed));
    }
  };
  hooks.on_failed = [this](const std::string& block_id, int32_t idx,
                           const std::string& reason) {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    if (active_block_.has_value() && active_block_->block_id() == block_id) {
      active_block_->RecordFailure(idx, reason);
    }
  };
  priming_pipeline_ = std::make_unique<PrimingPipeline>(std::move(hooks));

  stopping_.store(false);
  state_.store(SessionState::Warming);
  warming_duration_us_.store(-1);
  bootstrap_total_duration_us_.store(-1);
  seams_executed_.store(0);
  pad_bridge_events_total_.store(0);
  pad_bridge_ms_total_.store(0);
  channel_pts_offset_us_ = 0;
  in_pad_bridge_ = false;
  pad_bridge_start_mono_us_ = 0;
  pad_frames_in_current_bridge_ = 0;
  warmup_video_.clear();
  warmup_audio_.clear();

  priming_pipeline_->Start();
  priming_pipeline_->Kick();  // immediately look for raw segments

  encode_thread_ = std::thread([this]() { EncodeLoop(); });
  return true;
}

std::optional<PrimingRequest> AirSession::FindNextRawSegment() {
  std::lock_guard<std::mutex> lk(queue_mutex_);
  if (!active_block_.has_value()) return std::nullopt;
  const auto& block = active_block_->block();
  const int32_t start = active_segment_index_.load() + 1;
  for (int32_t i = start;
       i < static_cast<int32_t>(active_block_->segment_count()); ++i) {
    if (active_block_->State(i) == SegmentPrimeState::kRaw) {
      PrimingRequest r;
      r.block_id = block.block_id;
      r.segment_index = i;
      r.asset_uri = block.segments[i].asset_uri;
      r.asset_start_offset_ms = block.segments[i].asset_start_offset_ms;
      r.canonical = block.canonical;
      r.samples_per_channel_audio_block = audio_samples_per_block_;
      return r;
    }
  }
  return std::nullopt;
}

void AirSession::EngagePadBridge() {
  // Called from the encode thread when a seam fence has passed with the
  // successor still not primed. Retires the current segment, accumulates
  // the channel-PTS offset for segment 0's duration, and brings up pad
  // source + identity normalizer to cover the gap. Same encoder + pacer;
  // encoder continuity preserved.
  const int32_t cur_idx = active_segment_index_.load();
  const auto& cur_seg = active_block_->block().segments[cur_idx];
  auto& cur_rt = active_block_->at(cur_idx);

  channel_pts_offset_us_ += cur_seg.duration_ms * 1000;
  if (cur_rt.source) cur_rt.source->Retire();
  active_block_->SetState(cur_idx, SegmentPrimeState::kRetired);

  pad_source_ = std::make_unique<PadSourceProducer>(canonical_);
  pad_source_->Prepare();
  pad_source_->Activate();
  pad_normalizer_ = std::make_unique<IdentityNormalizer>(
      canonical_, pad_source_.get(),
      ChannelOrigin{.source_pts_anchor_us = 0, .channel_pts_anchor_us = 0});

  in_pad_bridge_ = true;
  pad_bridge_start_mono_us_ = MonoUs();
  pad_frames_in_current_bridge_ = 0;
  pad_bridge_events_total_.fetch_add(1);
}

void AirSession::ObserveNextSeam() {
  const int32_t from_idx = active_segment_index_.load();
  const int32_t to_idx = from_idx + 1;
  const auto& block = active_block_->block();
  const auto fence_us = SegmentFenceMonotonicUs(
      block, from_idx,
      SessionAnchor{.anchor_monotonic_us = anchor_monotonic_us_,
                    .anchor_utc_ms = anchor_utc_ms_});
  if (!fence_us.has_value()) return;  // no next segment / out-of-range
  seam_controller_.get()->ObserveSeam(SeamTarget{
      .from_block_id = block.block_id,
      .from_segment_index = from_idx,
      .to_block_id = block.block_id,
      .to_segment_index = to_idx,
      .fence_monotonic_us = *fence_us,
      .is_block_transition = false,
  });
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

  // Mark segment 0 as active. Segment 0 is primed (precondition of OpenAir).
  active_block_->SetState(0, SegmentPrimeState::kActive);

  auto ActiveNormalizer = [this]() -> StandardNormalizer* {
    return active_block_->at(active_segment_index_.load()).normalizer.get();
  };

  // ---- Phase 1: WARMING — pre-buffer frames; byte path HELD CLOSED. ----
  // Pull from the active segment's normalizer into the warmup deques.
  // Evaluate the gate every tick. Exit on gate fire (→ Ready) or source
  // EOF before readiness (→ FailedStart).
  while (!stopping_.load() && !gate_->HasFired()) {
    auto vf = ActiveNormalizer()->PullVideo();
    if (!vf.has_value()) {
      FailStart("SOURCE_EOF_DURING_WARMUP");
      return;
    }
    warmup_video_.push_back(std::move(*vf));
    auto ab = ActiveNormalizer()->PullAudio();
    if (ab.has_value()) warmup_audio_.push_back(std::move(*ab));

    BootstrapContentGate::ReadinessSnapshot snapshot{
        .video_buffer_depth = warmup_video_.size(),
        .audio_buffer_depth = warmup_audio_.size(),
        .decoder_healthy = true,
    };
    if (gate_->Evaluate(snapshot) == BootstrapContentGate::Verdict::Ready) {
      warming_duration_us_.store(MonoUs() - warming_entered_mono_us);
      TransitionTo(SessionState::Ready, "gate_fired");
      break;
    }
  }

  if (stopping_.load()) return;
  if (state_.load() == SessionState::FailedStart) return;

  // ---- Phase 2: READY → ON_AIR. ----
  const int64_t on_air_entered_mono_us = MonoUs();
  bootstrap_total_duration_us_.store(on_air_entered_mono_us -
                                     warming_entered_mono_us);

  // Establish the session anchor. monotonic side = now; UTC side = the
  // active Block's start_utc_ms. Segment fence arithmetic (C1.1) consumes
  // this anchor; encoder-loop swap timing derives from it.
  anchor_monotonic_us_ = on_air_entered_mono_us;
  anchor_utc_ms_ = active_block_->block().start_utc_ms;

  // If more than one segment, arm the first seam (0→1).
  if (active_block_->segment_count() >= 2) {
    ObserveNextSeam();
  }

  TransitionTo(SessionState::OnAir, "first_emit");

  // ---- Phase 3: ON_AIR — drain warmup, then pull, honoring seams. ----
  const int64_t video_period_us =
      canonical_.video.frame_rate.PeriodMicros();
  while (!stopping_.load()) {
    const int64_t now = MonoUs();

    // Pad-bridge engagement detection: fence passed + controller still
    // observing (successor not primed in time). Happens at most once per
    // seam; in_pad_bridge_ guards re-entry.
    if (!in_pad_bridge_ && seam_controller_->Phase() == SeamPhase::kObserving) {
      const auto& target = seam_controller_->CurrentTarget();
      if (target.has_value() && now >= target->fence_monotonic_us) {
        EngagePadBridge();
      }
    }

    // Seam-commit check. Two paths: pad-bridge exit (install primed
    // successor after a gap) or happy-path direct swap.
    if (seam_controller_->ShouldCommitAt(now)) {
      const int32_t new_idx = active_segment_index_.load() + 1;
      auto& successor_rt = active_block_->at(new_idx);

      if (in_pad_bridge_) {
        // Pad PTS advance: pad frames were emitted at channel rate;
        // their cumulative duration is the right offset advance so the
        // successor's 0-based normalizer picks up past pad's last PTS.
        channel_pts_offset_us_ +=
            pad_frames_in_current_bridge_ * video_period_us;
        if (pad_source_) pad_source_->Retire();
        pad_source_.reset();
        pad_normalizer_.reset();
        const int64_t bridge_ms =
            (now - pad_bridge_start_mono_us_) / 1000;
        if (bridge_ms > 0) pad_bridge_ms_total_.fetch_add(bridge_ms);
        in_pad_bridge_ = false;

        // JIP per INV-SEAM-LATE-SUCCESSOR-JIP-001. Frame-accurate
        // entry is required: backward keyframe seek + forward decode-
        // and-discard until the first queued frame is at-or-after
        // target. Call MUST complete before MarkFired so the seam
        // does not activate until the successor is positioned. Runs
        // synchronously on the encode thread; this is a real-time
        // trade-off for v1 (async pre-seek during pad is a future
        // optimisation).
        const int64_t fence_mono_us =
            seam_controller_->CurrentTarget()->fence_monotonic_us;
        const int64_t lateness_ms = (now - fence_mono_us) / 1000;
        const auto& successor_seg =
            active_block_->block().segments[new_idx];
        const int64_t jip_offset_ms =
            successor_seg.asset_start_offset_ms + lateness_ms;
        if (successor_rt.source) {
          successor_rt.source->SeekFrameAccurate(jip_offset_ms);
        }
        successor_rt.jip_lateness_ms = lateness_ms;
      } else {
        // Happy path: current segment's normalizer is still live.
        // Offset advances by (duration − jip_lateness_ms) — for a
        // non-JIP'd predecessor this equals full duration; for a
        // JIP'd predecessor, the skipped head is already accounted
        // for in the pad-exit offset advance and must NOT be double-
        // counted here.
        const int32_t cur_idx = active_segment_index_.load();
        auto& cur_rt = active_block_->at(cur_idx);
        const int64_t cur_duration_us =
            active_block_->block().segments[cur_idx].duration_ms * 1000;
        const int64_t jip_adjust_us = cur_rt.jip_lateness_ms * 1000;
        channel_pts_offset_us_ += (cur_duration_us - jip_adjust_us);
        if (cur_rt.source) cur_rt.source->Retire();
        active_block_->SetState(cur_idx, SegmentPrimeState::kRetired);
      }

      active_segment_index_.store(new_idx);
      active_block_->SetState(new_idx, SegmentPrimeState::kActive);

      seam_controller_->MarkFired(now);
      seams_executed_.fetch_add(1);
      seam_controller_->Reset();

      // Arm next seam if another segment follows.
      if (new_idx + 1 < static_cast<int32_t>(active_block_->segment_count())) {
        ObserveNextSeam();
      }
    }

    // Source of frames: pad during bridge, else the active segment's
    // normalizer. Warmup only ever holds segment-0 frames and is drained
    // before any seam can fire.
    std::optional<VideoFrame> vf_opt;
    if (!warmup_video_.empty()) {
      vf_opt = std::move(warmup_video_.front());
      warmup_video_.pop_front();
    } else if (in_pad_bridge_) {
      vf_opt = pad_normalizer_->PullVideo();
      if (vf_opt.has_value()) ++pad_frames_in_current_bridge_;
    } else {
      vf_opt = ActiveNormalizer()->PullVideo();
    }
    if (!vf_opt.has_value()) break;

    vf_opt->pts_us_relative += channel_pts_offset_us_;
    pacer_->WaitFor(vf_opt->pts_us_relative);
    if (!encoder_->EncodeVideo(*vf_opt)) break;
    frames_encoded_.fetch_add(1);

    std::optional<AudioBlock> ab_opt;
    if (!warmup_audio_.empty()) {
      ab_opt = std::move(warmup_audio_.front());
      warmup_audio_.pop_front();
    } else if (in_pad_bridge_) {
      ab_opt = pad_normalizer_->PullAudio();
    } else {
      ab_opt = ActiveNormalizer()->PullAudio();
    }
    if (ab_opt.has_value()) {
      ab_opt->pts_us_relative += channel_pts_offset_us_;
      encoder_->EncodeAudio(*ab_opt);
    }

    // Advance seam state each frame. During pad bridge, this is how the
    // controller picks up that the successor has finally become primed
    // and arms/commits/fires.
    seam_controller_->Tick(MonoUs());
  }

  // Drain a few extra audio blocks on the active segment so the mux
  // interleaver has enough audio to cover the final video span.
  for (int extra = 0; extra < 10; ++extra) {
    auto ab = ActiveNormalizer()->PullAudio();
    if (!ab.has_value()) break;
    ab->pts_us_relative += channel_pts_offset_us_;
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
  // Stop priming worker BEFORE touching BlockRuntime — the worker's hooks
  // hold `this` and read/write active_block_. Encode thread is already
  // joined; this is the last remaining source of concurrent access.
  if (priming_pipeline_) {
    priming_pipeline_->Stop();
  }
  if (encoder_) {
    encoder_->Close();
  }
  if (owned_fd_ >= 0) {
    ::close(owned_fd_);
    owned_fd_ = -1;
  }
  // Retire any still-active sources owned by BlockRuntime slots before
  // tearing down. Encode thread is joined above, so no races.
  {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    if (active_block_.has_value()) {
      for (std::size_t i = 0; i < active_block_->segment_count(); ++i) {
        auto& srt = active_block_->at(static_cast<int32_t>(i));
        if (srt.source) srt.source->Retire();
      }
    }
    for (auto& brt : queued_blocks_) {
      for (std::size_t i = 0; i < brt.segment_count(); ++i) {
        auto& srt = brt.at(static_cast<int32_t>(i));
        if (srt.source) srt.source->Retire();
      }
    }
  }
  encoder_.reset();
  pacer_.reset();
  gate_.reset();
  seam_controller_.reset();
  priming_pipeline_.reset();
  if (pad_source_) pad_source_->Retire();
  pad_source_.reset();
  pad_normalizer_.reset();
  in_pad_bridge_ = false;
  pad_frames_in_current_bridge_ = 0;
  emitter_.reset();
  warmup_video_.clear();
  warmup_audio_.clear();
  frames_encoded_.store(0);
  seams_executed_.store(0);
  pad_bridge_events_total_.store(0);
  pad_bridge_ms_total_.store(0);
  stopping_.store(false);
  // Clear execution queue on session end.
  {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    active_block_.reset();
    active_segment_index_.store(0);
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
