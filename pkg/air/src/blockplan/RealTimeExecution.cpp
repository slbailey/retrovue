// Repository: Retrovue-playout
// Component: BlockPlan Real-Time Execution Implementation
// Purpose: Real implementations of executor interfaces for production execution
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/RealTimeExecution.hpp"

#include <cstring>
#include <iostream>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/decode/FFmpegDecoder.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

#ifdef RETROVUE_FFMPEG_AVAILABLE
extern "C" {
#include <libavformat/avformat.h>
}
#endif

#if defined(__linux__) || defined(__APPLE__)
#include <unistd.h>
#endif

namespace retrovue::blockplan::realtime {

// Frame duration for emission (33ms ≈ 30fps)
static constexpr int64_t kFrameDurationMs = 33;

// =============================================================================
// RealTimeClock Implementation
// =============================================================================

RealTimeClock::RealTimeClock()
    : start_time_(std::chrono::steady_clock::now()) {}

int64_t RealTimeClock::NowMs() const {
  auto now = std::chrono::steady_clock::now();
  auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      now - start_time_);
  return epoch_ms_ + elapsed.count() + virtual_offset_ms_;
}

void RealTimeClock::AdvanceMs(int64_t delta_ms) {
  // Real-time pacing: sleep for the specified duration
  if (delta_ms > 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(delta_ms));
  }
}

void RealTimeClock::SetMs(int64_t ms) {
  // Adjust virtual offset to make NowMs() return the target value
  auto now = std::chrono::steady_clock::now();
  auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      now - start_time_);
  virtual_offset_ms_ = ms - epoch_ms_ - elapsed.count();
}

void RealTimeClock::SetEpoch(int64_t epoch_ms) {
  epoch_ms_ = epoch_ms;
  start_time_ = std::chrono::steady_clock::now();
  virtual_offset_ms_ = 0;
}

// =============================================================================
// RealAssetSource Implementation
// =============================================================================

bool RealAssetSource::ProbeAsset(const std::string& uri) {
#ifdef RETROVUE_FFMPEG_AVAILABLE
  AVFormatContext* fmt_ctx = nullptr;

  // ========================================================================
  // INSTRUMENTATION: Detailed probe timing (open_input vs find_stream_info)
  // ========================================================================
  auto open_start = std::chrono::steady_clock::now();
  if (avformat_open_input(&fmt_ctx, uri.c_str(), nullptr, nullptr) < 0) {
    std::cerr << "[RealAssetSource] Failed to open: " << uri << std::endl;
    return false;
  }
  auto open_end = std::chrono::steady_clock::now();
  auto open_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      open_end - open_start).count();
  std::cout << "[METRIC] asset_open_input_ms=" << open_ms
            << " uri=" << uri << std::endl;

  auto stream_info_start = std::chrono::steady_clock::now();
  if (avformat_find_stream_info(fmt_ctx, nullptr) < 0) {
    avformat_close_input(&fmt_ctx);
    std::cerr << "[RealAssetSource] Failed to find stream info: " << uri << std::endl;
    return false;
  }
  auto stream_info_end = std::chrono::steady_clock::now();
  auto stream_info_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      stream_info_end - stream_info_start).count();
  std::cout << "[METRIC] asset_stream_info_ms=" << stream_info_ms
            << " uri=" << uri << std::endl;

  // Get duration in milliseconds
  int64_t duration_ms = 0;
  if (fmt_ctx->duration != AV_NOPTS_VALUE) {
    duration_ms = fmt_ctx->duration / 1000;  // AV_TIME_BASE is microseconds
  }

  avformat_close_input(&fmt_ctx);

  AssetInfo info;
  info.uri = uri;
  info.duration_ms = duration_ms;
  info.valid = true;
  assets_[uri] = info;

  std::cout << "[RealAssetSource] Probed: " << uri << " (" << duration_ms << "ms)" << std::endl;
  return true;
#else
  (void)uri;
  std::cerr << "[RealAssetSource] FFmpeg not available" << std::endl;
  return false;
#endif
}

int64_t RealAssetSource::GetDuration(const std::string& uri) const {
  auto it = assets_.find(uri);
  if (it == assets_.end()) return -1;
  return it->second.duration_ms;
}

