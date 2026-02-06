// Repository: Retrovue-playout
// Component: BlockSource
// Purpose: Decode lifecycle for a single block in ContinuousOutput mode (P3.1a)
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/BlockSource.hpp"

#include <cmath>
#include <iostream>

#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "retrovue/decode/FFmpegDecoder.h"

namespace retrovue::blockplan {

static constexpr int kMaxAudioFramesPerVideoFrame = 2;

BlockSource::BlockSource(int width, int height, double fps)
    : width_(width),
      height_(height),
      frame_duration_ms_(static_cast<int64_t>(1000.0 / fps)) {}

BlockSource::~BlockSource() {
  Reset();
}

// =============================================================================
// AssignBlock — probe, validate, open decoder, seek
// Always transitions to READY (even on failure — fence still runs)
// =============================================================================

void BlockSource::AssignBlock(const FedBlock& block) {
  // Reset any previous state
  Reset();

  block_ = block;

  // Compute frames_per_block = ceil(duration_ms / frame_duration_ms)
  int64_t duration_ms = block.end_utc_ms - block.start_utc_ms;
  frames_per_block_ = static_cast<int64_t>(
      std::ceil(static_cast<double>(duration_ms) /
                static_cast<double>(frame_duration_ms_)));

  // Convert FedBlock → BlockPlan for validation
  BlockPlan plan = FedBlockToBlockPlan(block);

  // Probe all segment assets
  bool all_probed = true;
  for (const auto& seg : plan.segments) {
    if (!assets_.HasAsset(seg.asset_uri)) {
      if (!assets_.ProbeAsset(seg.asset_uri)) {
        std::cerr << "[BlockSource] Failed to probe asset: " << seg.asset_uri
                  << std::endl;
        all_probed = false;
        break;
      }
    }
  }

  if (!all_probed) {
    decoder_ok_ = false;
    state_ = State::kReady;
    std::cout << "[BlockSource] Block assigned (no decoder — probe failed): "
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
    std::cerr << "[BlockSource] Validation failed: " << result.detail
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
    std::cerr << "[BlockSource] Failed to open decoder: "
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
      std::cerr << "[BlockSource] Seek failed to "
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
  state_ = State::kReady;

  std::cout << "[BlockSource] Block assigned: " << block.block_id
            << " frames_per_block=" << frames_per_block_
            << " segments=" << plan.segments.size()
            << " decoder_ok=true" << std::endl;
}

// =============================================================================
// TryGetFrame — decode one frame, advance internal position
// =============================================================================

std::optional<BlockSource::FrameData> BlockSource::TryGetFrame() {
  if (state_ != State::kReady) {
    return std::nullopt;
  }

  if (!decoder_ok_) {
    block_ct_ms_ += frame_duration_ms_;
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
        block_ct_ms_ += frame_duration_ms_;
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
        std::cerr << "[BlockSource] Failed to open decoder for segment "
                  << next_index << ": " << next_seg.asset_uri << std::endl;
        decoder_.reset();
        decoder_ok_ = false;
        block_ct_ms_ += frame_duration_ms_;
        return std::nullopt;
      }

      if (next_seg.asset_start_offset_ms > 0) {
        int preroll =
            decoder_->SeekPreciseToMs(next_seg.asset_start_offset_ms);
        if (preroll < 0) {
          decoder_.reset();
          decoder_ok_ = false;
          block_ct_ms_ += frame_duration_ms_;
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
    block_ct_ms_ += frame_duration_ms_;
    return std::nullopt;
  }

  // Decode frame
  buffer::Frame video_frame;
  if (!decoder_->DecodeFrameToBuffer(video_frame)) {
    if (decoder_->IsEOF()) {
      // Loop: seek to 0 and retry
      decoder_->SeekToMs(0);
      if (!decoder_->DecodeFrameToBuffer(video_frame)) {
        block_ct_ms_ += frame_duration_ms_;
        return std::nullopt;
      }
    } else {
      block_ct_ms_ += frame_duration_ms_;
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

  // Capture CT before advancing
  int64_t ct_before = block_ct_ms_;
  block_ct_ms_ += frame_duration_ms_;
  next_frame_offset_ms_ += frame_duration_ms_;

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

void BlockSource::Reset() {
  decoder_.reset();
  decoder_ok_ = false;
  current_asset_uri_.clear();
  next_frame_offset_ms_ = 0;
  current_segment_index_ = 0;
  block_ct_ms_ = 0;
  frames_per_block_ = 0;
  boundaries_.clear();
  state_ = State::kEmpty;
}

BlockSource::State BlockSource::GetState() const {
  return state_;
}

const FedBlock& BlockSource::GetBlock() const {
  return block_;
}

int64_t BlockSource::FramesPerBlock() const {
  return frames_per_block_;
}

bool BlockSource::HasDecoder() const {
  return decoder_ok_;
}

}  // namespace retrovue::blockplan
