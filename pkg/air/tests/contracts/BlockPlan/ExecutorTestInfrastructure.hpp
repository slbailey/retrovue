// Repository: Retrovue-playout
// Component: BlockPlan Executor Test Infrastructure
// Purpose: Fakes and mocks for deterministic executor testing
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md Section 7
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_EXECUTOR_TEST_INFRASTRUCTURE_HPP_
#define RETROVUE_BLOCKPLAN_EXECUTOR_TEST_INFRASTRUCTURE_HPP_

#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"

namespace retrovue::blockplan::testing {

// =============================================================================
// Emitted Frame (output from executor)
// =============================================================================

struct EmittedFrame {
  int64_t ct_ms;           // Content Time when frame was emitted
  int64_t wall_ms;         // Wall clock when frame was emitted
  int32_t segment_index;   // Which segment this frame came from
  bool is_pad;             // True if this is a pad frame (black/silence)

  // For verification
  std::string asset_uri;   // Source asset (empty if pad)
  int64_t asset_offset_ms; // Offset within asset (0 if pad)
};

// =============================================================================
// Fake Clock
// FROZEN: CT single-writer (Section 8.1.1) - clock provides wall time only
// =============================================================================

class FakeClock {
 public:
  FakeClock() : current_ms_(0) {}

  // Get current wall clock time
  int64_t NowMs() const { return current_ms_; }

  // Advance wall clock by delta
  void AdvanceMs(int64_t delta_ms) { current_ms_ += delta_ms; }

  // Set absolute wall clock time
  void SetMs(int64_t ms) { current_ms_ = ms; }

 private:
  int64_t current_ms_;
};

// =============================================================================
// Fake Asset Frame
// =============================================================================

struct FakeAssetFrame {
  int64_t offset_ms;       // Position within asset
  int64_t duration_ms;     // Frame duration (e.g., 33ms for 30fps)
  bool is_video;           // True for video, false for audio
};

// =============================================================================
// Fake Asset
// Simulates an asset with known frame sequence
// =============================================================================

struct FakeAsset {
  std::string uri;
  int64_t duration_ms;
  std::vector<FakeAssetFrame> frames;

  // For simulating failures
  std::optional<int64_t> fail_at_offset_ms;  // If set, fail when reading at this offset
};

// =============================================================================
// Fake Asset Source
// Provides frames from fake assets, can simulate underrun/overrun/failure
// =============================================================================

class FakeAssetSource {
 public:
  // Register a fake asset
  void RegisterAsset(const FakeAsset& asset) {
    assets_[asset.uri] = asset;
  }

  // Create a simple asset with uniform frame rate
  void RegisterSimpleAsset(const std::string& uri, int64_t duration_ms, int64_t frame_duration_ms = 33) {
    FakeAsset asset;
    asset.uri = uri;
    asset.duration_ms = duration_ms;

    int64_t offset = 0;
    while (offset < duration_ms) {
      FakeAssetFrame frame;
      frame.offset_ms = offset;
      frame.duration_ms = frame_duration_ms;
      frame.is_video = true;
      asset.frames.push_back(frame);
      offset += frame_duration_ms;
    }

    assets_[uri] = asset;
  }

  // Create an asset that will fail at a specific offset
  void RegisterFailingAsset(const std::string& uri, int64_t duration_ms, int64_t fail_at_ms) {
    RegisterSimpleAsset(uri, duration_ms);
    assets_[uri].fail_at_offset_ms = fail_at_ms;
  }

  // Get asset duration (-1 if not found)
  int64_t GetDuration(const std::string& uri) const {
    auto it = assets_.find(uri);
    if (it == assets_.end()) return -1;
    return it->second.duration_ms;
  }

  // Check if asset exists
  bool HasAsset(const std::string& uri) const {
    return assets_.find(uri) != assets_.end();
  }

  // Get asset (for executor to read)
  const FakeAsset* GetAsset(const std::string& uri) const {
    auto it = assets_.find(uri);
    if (it == assets_.end()) return nullptr;
    return &it->second;
  }

  // AssetDurationFn for validator
  AssetDurationFn AsDurationFn() const {
    return [this](const std::string& uri) { return GetDuration(uri); };
  }