bool RealAssetSource::HasAsset(const std::string& uri) const {
  return assets_.find(uri) != assets_.end();
}

const RealAssetSource::AssetInfo* RealAssetSource::GetAsset(const std::string& uri) const {
  auto it = assets_.find(uri);
  if (it == assets_.end()) return nullptr;
  return &it->second;
}

// =============================================================================
// RealTimeEncoderSink Implementation
// =============================================================================

RealTimeEncoderSink::RealTimeEncoderSink(const SinkConfig& config)
    : config_(config), pts_offset_90k_(config.initial_pts_offset_90k) {
  // Allocate frame buffers for YUV420P
  // INV-PTS-MONOTONIC: pts_offset_90k_ starts at initial value for session continuity
  const size_t y_size = static_cast<size_t>(config_.width * config_.height);
  const size_t uv_size = y_size / 4;
  y_buffer_.resize(y_size);
  u_buffer_.resize(uv_size);
  v_buffer_.resize(uv_size);

  std::cout << "[RealTimeEncoderSink] Constructed with pts_offset_90k_=" << pts_offset_90k_
            << (config.shared_encoder ? " (using shared encoder)" : " (will create own encoder)")
            << std::endl;
}

RealTimeEncoderSink::~RealTimeEncoderSink() {
  Close();
}

bool RealTimeEncoderSink::Open() {
  if (config_.fd < 0) {
    std::cerr << "[RealTimeEncoderSink] Invalid FD" << std::endl;
    return false;
  }

  // ==========================================================================
  // SESSION-LONG ENCODER: Use shared encoder if provided
  // ==========================================================================
  // When using a shared encoder:
  // - The muxer/encoder state persists across blocks
  // - Continuity counters are maintained
  // - No PAT/PMT reset
  // - DTS/PTS tracking continues seamlessly
  // ==========================================================================
  if (config_.shared_encoder) {
    encoder_ = config_.shared_encoder;
    using_shared_encoder_ = true;
    std::cout << "[RealTimeEncoderSink] Using shared session encoder (no re-init)" << std::endl;
    return true;
  }

  // Create encoder config (only if not using shared encoder)
  playout_sinks::mpegts::MpegTSPlayoutSinkConfig enc_config;
  enc_config.target_width = config_.width;
  enc_config.target_height = config_.height;
  enc_config.target_fps = config_.fps;
  enc_config.enable_audio = true;
  enc_config.gop_size = 90;      // I-frame every 3 seconds (reduces encoding spikes)
  enc_config.bitrate = 2000000;  // 2 Mbps (faster encoding)

  owned_encoder_ = std::make_unique<playout_sinks::mpegts::EncoderPipeline>(enc_config);
  encoder_ = owned_encoder_.get();
  using_shared_encoder_ = false;

  // Write callback that writes to FD
  auto write_callback = [](void* opaque, uint8_t* buf, int buf_size) -> int {
    auto* sink = static_cast<RealTimeEncoderSink*>(opaque);
#if defined(__linux__) || defined(__APPLE__)
    ssize_t written = write(sink->config_.fd, buf, static_cast<size_t>(buf_size));
    if (written > 0) {
      sink->bytes_written_ += written;
    }
    return static_cast<int>(written);
#else
    (void)buf;
    return buf_size;
#endif
  };

  if (!encoder_->open(enc_config, this, write_callback)) {
    std::cerr << "[RealTimeEncoderSink] Failed to open encoder" << std::endl;
    return false;
  }

  std::cout << "[RealTimeEncoderSink] Opened: " << config_.width << "x" << config_.height
            << " @ " << config_.fps << "fps" << std::endl;
  return true;
}

void RealTimeEncoderSink::GenerateBlackFrame(uint8_t* y_plane, uint8_t* u_plane, uint8_t* v_plane) {
  const size_t y_size = static_cast<size_t>(config_.width * config_.height);
  const size_t uv_size = y_size / 4;

  // YUV420P black: Y=16, U=128, V=128 (studio range)
  std::memset(y_plane, 16, y_size);
  std::memset(u_plane, 128, uv_size);
  std::memset(v_plane, 128, uv_size);
}

