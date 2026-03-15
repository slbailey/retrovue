// Repository: Retrovue-playout
// Component: TestDecoder
// Purpose: Deterministic frame producer for contract tests.
//          Generates synthetic video + audio frames without FFmpeg.
//          Implements both IProducer and ITickProducer so PipelineManager
//          can use it identically to a real TickProducer.
// Copyright (c) 2026 RetroVue

#pragma once

#include <atomic>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/IProducerFactory.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/RationalFps.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/IProducer.h"

namespace retrovue::blockplan::test_infra {

// TestDecoder: generates deterministic frames at the configured FPS.
// No file I/O, no FFmpeg, no asset resolution.  Frames are solid-color
// with Y plane = 0x10 + (frame_index % 200).  Audio is silence (zeroed S16).
//
// Supports:
//   - AssignBlock → computes frames_per_block from segment durations
//   - TryGetFrame → returns FrameData with video, audio, source_frame_index
//   - HasDecoder → always true after AssignBlock
//   - PrimeFirstTick simulation (via HasPrimedFrame)
//   - Seek (asset_start_offset_ms → skip frames)
//   - Segment boundaries
//   - Reset / lifecycle
class TestDecoder : public producers::IProducer,
                    public ITickProducer {
 public:
  TestDecoder(int width, int height, RationalFps output_fps)
      : width_(width), height_(height), output_fps_(output_fps) {}

  // --- IProducer ---
  bool start() override { running_ = true; return true; }
  void stop() override { Reset(); running_ = false; }
  bool isRunning() const override { return running_; }
  void RequestStop() override { stop_requested_ = true; }
  bool IsStopped() const override { return !running_; }

  // --- ITickProducer ---
  void AssignBlock(const FedBlock& block) override {
    std::lock_guard<std::mutex> lock(mutex_);
    block_ = block;

    // Simulate decoder failure for unresolvable URIs (matches production behavior).
    bool all_unresolvable = true;
    for (const auto& seg : block.segments) {
      if (seg.asset_uri.find("/nonexistent/") == std::string::npos &&
          seg.segment_type != SegmentType::kPad) {
        all_unresolvable = false;
        break;
      }
    }
    if (all_unresolvable && !block.segments.empty()) {
      has_decoder_ = false;
      state_ = State::kReady;
      return;
    }

    has_decoder_ = true;
    state_ = State::kReady;
    frame_index_ = 0;
    segment_index_ = 0;
    segment_frame_offset_ = 0;

    // Compute total frames from segment durations
    frames_per_block_ = 0;
    boundaries_.clear();
    int64_t cumulative_ms = 0;
    for (size_t i = 0; i < block.segments.size(); ++i) {
      const auto& seg = block.segments[i];
      int64_t seg_frames = output_fps_.FramesFromDurationCeilMs(seg.segment_duration_ms);
      cumulative_ms += seg.segment_duration_ms;
      frames_per_block_ += seg_frames;

      if (i < block.segments.size() - 1) {
        SegmentBoundary sb;
        sb.end_ct_ms = cumulative_ms;
        sb.segment_index = static_cast<int32_t>(i);
        boundaries_.push_back(sb);
      }
    }

    // Handle seek offset on first segment
    if (!block.segments.empty()) {
      int64_t offset_ms = block.segments[0].asset_start_offset_ms;
      if (offset_ms > 0 && output_fps_.num > 0) {
        int64_t skip = output_fps_.FramesFromDurationFloorMs(offset_ms);
        segment_frame_offset_ = skip;
      }
    }

    // Prime first frame
    auto fd = GenerateFrame();
    if (fd) {
      primed_frame_ = std::move(*fd);
      has_primed_ = true;
    }
  }

  std::optional<FrameData> TryGetFrame() override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!has_decoder_) return std::nullopt;

    // Return primed frame first
    if (has_primed_) {
      has_primed_ = false;
      return std::move(primed_frame_);
    }

