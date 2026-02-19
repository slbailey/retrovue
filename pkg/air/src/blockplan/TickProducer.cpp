// Repository: Retrovue-playout
// Component: TickProducer
// Purpose: Decode lifecycle for a single block in PipelineManager mode (P3.1a)
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/TickProducer.hpp"

#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>

#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "retrovue/decode/FFmpegDecoder.h"

namespace retrovue::blockplan {

static constexpr int kMaxAudioFramesPerVideoFrame = 2;

TickProducer::TickProducer(int width, int height, double fps)
    : width_(width),
      height_(height),
      output_fps_(fps),
      frame_duration_ms_(static_cast<int64_t>(1000.0 / fps)),
      input_frame_duration_ms_(static_cast<int64_t>(1000.0 / fps)) {}

TickProducer::~TickProducer() {
  Reset();
}

// =============================================================================
// AssignBlock — probe, validate, open decoder, seek
// Always transitions to READY (even on failure — fence still runs)
// =============================================================================

void TickProducer::AssignBlock(const FedBlock& block) {
  // Reset any previous state
  Reset();

  block_ = block;

  // Compute frames_per_block using exact fps to avoid truncation error.
  // OLD: ceil(duration_ms / frame_duration_ms_) — truncated integer division
  // NEW: ceil(duration_ms * output_fps_ / 1000.0) — exact floating-point
  int64_t duration_ms = block.end_utc_ms - block.start_utc_ms;
  frames_per_block_ = static_cast<int64_t>(
      std::ceil(static_cast<double>(duration_ms) * output_fps_ / 1000.0));

  // Convert FedBlock → BlockPlan for validation
  BlockPlan plan = FedBlockToBlockPlan(block);

  // Detect PAD segments
  has_pad_segments_ = false;
  for (const auto& seg : plan.segments) {
    if (seg.segment_type == SegmentType::kPad) {
      has_pad_segments_ = true;
      break;
    }
  }

  // Probe all segment assets (skip PAD — no asset to probe)
  bool all_probed = true;
  for (const auto& seg : plan.segments) {
    if (seg.segment_type == SegmentType::kPad) continue;
    if (!assets_.HasAsset(seg.asset_uri)) {
      if (!assets_.ProbeAsset(seg.asset_uri)) {
        std::cerr << "[TickProducer] Failed to probe asset: " << seg.asset_uri
                  << std::endl;
        all_probed = false;
        break;
      }
    }
  }

  if (!all_probed) {
    decoder_ok_ = false;
    state_ = State::kReady;
    std::cout << "[TickProducer] DECODER_STEP block_id=" << block.block_id
              << " step=probe result=fail (asset probe failed)" << std::endl;
    return;
  }

  // Validate via BlockPlanValidator to get segment boundaries
  auto asset_duration_fn = [this](const std::string& uri) -> int64_t {
    return assets_.GetDuration(uri);
  };
  BlockPlanValidator validator(asset_duration_fn);
  auto result = validator.Validate(plan, 0);  // t_receipt=0 — skip freshness

  if (!result.valid) {
    decoder_ok_ = false;
    state_ = State::kReady;
    std::cout << "[TickProducer] DECODER_STEP block_id=" << block.block_id
              << " step=validation result=fail detail=" << result.detail << std::endl;
    return;
  }

  validated_.plan = plan;
  validated_.boundaries = std::move(result.boundaries);
  boundaries_ = validated_.boundaries;

  // Initialize pad frames if block has PAD segments
  if (has_pad_segments_) {
    InitPadFrames();
  }

  // Open decoder for first segment
  if (plan.segments.empty()) {
    decoder_ok_ = false;
    state_ = State::kReady;
    return;
  }

  const auto& first_seg = plan.segments[0];

  // First segment is PAD — no decoder needed, generate pad frames directly
  if (first_seg.segment_type == SegmentType::kPad) {
    decoder_ok_ = false;
    current_asset_uri_.clear();
    current_segment_index_ = 0;
    block_ct_ms_ = 0;
    state_ = State::kReady;
    std::cout << "[TickProducer] Block assigned: " << block.block_id
              << " frames_per_block=" << frames_per_block_
              << " segments=" << plan.segments.size()
              << " first_segment=PAD"
              << " output_frame_dur_ms=" << frame_duration_ms_
              << std::endl;
    return;
  }

  decode::DecoderConfig dec_config;
  dec_config.input_uri = first_seg.asset_uri;
  dec_config.target_width = width_;
  dec_config.target_height = height_;

  decoder_ = std::make_unique<decode::FFmpegDecoder>(dec_config);
  if (!decoder_->Open()) {
    std::cout << "[TickProducer] DECODER_STEP block_id=" << block.block_id
              << " step=open result=fail asset_uri=" << first_seg.asset_uri
              << " (see FFmpegDecoder DECODER_STEP for exact stage)" << std::endl;
    decoder_.reset();
    decoder_ok_ = false;
    state_ = State::kReady;
    return;
  }

  // Seek to first segment's asset_start_offset_ms
  if (first_seg.asset_start_offset_ms > 0) {
    int preroll = decoder_->SeekPreciseToMs(first_seg.asset_start_offset_ms);
    if (preroll < 0) {
      std::cout << "[TickProducer] DECODER_STEP block_id=" << block.block_id
                << " step=seek result=fail offset_ms=" << first_seg.asset_start_offset_ms
                << " (see FFmpegDecoder DECODER_STEP seek)" << std::endl;
      decoder_.reset();
      decoder_ok_ = false;
      state_ = State::kReady;
      return;
    }
  }

  current_asset_uri_ = first_seg.asset_uri;
  next_frame_offset_ms_ = first_seg.asset_start_offset_ms;
  current_segment_index_ = 0;
  block_ct_ms_ = 0;
  seg_first_pts_ms_ = -1;  // INV-PTS-ANCHOR-RESET: capture from first decode
  decoder_ok_ = true;
  open_generation_++;
  std::cout << "[TickProducer] SEGMENT_DECODER_OPEN"
            << " block_id=" << block.block_id
            << " segment_index=0"
            << " asset_uri=" << first_seg.asset_uri
            << " open_generation=" << open_generation_
            << " seek_offset_ms=" << first_seg.asset_start_offset_ms
            << std::endl;

  // Detect input FPS from decoder for cadence support.
  // If input FPS differs from output FPS, PipelineManager will use
  // cadence-based frame repeat to avoid consuming content too fast.
  input_fps_ = decoder_->GetVideoFPS();
  if (input_fps_ > 0.0) {
    input_frame_duration_ms_ = static_cast<int64_t>(
        std::round(1000.0 / input_fps_));
  } else {
    input_frame_duration_ms_ = frame_duration_ms_;
  }

  state_ = State::kReady;

  std::cout << "[TickProducer] Block assigned: " << block.block_id
            << " frames_per_block=" << frames_per_block_
            << " segments=" << plan.segments.size()
            << " decoder_ok=true"
            << " has_pad=" << has_pad_segments_
            << " input_fps=" << input_fps_
            << " input_frame_dur_ms=" << input_frame_duration_ms_
            << " output_frame_dur_ms=" << frame_duration_ms_
            << std::endl;
}

void TickProducer::SetLogicalSegmentIndex(int32_t index) {
  logical_segment_index_ = index;
}

void TickProducer::SetInterruptFlags(const ITickProducer::InterruptFlags& flags) {
  interrupt_flags_ = flags;
  if (decoder_) {
    decode::FFmpegDecoder::InterruptFlags dec_flags;
    dec_flags.fill_stop = flags.fill_stop;
    dec_flags.session_stop = flags.session_stop;
    decoder_->SetInterruptFlags(dec_flags);
  }
}

// =============================================================================
// PrimeFirstFrame — INV-BLOCK-PRIME-001: decode first frame into held slot
// Called by ProducerPreloader::Worker after AssignBlock.
// =============================================================================

void TickProducer::PrimeFirstFrame() {
  if (state_ != State::kReady || !decoder_ok_ || !decoder_) {
    return;  // INV-BLOCK-PRIME-005: failure degrades safely
  }

  buffer::Frame video_frame;
  if (!decoder_->DecodeFrameToBuffer(video_frame)) {
    // INV-BLOCK-PRIME-005: decode failure → empty slot, still kReady
    return;
  }

  std::vector<buffer::AudioFrame> audio_frames;
  buffer::AudioFrame audio_frame;
  int audio_count = 0;
  while (audio_count < kMaxAudioFramesPerVideoFrame &&
         decoder_->GetPendingAudioFrame(audio_frame)) {
    audio_frames.push_back(std::move(audio_frame));
    audio_count++;
  }

  // PTS-anchored CT — same logic as TryGetFrame (INV-BLOCK-PRIME-007)
  int64_t decoded_pts_ms = video_frame.metadata.pts / 1000;

  // INV-PTS-ANCHOR-RESET: Capture PTS origin on first decode of segment.
  if (seg_first_pts_ms_ < 0) {
    seg_first_pts_ms_ = decoded_pts_ms;
  }

  int64_t seg_start_ct = 0;
  if (current_segment_index_ < static_cast<int32_t>(boundaries_.size())) {
    seg_start_ct = boundaries_[current_segment_index_].start_ct_ms;
  }
  int64_t ct_before = seg_start_ct + (decoded_pts_ms - seg_first_pts_ms_);
  block_ct_ms_ = ct_before + input_frame_duration_ms_;
  next_frame_offset_ms_ = decoded_pts_ms + input_frame_duration_ms_;

  primed_frame_ = FrameData{
      std::move(video_frame),
      std::move(audio_frames),
      current_asset_uri_,
      ct_before
  };

  std::cout << "[TickProducer] INV-BLOCK-PRIME-001: primed frame 0"
            << " pts_ms=" << decoded_pts_ms
            << " ct_before=" << ct_before
            << " asset=" << current_asset_uri_
            << std::endl;
}

// =============================================================================
// PrimeFirstTick — INV-AUDIO-PRIME-001: prime video + audio for fence readiness
// =============================================================================

TickProducer::PrimeResult TickProducer::PrimeFirstTick(int min_audio_prime_ms) {
  PrimeFirstFrame();
  if (!primed_frame_.has_value()) return {false, 0};

  // No audio threshold → behaves like PrimeFirstFrame.
  if (min_audio_prime_ms <= 0) return {true, 0};

  // Count audio already in primed frame.
  int64_t audio_samples = 0;
  for (const auto& af : primed_frame_->audio) {
    audio_samples += af.nb_samples;
  }
  int depth_ms = static_cast<int>(
      (audio_samples * 1000) / buffer::kHouseAudioSampleRate);
  if (depth_ms >= min_audio_prime_ms) return {true, depth_ms};

  // Move primed frame into local accumulation deque.
  std::deque<FrameData> primed_frames;
  primed_frames.push_back(std::move(*primed_frame_));
  primed_frame_.reset();

  // Decode additional frames until audio depth meets threshold.
  constexpr int kMaxNullRun = 10;
  constexpr int kMaxTotalDecodes = 60;
  constexpr int kMaxPrimeWallclockMs = 2000;
  auto prime_start = std::chrono::steady_clock::now();
  int null_run = 0;
  int total_decodes = 0;

  while (depth_ms < min_audio_prime_ms &&
         total_decodes < kMaxTotalDecodes) {
    // Wallclock timeout check.
    auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - prime_start).count();
    if (elapsed_ms >= kMaxPrimeWallclockMs) {
      std::cerr << "[TickProducer] INV-AUDIO-PRIME-001: wallclock timeout"
                << " elapsed_ms=" << elapsed_ms
                << " depth_ms=" << depth_ms
                << " total_decodes=" << total_decodes
                << std::endl;
      break;
    }

    total_decodes++;

    auto fd = DecodeNextFrameRaw();
    if (!fd) {
      null_run++;
      if (null_run >= kMaxNullRun) break;
      continue;
    }
    null_run = 0;

    // Accumulate audio depth from this frame.
    for (const auto& af : fd->audio) {
      audio_samples += af.nb_samples;
    }
    depth_ms = static_cast<int>(
        (audio_samples * 1000) / buffer::kHouseAudioSampleRate);

    primed_frames.push_back(std::move(*fd));
  }