bool RealTimeEncoderSink::EmitFrame(const FrameMetadata& frame) {
  if (!encoder_) {
    return false;
  }

  frame_count_++;

  // ========================================================================
  // INSTRUMENTATION: First frame timing (per block)
  // ========================================================================
  if (frame_count_ == 1) {
    std::cout << "[METRIC] first_frame_emitted ct_ms=" << frame.ct_ms
              << " segment_index=" << frame.segment_index
              << " is_pad=" << (frame.is_pad ? "true" : "false") << std::endl;
  }

  // Handle block transitions (CT reset)
  // INV-PTS-MONOTONIC: PTS must be monotonically increasing across the entire session
  // INV-PTS-CONTINUOUS: PTS must advance by frame duration (no gaps)
  // INV-CT-UNCHANGED: CT resets to 0 at each block boundary (this is correct)
  // When CT drops, we're at a block boundary - accumulate the previous block's
  // duration into the offset so PTS continues increasing.
  if (last_ct_ms_ >= 0 && frame.ct_ms < last_ct_ms_) {
    // CT dropped - block transition, ACCUMULATE offset (not assign!)
    pts_offset_90k_ += (last_ct_ms_ + kFrameDurationMs) * 90;
  }
  last_ct_ms_ = frame.ct_ms;

  // Compute PTS in 90kHz units
  int64_t pts_90k = frame.ct_ms * 90 + pts_offset_90k_;

  // ==========================================================================
  // TRIPWIRE: Verify video PTS is monotonically increasing
  // ==========================================================================
  // This assertion catches bugs in PTS calculation before they reach the muxer.
  // If this fires, the bug is in our PTS offset tracking, not the encoder.
  // ==========================================================================
  if (last_video_pts_90k_ >= 0 && pts_90k <= last_video_pts_90k_) {
    std::cerr << "[TRIPWIRE] VIDEO PTS NOT MONOTONIC! "
              << "last=" << last_video_pts_90k_ << " (" << (last_video_pts_90k_ / 90.0) << "ms), "
              << "new=" << pts_90k << " (" << (pts_90k / 90.0) << "ms), "
              << "ct_ms=" << frame.ct_ms << ", offset=" << pts_offset_90k_
              << ", block_transition=" << (last_ct_ms_ >= 0 && frame.ct_ms < last_ct_ms_)
              << std::endl;
    // In debug builds, abort to catch this immediately
#ifndef NDEBUG
    std::abort();
#endif
  }
  last_video_pts_90k_ = pts_90k;

  const size_t y_size = static_cast<size_t>(config_.width * config_.height);
  const size_t uv_size = y_size / 4;

  buffer::Frame video_frame;
  video_frame.width = config_.width;
  video_frame.height = config_.height;

  bool decoded_ok = false;

  // For pad frames or if asset_uri is empty, generate black
  if (frame.is_pad || frame.asset_uri.empty()) {
    GenerateBlackFrame(y_buffer_.data(), u_buffer_.data(), v_buffer_.data());
  } else {
    // Try to decode real frame from asset
    // Check if we need to open/seek the decoder
    bool need_seek = false;

    if (!decoder_ || current_asset_uri_ != frame.asset_uri) {
      // Different asset - need to open new decoder
      decoder_.reset();
      current_asset_uri_ = frame.asset_uri;

      decode::DecoderConfig dec_config;
      dec_config.input_uri = frame.asset_uri;
      dec_config.target_width = config_.width;
      dec_config.target_height = config_.height;

      // ========================================================================
      // INSTRUMENTATION: Decoder open timing
      // ========================================================================
      auto decoder_open_start = std::chrono::steady_clock::now();
      decoder_ = std::make_unique<decode::FFmpegDecoder>(dec_config);
      if (!decoder_->Open()) {
        std::cerr << "[RealTimeEncoderSink] Failed to open decoder for: " << frame.asset_uri << std::endl;
        decoder_.reset();
        current_asset_uri_.clear();
      } else {
        auto decoder_open_end = std::chrono::steady_clock::now();
        auto decoder_open_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            decoder_open_end - decoder_open_start).count();
        std::cout << "[METRIC] decoder_open_ms=" << decoder_open_ms
                  << " uri=" << frame.asset_uri << std::endl;
        need_seek = true;
        next_frame_offset_ms_ = 0;
      }
    }

    // Check if we need to seek (new asset or discontinuous offset)
    if (decoder_ && !need_seek) {
      // If the requested offset is significantly different from where we expect to be,
      // we need to seek
      int64_t expected_offset = next_frame_offset_ms_;
      int64_t delta = frame.asset_offset_ms - expected_offset;
      if (delta < -kFrameDurationMs || delta > kFrameDurationMs * 2) {
        need_seek = true;
      }
    }

    if (decoder_ && need_seek) {
      if (!decoder_->SeekToMs(frame.asset_offset_ms)) {
        std::cerr << "[RealTimeEncoderSink] Seek failed to " << frame.asset_offset_ms << "ms" << std::endl;
      }
      next_frame_offset_ms_ = frame.asset_offset_ms;
    }

    // Decode the frame
    if (decoder_) {
      buffer::Frame decoded_frame;
      if (decoder_->DecodeFrameToBuffer(decoded_frame)) {
        // Copy decoded frame data to our video_frame
        video_frame = std::move(decoded_frame);
        decoded_ok = true;
        next_frame_offset_ms_ += kFrameDurationMs;
      } else if (decoder_->IsEOF()) {
        // Reached end of file - loop back to start
        decoder_->SeekToMs(0);
        next_frame_offset_ms_ = 0;
        if (decoder_->DecodeFrameToBuffer(decoded_frame)) {
          video_frame = std::move(decoded_frame);
          decoded_ok = true;
          next_frame_offset_ms_ += kFrameDurationMs;
        }
      }
    }

    // Fall back to black if decode failed
    if (!decoded_ok) {
      GenerateBlackFrame(y_buffer_.data(), u_buffer_.data(), v_buffer_.data());
    }
  }

  // If we didn't get a decoded frame, build from buffers
  if (!decoded_ok) {
    video_frame.data.resize(y_size + uv_size * 2);
    std::memcpy(video_frame.data.data(), y_buffer_.data(), y_size);
    std::memcpy(video_frame.data.data() + y_size, u_buffer_.data(), uv_size);
    std::memcpy(video_frame.data.data() + y_size + uv_size, v_buffer_.data(), uv_size);
    video_frame.width = config_.width;
    video_frame.height = config_.height;
  }

  video_frame.metadata.pts = pts_90k;
  video_frame.metadata.dts = pts_90k;
  video_frame.metadata.duration = kFrameDurationMs / 1000.0;
  video_frame.metadata.asset_uri = frame.asset_uri;
  video_frame.metadata.has_ct = true;

  // Encode the video frame
  if (!encoder_->encodeFrame(video_frame, pts_90k)) {
    std::cerr << "[RealTimeEncoderSink] encodeFrame failed at CT=" << frame.ct_ms << std::endl;
    // Continue even on failure - don't break the stream
  }

  // Phase 8.9: Encode pending audio frames from the decoder
  // Limit to 2 audio frames per video frame to stay within real-time budget.
  // (Video ~33ms, AAC audio ~21ms, so steady-state is ~1.5 audio/video)
  if (decoder_ && decoded_ok) {
    buffer::AudioFrame audio_frame;
    int audio_frames_this_call = 0;
    constexpr int kMaxAudioFramesPerVideoFrame = 2;

    while (audio_frames_this_call < kMaxAudioFramesPerVideoFrame &&
           decoder_->GetPendingAudioFrame(audio_frame)) {
      // =======================================================================
      // INV-PTS-MONOTONIC / INV-AUDIO-VIDEO-SYNC: CT-based audio PTS
      // =======================================================================
      // Audio PTS is computed from samples emitted within this block, NOT from
      // decoder timestamps (which are asset-relative and cause discontinuities
      // when the same asset continues across block boundaries).
      //
      // Formula: audio_pts_90k = session_offset + (samples_emitted * 90000 / sample_rate)
      //
      // This ensures audio and video share the same monotonic timeline.
      // Recv cadence is not used as a correctness signal.
      // =======================================================================
      int64_t audio_pts_90k = pts_offset_90k_ +
          (audio_samples_emitted_ * 90000 / kAudioSampleRate);

      // =======================================================================
      // TRIPWIRE: Verify audio PTS is monotonically increasing
      // =======================================================================
      if (last_audio_pts_90k_ >= 0 && audio_pts_90k <= last_audio_pts_90k_) {
        std::cerr << "[TRIPWIRE] AUDIO PTS NOT MONOTONIC! "
                  << "last=" << last_audio_pts_90k_ << ", new=" << audio_pts_90k
                  << ", samples_emitted=" << audio_samples_emitted_
                  << ", offset=" << pts_offset_90k_
                  << std::endl;
#ifndef NDEBUG
        std::abort();
#endif
      }
      last_audio_pts_90k_ = audio_pts_90k;

      // Disable silence injection since we have real audio
      if (!audio_started_) {
        encoder_->SetAudioLivenessEnabled(false);
        audio_started_ = true;
        std::cout << "[RealTimeEncoderSink] Real audio started at CT=" << frame.ct_ms << std::endl;
      }

      if (!encoder_->encodeAudioFrame(audio_frame, audio_pts_90k, false)) {
        std::cerr << "[RealTimeEncoderSink] encodeAudioFrame failed" << std::endl;
        // Continue even on failure
      }

      // Track samples emitted for next audio frame's PTS
      audio_samples_emitted_ += audio_frame.nb_samples;
      audio_frames_this_call++;
    }
  }

  return true;
}