    if (frame_index_ >= frames_per_block_) return std::nullopt;
    return GenerateFrame();
  }

  void Reset() override {
    std::lock_guard<std::mutex> lock(mutex_);
    has_decoder_ = false;
    state_ = State::kEmpty;
    frame_index_ = 0;
    has_primed_ = false;
  }

  State GetState() const override { return state_; }
  const FedBlock& GetBlock() const override { return block_; }
  int64_t FramesPerBlock() const override { return frames_per_block_; }
  bool HasDecoder() const override { return has_decoder_; }
  RationalFps GetInputRationalFps() const override { return output_fps_; }
  bool HasPrimedFrame() const override { return has_primed_; }
  bool HasAudioStream() const override { return true; }
  const std::vector<SegmentBoundary>& GetBoundaries() const override { return boundaries_; }
  int64_t GetFrameIndex() const override { return frame_index_; }
  void SetInterruptFlags(const InterruptFlags&) override {}

  // Not used by TestDecoder but required by production callers
  void SetAspectPolicy(runtime::AspectPolicy) {}

 private:
  std::optional<FrameData> GenerateFrame() {
    if (frame_index_ >= frames_per_block_) return std::nullopt;

    int64_t idx = frame_index_++;
    int64_t source_idx = segment_frame_offset_ + idx;

    // Compute block_ct_ms from frame index
    int64_t ct_ms = (output_fps_.den > 0 && output_fps_.num > 0)
        ? (idx * 1000 * output_fps_.den) / output_fps_.num
        : idx * 33;

    FrameData fd;
    fd.source_frame_index = source_idx;
    fd.block_ct_ms = ct_ms;

    // Determine current segment for asset_uri
    if (!block_.segments.empty()) {
      int64_t seg_boundary = 0;
      for (size_t s = 0; s < block_.segments.size(); ++s) {
        int64_t seg_frames = output_fps_.FramesFromDurationCeilMs(
            block_.segments[s].segment_duration_ms);
        if (idx < seg_boundary + seg_frames || s == block_.segments.size() - 1) {
          fd.asset_uri = block_.segments[s].asset_uri;
          break;
        }
        seg_boundary += seg_frames;
      }
    } else {
      fd.asset_uri = "test://synthetic";
    }

    // Generate solid-color video frame
    fd.video.width = width_;
    fd.video.height = height_;
    uint8_t y_val = static_cast<uint8_t>(0x10 + (source_idx % 200));
    size_t y_size = static_cast<size_t>(width_) * height_;
    size_t uv_size = y_size / 2;  // NV12: Y plane + interleaved UV
    fd.video.data.resize(y_size + uv_size);
    std::memset(fd.video.data.data(), y_val, y_size);
    std::memset(fd.video.data.data() + y_size, 128, uv_size);  // neutral chroma

    fd.video.metadata.pts = ct_ms * 1000;  // us
    fd.video.metadata.dts = ct_ms * 1000;

    // Generate one audio frame per video frame (silence, house format)
    buffer::AudioFrame af;
    af.sample_rate = 48000;
    af.channels = 2;
    // ~1 frame of audio at output fps
    af.nb_samples = (output_fps_.den > 0 && output_fps_.num > 0)
        ? static_cast<int>((48000LL * output_fps_.den + output_fps_.num - 1) / output_fps_.num)
        : 1601;
    af.pts_us = ct_ms * 1000;
    af.data.resize(static_cast<size_t>(af.nb_samples) * af.channels * sizeof(int16_t), 0);
    fd.audio.push_back(std::move(af));

    return fd;
  }

  int width_;
  int height_;
  RationalFps output_fps_;

  mutable std::mutex mutex_;
  FedBlock block_;
  bool has_decoder_ = false;
  State state_ = State::kEmpty;
  int64_t frame_index_ = 0;
  int64_t frames_per_block_ = 0;
  int64_t segment_frame_offset_ = 0;
  int segment_index_ = 0;
  bool running_ = false;
  std::atomic<bool> stop_requested_{false};

  bool has_primed_ = false;
  FrameData primed_frame_;
  std::vector<SegmentBoundary> boundaries_;
};

// TestProducerFactory: creates TestDecoder instances for contract tests.
class TestProducerFactory : public IProducerFactory {
 public:
  std::unique_ptr<producers::IProducer> Create(
      int width, int height, RationalFps output_fps) override {
    return std::make_unique<TestDecoder>(width, height, output_fps);
  }
};

}  // namespace retrovue::blockplan::test_infra