 private:
  std::map<std::string, FakeAsset> assets_;
};

// =============================================================================
// Recording Sink
// Captures all emitted frames for verification
// =============================================================================

class RecordingSink {
 public:
  void EmitFrame(const EmittedFrame& frame) {
    frames_.push_back(frame);
  }

  const std::vector<EmittedFrame>& Frames() const { return frames_; }

  size_t FrameCount() const { return frames_.size(); }

  bool Empty() const { return frames_.empty(); }

  void Clear() { frames_.clear(); }

  // Verification helpers

  // Check all CT values are strictly monotonic
  // FROZEN: Monotonic CT advancement (Section 8.1.1)
  bool AllCtMonotonic() const {
    for (size_t i = 1; i < frames_.size(); ++i) {
      if (frames_[i].ct_ms <= frames_[i-1].ct_ms) {
        return false;
      }
    }
    return true;
  }

  // Get first frame CT
  std::optional<int64_t> FirstCtMs() const {
    if (frames_.empty()) return std::nullopt;
    return frames_.front().ct_ms;
  }

  // Get last frame CT
  std::optional<int64_t> LastCtMs() const {
    if (frames_.empty()) return std::nullopt;
    return frames_.back().ct_ms;
  }

  // Get first wall time
  std::optional<int64_t> FirstWallMs() const {
    if (frames_.empty()) return std::nullopt;
    return frames_.front().wall_ms;
  }

  // Count pad frames
  size_t PadFrameCount() const {
    size_t count = 0;
    for (const auto& f : frames_) {
      if (f.is_pad) ++count;
    }
    return count;
  }

  // Count frames from specific segment
  size_t FramesFromSegment(int32_t segment_index) const {
    size_t count = 0;
    for (const auto& f : frames_) {
      if (f.segment_index == segment_index) ++count;
    }
    return count;
  }

  // Check no frame has CT beyond limit
  bool NoCtBeyond(int64_t limit_ms) const {
    for (const auto& f : frames_) {
      if (f.ct_ms >= limit_ms) return false;
    }
    return true;
  }

  // Check no real (non-pad) frame from segment has CT beyond limit
  bool NoRealFrameBeyondCt(int32_t segment_index, int64_t limit_ct_ms) const {
    for (const auto& f : frames_) {
      if (f.segment_index == segment_index && !f.is_pad && f.ct_ms >= limit_ct_ms) {
        return false;
      }
    }
    return true;
  }

  // Find first frame from a segment
  std::optional<EmittedFrame> FirstFrameFromSegment(int32_t segment_index) const {
    for (const auto& f : frames_) {
      if (f.segment_index == segment_index) return f;
    }
    return std::nullopt;
  }

  // Check all frames in CT range are pad frames
  bool AllPadInCtRange(int64_t start_ct_ms, int64_t end_ct_ms) const {
    for (const auto& f : frames_) {
      if (f.ct_ms >= start_ct_ms && f.ct_ms < end_ct_ms) {
        if (!f.is_pad) return false;
      }
    }
    return true;
  }

 private:
  std::vector<EmittedFrame> frames_;
};

// =============================================================================
// Executor Result
// =============================================================================

enum class ExecutorExitCode {
  kSuccess,              // Block completed at fence
  kAssetError,           // Asset read/decode failure
  kLookaheadExhausted,   // No next block at fence (only for multi-block)
  kTerminated,           // External termination request
};

struct ExecutorResult {
  ExecutorExitCode exit_code;
  int64_t final_ct_ms;        // CT at termination
  int64_t final_wall_ms;      // Wall clock at termination
  std::string error_detail;   // For failures
};

// =============================================================================
// Executor Interface (to be implemented)
// This interface is derived from the contract tests
// =============================================================================

class IBlockPlanExecutor {
 public:
  virtual ~IBlockPlanExecutor() = default;

  // Execute a validated block plan
  // FROZEN: No Core communication during execution (Section 8.1.4)
  // Returns when: fence reached, failure occurs, or termination requested
  virtual ExecutorResult Execute(
      const ValidatedBlockPlan& plan,
      const JoinParameters& join_params,
      FakeClock* clock,
      FakeAssetSource* assets,
      RecordingSink* sink) = 0;

  // Request graceful termination (for external stop)
  virtual void RequestTermination() = 0;
};

}  // namespace retrovue::blockplan::testing

#endif  // RETROVUE_BLOCKPLAN_EXECUTOR_TEST_INFRASTRUCTURE_HPP_