void RealTimeEncoderSink::Close() {
  // ==========================================================================
  // SESSION-LONG ENCODER: Do NOT close/destroy shared encoder
  // ==========================================================================
  // When using a shared encoder, we only reset per-block state.
  // The encoder/muxer continues running for the next block.
  // This maintains continuity counters and DTS/PTS tracking.
  // ==========================================================================
  if (using_shared_encoder_) {
    // Shared encoder stays open - just log block completion
    std::cout << "[RealTimeEncoderSink] Block completed (shared encoder): "
              << frame_count_ << " frames, " << bytes_written_ << " bytes, "
              << "last_ct_ms=" << last_ct_ms_ << ", final_pts_offset=" << FinalPtsOffset90k()
              << std::endl;
    // Clear the pointer but don't delete (not owned)
    encoder_ = nullptr;
  } else {
    // Owned encoder - close and destroy
    if (owned_encoder_) {
      owned_encoder_->close();
      owned_encoder_.reset();
    }
    encoder_ = nullptr;
    std::cout << "[RealTimeEncoderSink] Closed: " << frame_count_ << " frames, "
              << bytes_written_ << " bytes" << std::endl;
  }
}

// =============================================================================
// RealTimeBlockExecutor Implementation
// This replicates the exact logic from BlockPlanExecutor but with real components
// =============================================================================