  // Restore: first frame → primed_frame_, rest → buffered_frames_.
  primed_frame_ = std::move(primed_frames.front());
  primed_frames.pop_front();
  for (auto& f : primed_frames) {
    buffered_frames_.push_back(std::move(f));
  }

  bool met = depth_ms >= min_audio_prime_ms;

  std::cout << "[TickProducer] INV-AUDIO-PRIME-001: PrimeFirstTick"
            << " wanted_ms=" << min_audio_prime_ms
            << " got_ms=" << depth_ms
            << " met=" << met
            << " total_decodes=" << total_decodes
            << " null_run=" << null_run
            << " buffered_video=" << buffered_frames_.size()
            << std::endl;

  return {met, depth_ms};
}

// =============================================================================
// TryGetFrame — decode one frame, advance internal position
// =============================================================================

std::optional<FrameData> TickProducer::TryGetFrame() {
  if (state_ != State::kReady) {
    return std::nullopt;
  }

  // INV-BLOCK-PRIME-002: return primed frame without decode
  if (primed_frame_.has_value()) {
    auto frame = std::move(*primed_frame_);
    primed_frame_.reset();
    return frame;
  }

  // INV-AUDIO-PRIME-001: return buffered frames from PrimeFirstTick
  if (!buffered_frames_.empty()) {
    auto frame = std::move(buffered_frames_.front());
    buffered_frames_.pop_front();
    return frame;
  }

  // Decode-only path: handles both real decode and PAD generation.
  return DecodeNextFrameRaw();
}

