// Repository: Retrovue-playout
// Component: MpegTsSink for Standalone Harness
// Purpose: Real MPEG-TS file output sink for BlockPlanExecutor verification
// Copyright (c) 2025 RetroVue

#include "MpegTsSink.hpp"

#include <cstring>
#include <fstream>
#include <iostream>

#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "ExecutorTestInfrastructure.hpp"

namespace retrovue::standalone {

namespace {

// File output context for AVIO callback
struct FileOutputContext {
  std::ofstream file;
  size_t bytes_written = 0;
};

// AVIO write callback - writes to file
int FileWriteCallback(void* opaque, uint8_t* buf, int buf_size) {
  auto* ctx = static_cast<FileOutputContext*>(opaque);
  if (!ctx || !ctx->file.is_open()) {
    return AVERROR(EIO);
  }

  ctx->file.write(reinterpret_cast<char*>(buf), buf_size);
  if (!ctx->file.good()) {
    return AVERROR(EIO);
  }

  ctx->bytes_written += buf_size;
  return buf_size;
}

}  // namespace

// =============================================================================
// MpegTsSink Implementation
// =============================================================================

MpegTsSink::MpegTsSink(const std::string& output_path, int width, int height, double fps)
    : output_path_(output_path),
      width_(width),
      height_(height),
      fps_(fps) {

  // Create encoder config
  config_ = std::make_unique<playout_sinks::mpegts::MpegTSPlayoutSinkConfig>();
  config_->target_width = width;
  config_->target_height = height;
  config_->target_fps = fps;
  config_->bitrate = 2000000;  // 2 Mbps - reasonable for test output
  config_->gop_size = static_cast<int>(fps);  // 1 GOP per second
  config_->stub_mode = false;  // Real encoding
  config_->enable_audio = true;  // Include audio track
  config_->persistent_mux = true;  // No header resends in middle of stream

  // Pre-allocate black frame (YUV420P)
  // Y plane: width * height bytes (all 16 for black)
  // U plane: (width/2) * (height/2) bytes (all 128 for neutral)
  // V plane: (width/2) * (height/2) bytes (all 128 for neutral)
  size_t y_size = width * height;
  size_t uv_size = (width / 2) * (height / 2);
  black_frame_data_.resize(y_size + 2 * uv_size);

  // Y = 16 (black in TV range)
  std::memset(black_frame_data_.data(), 16, y_size);
  // U = 128 (neutral chroma)
  std::memset(black_frame_data_.data() + y_size, 128, uv_size);
  // V = 128 (neutral chroma)
  std::memset(black_frame_data_.data() + y_size + uv_size, 128, uv_size);

  // Pre-allocate silent audio (PCM S16 interleaved stereo)
  // Audio frame at 48kHz with AAC typically uses 1024 samples
  // For 30fps video, audio frames should align: 48000 / 30 = 1600 samples per video frame
  // But AAC encoder needs 1024 samples per frame
  audio_samples_per_frame_ = 1024;
  int channels = 2;
  silent_audio_data_.resize(audio_samples_per_frame_ * channels * sizeof(int16_t), 0);
}

MpegTsSink::~MpegTsSink() {
  Close();
}

bool MpegTsSink::Open() {
  if (is_open_) {
    return true;
  }

  // Create encoder
  encoder_ = std::make_unique<playout_sinks::mpegts::EncoderPipeline>(*config_);

  // Open output file
  auto* file_ctx = new FileOutputContext();
  file_ctx->file.open(output_path_, std::ios::binary | std::ios::trunc);
  if (!file_ctx->file.is_open()) {
    std::cerr << "[MpegTsSink] Failed to open output file: " << output_path_ << std::endl;
    delete file_ctx;
    return false;
  }

  // Open encoder with file callback
  if (!encoder_->open(*config_, file_ctx, FileWriteCallback)) {
    std::cerr << "[MpegTsSink] Failed to initialize encoder" << std::endl;
    file_ctx->file.close();
    delete file_ctx;
    return false;
  }

  // Disable silence injection and output timing - we're deterministic
  encoder_->SetAudioLivenessEnabled(false);
  encoder_->SetOutputTimingEnabled(false);
  encoder_->SetProducerCTAuthoritative(true);

  std::cerr << "[MpegTsSink] Opened: " << output_path_
            << " (" << width_ << "x" << height_ << " @ " << fps_ << "fps)" << std::endl;

  is_open_ = true;
  return true;
}

void MpegTsSink::EmitFrame(const blockplan::testing::EmittedFrame& frame) {
  if (!is_open_ || !encoder_) {
    return;
  }

  // Convert CT (milliseconds) to PTS (90kHz)
  // This is the deterministic mapping: no wall-clock involvement
  int64_t raw_pts_90k = frame.ct_ms * 90;

  // Handle block transitions: CT resets to 0 per block, but MPEG-TS needs monotonic PTS.
  // When CT drops (new block), add offset to maintain continuous PTS.
  if (last_input_ct_ms_ >= 0 && frame.ct_ms < last_input_ct_ms_) {
    // CT dropped - this is a block transition
    // Add the previous block's final PTS (plus one frame) to the offset
    pts_offset_90k_ = last_output_pts_90k_ + static_cast<int64_t>(90000.0 / fps_);
    std::cerr << "[MpegTsSink] Block transition detected: CT " << last_input_ct_ms_
              << "ms -> " << frame.ct_ms << "ms, new offset=" << pts_offset_90k_ << std::endl;
  }
  last_input_ct_ms_ = frame.ct_ms;

  // Apply offset for continuous PTS
  int64_t pts_90k = raw_pts_90k + pts_offset_90k_;

  // Verify monotonicity (should always be true after offset adjustment)
  if (last_output_pts_90k_ >= 0 && pts_90k <= last_output_pts_90k_) {
    std::cerr << "[MpegTsSink] ERROR: Non-monotonic PTS after offset: " << pts_90k
              << " <= " << last_output_pts_90k_ << std::endl;
    // Force monotonicity by incrementing
    pts_90k = last_output_pts_90k_ + 1;
  }
  last_output_pts_90k_ = pts_90k;

  // Create frame for encoder
  buffer::Frame video_frame;
  video_frame.width = width_;
  video_frame.height = height_;
  video_frame.metadata.pts = pts_90k;
  video_frame.metadata.dts = pts_90k;
  video_frame.metadata.duration = 1.0 / fps_;
  video_frame.metadata.has_ct = true;

  if (frame.is_pad) {
    // Padding frame: use pre-generated black frame
    video_frame.data = black_frame_data_;
    video_frame.metadata.asset_uri = "black";
    ++pad_frames_encoded_;
  } else {
    // Real frame: for the standalone harness, we don't have actual video data
    // from the fake assets. Use black frame as placeholder.
    // In production, this would be actual decoded video from FileProducer.
    video_frame.data = black_frame_data_;
    video_frame.metadata.asset_uri = frame.asset_uri;
  }

  // Encode video frame
  if (!encoder_->encodeFrame(video_frame, pts_90k)) {
    std::cerr << "[MpegTsSink] Failed to encode video frame at PTS=" << pts_90k << std::endl;
  }

  // Encode audio frame (silent for padding, or placeholder for real)
  buffer::AudioFrame audio_frame;
  audio_frame.data = silent_audio_data_;
  audio_frame.sample_rate = buffer::kHouseAudioSampleRate;  // 48000
  audio_frame.channels = buffer::kHouseAudioChannels;        // 2
  audio_frame.nb_samples = audio_samples_per_frame_;
  audio_frame.pts_us = frame.ct_ms * 1000;  // CT in microseconds

  if (!encoder_->encodeAudioFrame(audio_frame, pts_90k, frame.is_pad)) {
    // Audio encoding failures are logged but not fatal
  }

  ++frames_encoded_;
}

void MpegTsSink::Close() {
  if (!is_open_) {
    return;
  }

  if (encoder_) {
    // Flush audio
    encoder_->flushAudio();
    // Close encoder (writes trailer)
    encoder_->close();
    encoder_.reset();
  }

  is_open_ = false;

  std::cerr << "[MpegTsSink] Closed: " << frames_encoded_ << " frames encoded ("
            << pad_frames_encoded_ << " padding)" << std::endl;
}

}  // namespace retrovue::standalone