RealTimeBlockExecutor::RealTimeBlockExecutor(const Config& config)
    : config_(config) {}

RealTimeBlockExecutor::~RealTimeBlockExecutor() = default;

void RealTimeBlockExecutor::RequestTermination() {
  termination_requested_.store(true, std::memory_order_release);
}

void RealTimeBlockExecutor::Diag(const std::string& msg) {
  if (config_.diagnostic) {
    config_.diagnostic(msg);
  }
}

int32_t RealTimeBlockExecutor::FindSegmentForCt(
    const std::vector<SegmentBoundary>& boundaries,
    int64_t ct_ms) const {
  for (const auto& bound : boundaries) {
    if (ct_ms >= bound.start_ct_ms && ct_ms < bound.end_ct_ms) {
      return bound.segment_index;
    }
  }
  return -1;
}

const Segment* RealTimeBlockExecutor::GetSegmentByIndex(
    const BlockPlan& plan,
    int32_t segment_index) const {
  for (const auto& seg : plan.segments) {
    if (seg.segment_index == segment_index) {
      return &seg;
    }
  }
  return nullptr;
}

RealTimeBlockExecutor::Result RealTimeBlockExecutor::Execute(
    const ValidatedBlockPlan& validated,
    const JoinParameters& join_params) {

  const BlockPlan& plan = validated.plan;
  const auto& boundaries = validated.boundaries;

  // Block timing
  const int64_t block_duration_ms = plan.duration_ms();
  const int64_t block_start_wall_ms = plan.start_utc_ms;
  const int64_t block_end_wall_ms = plan.end_utc_ms;

  Diag("[Executor] Starting block: " + plan.block_id +
       " (duration=" + std::to_string(block_duration_ms) + "ms)");

  // Probe all assets in the block
  for (const auto& seg : plan.segments) {
    if (!assets_.HasAsset(seg.asset_uri)) {
      if (!assets_.ProbeAsset(seg.asset_uri)) {
        return Result{
            Result::Code::kAssetError,
            0,
            0,  // No PTS offset on error before sink initialized
            "Failed to probe asset: " + seg.asset_uri
        };
      }
    }
  }

  // Initialize encoder sink
  sink_ = std::make_unique<RealTimeEncoderSink>(config_.sink);
  if (!sink_->Open()) {
    return Result{
        Result::Code::kEncoderError,
        0,
        config_.sink.initial_pts_offset_90k,  // Preserve incoming offset on error
        "Failed to open encoder sink"
    };
  }

  // Set clock epoch to block start
  clock_.SetEpoch(block_start_wall_ms);

  // ==========================================================================
  // PHASE 1: Wait for block start (early join)
  // CONTRACT-JOIN-001: Early join waits for block start
  // ==========================================================================
  if (join_params.classification == JoinClassification::kEarly) {
    Diag("[Executor] Early join - waiting for block start");
    while (clock_.NowMs() < block_start_wall_ms) {
      std::this_thread::sleep_for(std::chrono::milliseconds(1));

      if (termination_requested_.load(std::memory_order_acquire)) {
        int64_t final_pts_offset = sink_->FinalPtsOffset90k();
        sink_->Close();
        return Result{Result::Code::kTerminated, 0, final_pts_offset, "Terminated during wait"};
      }
    }
  }

  // ==========================================================================
  // PHASE 2: Initialize CT
  // CONTRACT-JOIN-002: CT starts at ct_start_ms
  // ==========================================================================
  int64_t ct_ms = join_params.ct_start_ms;

  // Set wall clock to join time
  if (clock_.NowMs() < block_start_wall_ms) {
    clock_.SetMs(block_start_wall_ms);
  }

  // Current segment state
  int32_t current_segment_index = join_params.start_segment_index;
  const Segment* current_segment = GetSegmentByIndex(plan, current_segment_index);
  if (!current_segment) {
    int64_t final_pts_offset = sink_->FinalPtsOffset90k();
    sink_->Close();
    return Result{Result::Code::kAssetError, ct_ms, final_pts_offset, "Invalid start segment"};
  }

  // Get current segment boundary
  const SegmentBoundary* current_boundary = nullptr;
  for (const auto& b : boundaries) {
    if (b.segment_index == current_segment_index) {
      current_boundary = &b;
      break;
    }
  }

  // Asset state
  auto* current_asset = assets_.GetAsset(current_segment->asset_uri);
  if (!current_asset) {
    int64_t final_pts_offset = sink_->FinalPtsOffset90k();
    sink_->Close();
    return Result{
        Result::Code::kAssetError,
        ct_ms,
        final_pts_offset,
        "Asset not found: " + current_segment->asset_uri
    };
  }

  // Compute initial asset offset
  int64_t asset_offset_ms = join_params.effective_asset_offset_ms;

  Diag("[Executor] Starting execution at CT=" + std::to_string(ct_ms) +
       ", segment=" + std::to_string(current_segment_index));

  // ==========================================================================
  // PHASE 3: Main execution loop
  // CONTRACT-BLOCK-002: Block execution lifecycle
  // IDENTICAL TO BlockPlanExecutor logic
  // ==========================================================================
  while (true) {
    // Check termination
    if (termination_requested_.load(std::memory_order_acquire)) {
      int64_t final_pts_offset = sink_->FinalPtsOffset90k();
      sink_->Close();
      return Result{Result::Code::kTerminated, ct_ms, final_pts_offset, "Terminated"};
    }

    // =======================================================================
    // FENCE CHECK
    // CONTRACT-BLOCK-003: Execution stops exactly at end_utc_ms
    // =======================================================================
    if (ct_ms >= block_duration_ms) {
      Diag("[Executor] Fence reached at CT=" + std::to_string(ct_ms));
      // INV-PTS-MONOTONIC: Capture PTS offset before close for next block
      int64_t final_pts_offset = sink_->FinalPtsOffset90k();
      sink_->Close();
      return Result{Result::Code::kSuccess, ct_ms, final_pts_offset, ""};
    }

    // =======================================================================
    // SEGMENT BOUNDARY CHECK
    // CONTRACT-SEG-002: Transition at CT boundary
    // =======================================================================
    if (current_boundary && ct_ms >= current_boundary->end_ct_ms) {
      int32_t next_segment_index = current_segment_index + 1;
      const Segment* next_segment = GetSegmentByIndex(plan, next_segment_index);

      if (!next_segment) {
        int64_t final_pts_offset = sink_->FinalPtsOffset90k();
        sink_->Close();
        return Result{Result::Code::kSuccess, ct_ms, final_pts_offset, ""};
      }

      Diag("[Executor] Segment transition: " + std::to_string(current_segment_index) +
           " -> " + std::to_string(next_segment_index));

      current_segment_index = next_segment_index;
      current_segment = next_segment;

      for (const auto& b : boundaries) {
        if (b.segment_index == current_segment_index) {
          current_boundary = &b;
          break;
        }
      }

      current_asset = assets_.GetAsset(current_segment->asset_uri);
      if (!current_asset) {
        int64_t final_pts_offset = sink_->FinalPtsOffset90k();
        sink_->Close();
        return Result{
            Result::Code::kAssetError,
            ct_ms,
            final_pts_offset,
            "Asset not found: " + current_segment->asset_uri
        };
      }

      asset_offset_ms = current_segment->asset_start_offset_ms;
    }

    // =======================================================================
    // REAL-TIME PACING: Wait until frame deadline before starting work
    // This ensures writes happen at consistent intervals
    // =======================================================================
    if (!deadline_initialized_) {
      next_frame_deadline_ = std::chrono::steady_clock::now();
      deadline_initialized_ = true;
    } else {
      // Wait until deadline
      auto now = std::chrono::steady_clock::now();
      if (now < next_frame_deadline_) {
        std::this_thread::sleep_until(next_frame_deadline_);
      }
    }

    // =======================================================================
    // COMPUTE FRAME TO EMIT
    // =======================================================================
    FrameMetadata frame;
    frame.ct_ms = ct_ms;
    frame.wall_ms = clock_.NowMs();
    frame.segment_index = current_segment_index;

    // Check for underrun (asset EOF before segment end)
    if (asset_offset_ms >= current_asset->duration_ms) {
      // CONTRACT-SEG-003: Underrun pads to CT boundary
      frame.is_pad = true;
      frame.asset_uri = "";
      frame.asset_offset_ms = 0;
    } else {
      frame.is_pad = false;
      frame.asset_uri = current_asset->uri;
      frame.asset_offset_ms = asset_offset_ms;
    }

    // =======================================================================
    // EMIT FRAME
    // =======================================================================
    if (!sink_->EmitFrame(frame)) {
      int64_t final_pts_offset = sink_->FinalPtsOffset90k();
      sink_->Close();
      return Result{Result::Code::kEncoderError, ct_ms, final_pts_offset, "Encoder error"};
    }

    // =======================================================================
    // ADVANCE CT
    // FROZEN: Monotonic CT advancement (Section 8.1.1)
    // =======================================================================
    ct_ms += kFrameDurationMs;

    if (!frame.is_pad) {
      asset_offset_ms += kFrameDurationMs;
    }

    // Advance deadline for next frame
    next_frame_deadline_ += std::chrono::milliseconds(kFrameDurationMs);

    // If we're more than one frame behind, reset deadline to prevent catching up
    auto now = std::chrono::steady_clock::now();
    if (now > next_frame_deadline_ + std::chrono::milliseconds(kFrameDurationMs)) {
      next_frame_deadline_ = now + std::chrono::milliseconds(kFrameDurationMs);
    }

    // Progress logging every second
    if (ct_ms % 1000 < kFrameDurationMs) {
      Diag("[Executor] CT=" + std::to_string(ct_ms) + "ms, frames=" +
           std::to_string(sink_->FrameCount()));
    }
  }

  int64_t final_pts_offset = sink_->FinalPtsOffset90k();
  sink_->Close();
  return Result{Result::Code::kSuccess, ct_ms, final_pts_offset, ""};
}

}  // namespace retrovue::blockplan::realtime