// =============================================================================
// ApplyFade — apply linear video+audio fade to a FrameData in-place
// Contract Reference: docs/contracts/coordination/SegmentTransitionContract.md
// INV-TRANSITION-004: Fade applied using segment-relative CT.
// Video (YUV420P): Y *= alpha; U = 128 + (U-128)*alpha; V = 128 + (V-128)*alpha
// Audio (S16 interleaved): each sample *= alpha
// =============================================================================

static void ApplyFade(FrameData& fd, double alpha) {
  if (alpha <= 0.0) {
    // Full black + silence
    int y_size = fd.video.width * fd.video.height;
    int uv_size = (fd.video.width / 2) * (fd.video.height / 2);
    if (!fd.video.data.empty()) {
      std::memset(fd.video.data.data(), 0, static_cast<size_t>(y_size));
      std::memset(fd.video.data.data() + y_size, 128,
                  static_cast<size_t>(2 * uv_size));
    }
    for (auto& af : fd.audio) {
      std::memset(af.data.data(), 0, af.data.size());
    }
    return;
  }

  if (alpha >= 1.0) return;  // No change needed

  // Video: YUV420P layout [Y][U][V]
  if (!fd.video.data.empty() && fd.video.width > 0 && fd.video.height > 0) {
    int y_size = fd.video.width * fd.video.height;
    int uv_size = (fd.video.width / 2) * (fd.video.height / 2);
    uint8_t* y_plane = fd.video.data.data();
    uint8_t* u_plane = y_plane + y_size;
    uint8_t* v_plane = u_plane + uv_size;

    // Y plane: scale toward 0 (black)
    for (int i = 0; i < y_size && i < static_cast<int>(fd.video.data.size()); ++i) {
      y_plane[i] = static_cast<uint8_t>(y_plane[i] * alpha + 0.5);
    }
    // U plane: blend toward 128 (neutral chroma)
    for (int i = 0; i < uv_size; ++i) {
      int idx = y_size + i;
      if (idx >= static_cast<int>(fd.video.data.size())) break;
      u_plane[i] = static_cast<uint8_t>(128.0 + (u_plane[i] - 128.0) * alpha + 0.5);
    }
    // V plane: blend toward 128 (neutral chroma)
    for (int i = 0; i < uv_size; ++i) {
      int idx = y_size + uv_size + i;
      if (idx >= static_cast<int>(fd.video.data.size())) break;
      v_plane[i] = static_cast<uint8_t>(128.0 + (v_plane[i] - 128.0) * alpha + 0.5);
    }
  }

  // Audio: S16 interleaved — scale each sample by alpha
  for (auto& af : fd.audio) {
    int num_samples = af.nb_samples * af.channels;
    int16_t* samples = reinterpret_cast<int16_t*>(af.data.data());
    int max_samples = static_cast<int>(af.data.size() / sizeof(int16_t));
    for (int i = 0; i < num_samples && i < max_samples; ++i) {
      samples[i] = static_cast<int16_t>(samples[i] * alpha);
    }
  }
}

