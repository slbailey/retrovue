// Repository: Retrovue-playout
// Component: ITickProducer
// Purpose: Pure virtual interface for tick-driven producer methods used by
//          PipelineManager.  Separates tick operations from system-wide
//          IProducer identity so PipelineManager can hold IProducer pointers
//          and downcast to ITickProducer for blockplan-specific calls.
// Contract Reference: PlayoutAuthorityContract.md (P3.1a)
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_ITICK_PRODUCER_HPP_
#define RETROVUE_BLOCKPLAN_ITICK_PRODUCER_HPP_

#include <atomic>
#include <cstdint>
#include <optional>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"

namespace retrovue::blockplan {

struct FrameData;  // forward — defined in TickProducer.hpp

class ITickProducer {
 public:
  virtual ~ITickProducer() = default;

  enum class State { kEmpty, kReady };

  // Assign a block.  Synchronous: probes assets, opens decoder, seeks.
  virtual void AssignBlock(const FedBlock& block) = 0;

  // Try to decode the next frame for the current block position.
  // Returns FrameData if decoded, nullopt if decode failed.
  virtual std::optional<FrameData> TryGetFrame() = 0;

  // Reset to EMPTY, releasing decoder and block state.
  virtual void Reset() = 0;

  virtual State GetState() const = 0;
  virtual const FedBlock& GetBlock() const = 0;
  virtual int64_t FramesPerBlock() const = 0;
  virtual bool HasDecoder() const = 0;

  // Return the detected input (source) FPS from the decoder.
  // Returns 0.0 if unknown (no decoder, probe failed, etc.).
  virtual double GetInputFPS() const = 0;

  // Resample mode (rational detection: OFF / DROP / CADENCE).
  // Default OFF for producers that do not compute it.
  virtual ResampleMode GetResampleMode() const { return ResampleMode::OFF; }

  // For DROP mode: integer step (input frames per output frame). Always >= 1.
  virtual int64_t GetDropStep() const { return 1; }

  // INV-BLOCK-PRIME-002: True when a pre-decoded primed frame is available.
  // Retrieving a primed frame via TryGetFrame() is non-blocking.
  virtual bool HasPrimedFrame() const = 0;

  // True if the current segment has an audio stream (from decoder). For priming logs / INV-AUDIO-PRIME-002.
  virtual bool HasAudioStream() const { return false; }

  // INV-SEAM-SEG: Return computed segment boundaries for the assigned block.
  // Empty if no block assigned or validation failed.
  virtual const std::vector<SegmentBoundary>& GetBoundaries() const = 0;

  // Optional: Set interrupt flags for FFmpeg I/O. When either is true,
  // av_read_frame and other blocking calls abort promptly.
  // fill_stop: buffer's fill-stop signal (StopFilling/StopFillingAsync).
  // session_stop: session stop signal (ctx_->stop_requested).
  // Default no-op for producers that don't use FFmpeg.
  struct InterruptFlags {
    std::atomic<bool>* fill_stop = nullptr;
    std::atomic<bool>* session_stop = nullptr;
  };
  virtual void SetInterruptFlags(const InterruptFlags&) {}
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_ITICK_PRODUCER_HPP_
