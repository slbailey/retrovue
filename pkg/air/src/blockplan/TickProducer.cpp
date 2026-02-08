// Repository: Retrovue-playout
// Component: TickProducer
// Purpose: Decode lifecycle for a single block in PipelineManager mode (P3.1a)
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/TickProducer.hpp"

#include <cmath>
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

  // Probe all segment assets
  bool all_probed = true;
  for (const auto& seg : plan.segments) {
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
    std::cout << "[TickProducer] Block assigned (no decoder — probe failed): "
              << block.block_id << " frames_per_block=" << frames_per_block_
              << std::endl;
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
    std::cerr << "[TickProducer] Validation failed: " << result.detail
              << std::endl;
    return;
  }

  validated_.plan = plan;
  validated_.boundaries = std::move(result.boundaries);
  boundaries_ = validated_.boundaries;

  // Open decoder for first segment
  if (plan.segments.empty()) {
    decoder_ok_ = false;
    state_ = State::kReady;
    return;
  }

  const auto& first_seg = plan.segments[0];
  decode::DecoderConfig dec_config;
  dec_config.input_uri = first_seg.asset_uri;
  dec_config.target_width = width_;
  dec_config.target_height = height_;

  decoder_ = std::make_unique<decode::FFmpegDecoder>(dec_config);
  if (!decoder_->Open()) {
    std::cerr << "[TickProducer] Failed to open decoder: "
              << first_seg.asset_uri << std::endl;
    decoder_.reset();
    decoder_ok_ = false;
    state_ = State::kReady;
    return;
  }

  // Seek to first segment's asset_start_offset_ms
  if (first_seg.asset_start_offset_ms > 0) {
    int preroll = decoder_->SeekPreciseToMs(first_seg.asset_start_offset_ms);
    if (preroll < 0) {
      std::cerr << "[TickProducer] Seek failed to "
                << first_seg.asset_start_offset_ms << "ms" << std::endl;
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
  decoder_ok_ = true;

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
            << " input_fps=" << input_fps_
            << " input_frame_dur_ms=" << input_frame_duration_ms_
            << " output_frame_dur_ms=" << frame_duration_ms_
            << std::endl;
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
  int64_t seg_asset_start = 0;
  int64_t seg_start_ct = 0;
  if (current_segment_index_ < static_cast<int32_t>(boundaries_.size())) {
    seg_start_ct = boundaries_[current_segment_index_].start_ct_ms;
  }
  if (current_segment_index_ <
      static_cast<int32_t>(validated_.plan.segments.size())) {
    seg_asset_start =
        validated_.plan.segments[current_segment_index_].asset_start_offset_ms;
  }
  int64_t ct_before = seg_start_ct + (decoded_pts_ms - seg_asset_start);
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

  if (!decoder_ok_) {
    block_ct_ms_ += input_frame_duration_ms_;
    return std::nullopt;
  }

  // Check segment boundary
  if (!boundaries_.empty() &&
      current_segment_index_ < static_cast<int32_t>(boundaries_.size())) {
    const auto& boundary = boundaries_[current_segment_index_];
    if (block_ct_ms_ >= boundary.end_ct_ms) {
      // Transition to next segment
      int32_t next_index = current_segment_index_ + 1;
      if (next_index >= static_cast<int32_t>(validated_.plan.segments.size())) {
        // Past last segment — pad
        block_ct_ms_ += input_frame_duration_ms_;
        return std::nullopt;
      }

      const auto& next_seg = validated_.plan.segments[next_index];
      current_segment_index_ = next_index;

      // Open decoder for new segment
      decode::DecoderConfig dec_config;
      dec_config.input_uri = next_seg.asset_uri;
      dec_config.target_width = width_;
      dec_config.target_height = height_;

      decoder_ = std::make_unique<decode::FFmpegDecoder>(dec_config);
      if (!decoder_->Open()) {
        std::cerr << "[TickProducer] Failed to open decoder for segment "
                  << next_index << ": " << next_seg.asset_uri << std::endl;
        decoder_.reset();
        decoder_ok_ = false;
        block_ct_ms_ += input_frame_duration_ms_;
        return std::nullopt;
      }

      if (next_seg.asset_start_offset_ms > 0) {
        int preroll =
            decoder_->SeekPreciseToMs(next_seg.asset_start_offset_ms);
        if (preroll < 0) {
          decoder_.reset();
          decoder_ok_ = false;
          block_ct_ms_ += input_frame_duration_ms_;
          return std::nullopt;
        }
      }

      current_asset_uri_ = next_seg.asset_uri;
      next_frame_offset_ms_ = next_seg.asset_start_offset_ms;
    }
  }

  // Check if asset offset exceeds asset duration (underrun → pad)
  const auto* asset_info = assets_.GetAsset(current_asset_uri_);
  if (asset_info && next_frame_offset_ms_ >= asset_info->duration_ms) {
    block_ct_ms_ += input_frame_duration_ms_;
    return std::nullopt;
  }

  // Decode frame
  buffer::Frame video_frame;
  if (!decoder_->DecodeFrameToBuffer(video_frame)) {
    if (decoder_->IsEOF()) {
      // Loop: seek to 0 and retry
      decoder_->SeekToMs(0);
      if (!decoder_->DecodeFrameToBuffer(video_frame)) {
        block_ct_ms_ += input_frame_duration_ms_;
        return std::nullopt;
      }
    } else {
      block_ct_ms_ += input_frame_duration_ms_;
      return std::nullopt;
    }
  }

  // Extract audio (up to 2 frames)
  std::vector<buffer::AudioFrame> audio_frames;
  buffer::AudioFrame audio_frame;
  int audio_count = 0;
  while (audio_count < kMaxAudioFramesPerVideoFrame &&
         decoder_->GetPendingAudioFrame(audio_frame)) {
    audio_frames.push_back(std::move(audio_frame));
    audio_count++;
  }

  // Anchor block_ct_ms_ and next_frame_offset_ms_ to decoded PTS.
  // This prevents rounding error from accumulating across frames.
  // PTS is in microseconds from stream start; convert to milliseconds.
  int64_t decoded_pts_ms = video_frame.metadata.pts / 1000;

  // Derive block CT from actual decoded position within current segment
  int64_t seg_asset_start = 0;
  int64_t seg_start_ct = 0;
  if (current_segment_index_ < static_cast<int32_t>(boundaries_.size())) {
    seg_start_ct = boundaries_[current_segment_index_].start_ct_ms;
  }
  if (current_segment_index_ < static_cast<int32_t>(validated_.plan.segments.size())) {
    seg_asset_start = validated_.plan.segments[current_segment_index_].asset_start_offset_ms;
  }

  int64_t ct_before = seg_start_ct + (decoded_pts_ms - seg_asset_start);

  // Advance: +1 frame estimate for NEXT-frame boundary/underrun checks.
  // Single-frame rounding (max 0.3ms), never accumulated.
  block_ct_ms_ = ct_before + input_frame_duration_ms_;
  next_frame_offset_ms_ = decoded_pts_ms + input_frame_duration_ms_;

  return FrameData{
      std::move(video_frame),
      std::move(audio_frames),
      current_asset_uri_,   // P3.2
      ct_before             // P3.2
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
  input_fps_ = 0.0;
  input_frame_duration_ms_ = frame_duration_ms_;
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