// =============================================================================
// DecodeNextFrameRaw — decode-only frame advancement (no delivery state)
// =============================================================================

std::optional<FrameData> TickProducer::DecodeNextFrameRaw() {
  if (state_ != State::kReady) {
    return std::nullopt;
  }

  // PAD segment: generate synthetic frame (no decoder needed).
  if (has_pad_segments_ &&
      current_segment_index_ < static_cast<int32_t>(validated_.plan.segments.size()) &&
      validated_.plan.segments[current_segment_index_].segment_type == SegmentType::kPad) {
    return GeneratePadFrame();
  }

  if (!decoder_ok_) {
    block_ct_ms_ += input_frame_duration_ms_;
    return std::nullopt;
  }

  buffer::Frame video_frame;
  if (!decoder_->DecodeFrameToBuffer(video_frame)) {
    if (decoder_->IsEOF()) {
      std::cout << "[TickProducer] SEGMENT_EOF"
                << " segment_index=" << current_segment_index_
                << " asset_uri=" << current_asset_uri_
                << " block_ct_ms=" << block_ct_ms_
                << " block_id=" << block_.block_id
                << std::endl;
      decoder_ok_ = false;
      return std::nullopt;
    }
    block_ct_ms_ += input_frame_duration_ms_;
    return std::nullopt;
  }

  std::vector<buffer::AudioFrame> audio_frames;
  buffer::AudioFrame audio_frame;
  int audio_count = 0;
  while (audio_count < kMaxAudioFramesPerVideoFrame &&
         decoder_->GetPendingAudioFrame(audio_frame)) {
    audio_frames.push_back(std::move(audio_frame));
    audio_count++;
  }

  int64_t decoded_pts_ms = video_frame.metadata.pts / 1000;
  if (seg_first_pts_ms_ < 0) {
    seg_first_pts_ms_ = decoded_pts_ms;
  }

  int64_t seg_start_ct = 0;
  if (current_segment_index_ < static_cast<int32_t>(boundaries_.size())) {
    seg_start_ct = boundaries_[current_segment_index_].start_ct_ms;
  }

  int64_t ct_before = seg_start_ct + (decoded_pts_ms - seg_first_pts_ms_);
  block_ct_ms_ = ct_before + input_frame_duration_ms_;
  next_frame_offset_ms_ = decoded_pts_ms + input_frame_duration_ms_;

  FrameData result{
      std::move(video_frame),
      std::move(audio_frames),
      current_asset_uri_,
      ct_before
  };

  // Apply segment transition fade (INV-TRANSITION-004: CT-based, not wall-clock).
  // Only applies to second-class breakpoints tagged by Python Core.
  if (current_segment_index_ < static_cast<int32_t>(validated_.plan.segments.size()) &&
      current_segment_index_ < static_cast<int32_t>(boundaries_.size())) {
    const auto& seg = validated_.plan.segments[current_segment_index_];
    const auto& boundary = boundaries_[current_segment_index_];

    double alpha = 1.0;

    // Transition in: fade from 0.0 → 1.0 over first transition_in_duration_ms
    if (seg.transition_in == TransitionType::kFade && seg.transition_in_duration_ms > 0) {
      int64_t seg_ct = ct_before - boundary.start_ct_ms;
      int64_t fade_dur = static_cast<int64_t>(seg.transition_in_duration_ms);
      if (seg_ct < fade_dur) {
        double in_alpha = static_cast<double>(seg_ct) / static_cast<double>(fade_dur);
        alpha = std::min(alpha, std::max(0.0, in_alpha));
      }
    }

    // Transition out: fade from 1.0 → 0.0 over last transition_out_duration_ms
    if (seg.transition_out == TransitionType::kFade && seg.transition_out_duration_ms > 0) {
      int64_t seg_duration = boundary.end_ct_ms - boundary.start_ct_ms;
      int64_t seg_ct = ct_before - boundary.start_ct_ms;
      int64_t fade_dur = static_cast<int64_t>(seg.transition_out_duration_ms);
      int64_t fade_start = seg_duration - fade_dur;
      if (seg_ct >= fade_start) {
        int64_t time_in_fade = seg_ct - fade_start;
        double out_alpha = 1.0 - static_cast<double>(time_in_fade) / static_cast<double>(fade_dur);
        alpha = std::min(alpha, std::max(0.0, out_alpha));
      }
    }

    if (alpha < 1.0) {
      ApplyFade(result, alpha);
    }
  }

  return result;
}

// =============================================================================
// InitPadFrames — pre-allocate black video + silence audio template
// =============================================================================

void TickProducer::InitPadFrames() {
  int y_size = width_ * height_;
  int uv_size = (width_ / 2) * (height_ / 2);
  pad_video_frame_.width = width_;
  pad_video_frame_.height = height_;
  pad_video_frame_.data.resize(
      static_cast<size_t>(y_size + 2 * uv_size));
  // Y = 0x10 (broadcast black), U/V = 0x80 (neutral chroma)
  std::memset(pad_video_frame_.data.data(), 0x10,
              static_cast<size_t>(y_size));
  std::memset(pad_video_frame_.data.data() + y_size, 0x80,
              static_cast<size_t>(2 * uv_size));

  int64_t sr = static_cast<int64_t>(buffer::kHouseAudioSampleRate);
  int64_t fps_num_i = static_cast<int64_t>(output_fps_ + 0.5);
  pad_audio_samples_per_frame_ = static_cast<int>(
      (sr + fps_num_i - 1) / fps_num_i);
}

// AdvanceToNextSegment REMOVED — reactive segment advancement replaced by
// eager overlap via SeamPreparer.  See INV-SEAM-SEG-001..006.

// =============================================================================
// GeneratePadFrame — return black+silence FrameData, advance CT
// =============================================================================

std::optional<FrameData> TickProducer::GeneratePadFrame() {
  buffer::Frame vf;
  vf.width = pad_video_frame_.width;
  vf.height = pad_video_frame_.height;
  vf.data = pad_video_frame_.data;  // Copy from pre-allocated template

  buffer::AudioFrame af;
  af.sample_rate = buffer::kHouseAudioSampleRate;
  af.channels = buffer::kHouseAudioChannels;
  af.nb_samples = pad_audio_samples_per_frame_;
  af.pts_us = 0;
  af.data.resize(
      static_cast<size_t>(pad_audio_samples_per_frame_) *
      static_cast<size_t>(buffer::kHouseAudioChannels) *
      sizeof(int16_t), 0);

  int64_t ct_before = block_ct_ms_;
  block_ct_ms_ += frame_duration_ms_;

  return FrameData{
      std::move(vf),
      {std::move(af)},
      "",         // No asset_uri for planned pad
      ct_before
  };
}

// =============================================================================
// Reset — back to EMPTY
// =============================================================================

void TickProducer::Reset() {
  decoder_.reset();
  decoder_ok_ = false;
  current_asset_uri_.clear();
  next_frame_offset_ms_ = 0;
  current_segment_index_ = 0;
  block_ct_ms_ = 0;
  frames_per_block_ = 0;
  boundaries_.clear();
  primed_frame_.reset();
  buffered_frames_.clear();
  has_pad_segments_ = false;
  input_fps_ = 0.0;
  input_frame_duration_ms_ = frame_duration_ms_;
  seg_first_pts_ms_ = -1;
  open_generation_ = 0;
  state_ = State::kEmpty;
}

TickProducer::State TickProducer::GetState() const {
  return state_;
}

const FedBlock& TickProducer::GetBlock() const {
  return block_;
}

int64_t TickProducer::FramesPerBlock() const {
  return frames_per_block_;
}

bool TickProducer::HasDecoder() const {
  return decoder_ok_;
}

double TickProducer::GetInputFPS() const {
  return input_fps_;
}

bool TickProducer::HasPrimedFrame() const {
  return primed_frame_.has_value();
}

const std::vector<SegmentBoundary>& TickProducer::GetBoundaries() const {
  return boundaries_;
}

// =============================================================================
// IProducer implementation
// =============================================================================

bool TickProducer::start() {
  running_ = true;
  stop_requested_ = false;
  return true;
}

void TickProducer::stop() {
  Reset();
  running_ = false;
}

bool TickProducer::isRunning() const {
  return running_;
}

void TickProducer::RequestStop() {
  stop_requested_ = true;
}

bool TickProducer::IsStopped() const {
  return !running_;
}

std::optional<producers::AsRunFrameStats>
TickProducer::GetAsRunFrameStats() const {
  return std::nullopt;
}

}  // namespace retrovue::blockplan
