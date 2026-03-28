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
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/RationalFps.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/runtime/AspectPolicy.h"

namespace retrovue::blockplan {

// FrameData: decoded frame + audio + metadata.
// Defined here (not in TickProducer.hpp) because DecodeResult needs it complete.
struct FrameData {
  buffer::Frame video;
  std::vector<buffer::AudioFrame> audio;  // 0-2 frames
  std::string asset_uri;
  int64_t block_ct_ms = 0;
  int64_t source_frame_index = -1;
};

// INV-AIR-DECODE-RESULT-EXPLICIT-001: Explicit decode outcome.
// Contract: docs/contracts/air/DECODE_RESULT_MODEL.md
enum class DecodeStatus {
  kFrame,     // Normal decoded frame available
  kUnderrun,  // Temporary — no frame this tick, may recover
  kEof,       // Terminal — segment asset exhausted, no more frames
  kError      // Fatal — decoder failed, unrecoverable for this segment
};

// INV-AIR-DECODE-RESULT-SCOPE-001: Per-call result, no persistent state.
struct DecodeResult {
  DecodeStatus status;
  std::optional<FrameData> frame;  // present when status == kFrame
};

class ITickProducer {
 public:
  virtual ~ITickProducer() = default;

  enum class State { kEmpty, kReady };

  // Assign a block.  Synchronous: probes assets, opens decoder, seeks.
  virtual void AssignBlock(const FedBlock& block) = 0;

  // INV-AIR-DECODE-RESULT-EXPLICIT-001: Decode one frame with explicit status.
  // Contract: docs/contracts/air/DECODE_RESULT_MODEL.md
  virtual DecodeResult TryGetFrame() = 0;

  // Reset to EMPTY, releasing decoder and block state.
  virtual void Reset() = 0;

  virtual State GetState() const = 0;
  virtual const FedBlock& GetBlock() const = 0;
  virtual int64_t FramesPerBlock() const = 0;
  virtual bool HasDecoder() const = 0;

  // Return the detected input (source) FPS from the decoder as RationalFps.
  // Returns {0, 1} if unknown (no decoder, probe failed, etc.).
  virtual RationalFps GetInputRationalFps() const = 0;

  // Legacy accessor (implemented as ToDouble() wrapper for compatibility).
  // Prefer GetInputRationalFps() for new code.
  double GetInputFPS() const { return GetInputRationalFps().ToDouble(); }


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

  // Diagnostic only (STARTUP_TRACE): 0-based count of frames emitted by this producer.
  // Returns -1 for non-TickProducer implementations.
  virtual int64_t GetFrameIndex() const { return -1; }

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

  // INV-AIR-PRODUCER-PRIME-001: Audio priming result.
  // Defined on the interface so PipelineManager can prime any producer
  // without concrete-type downcasts.
  struct PrimeResult {
    bool met_threshold = false;
    int actual_depth_ms = 0;
  };

  // INV-AIR-PRODUCER-PRIME-001: Prime audio to min_audio_prime_ms depth.
  // TickProducer overrides with real decoding.  Other implementations
  // (test stubs, pad-only producers) inherit the default no-op.
  virtual PrimeResult PrimeFirstTick(int /*min_audio_prime_ms*/) {
    return {false, 0};
  }

  // INV-AIR-PRODUCER-ASPECT-001: Set aspect policy for decoder scaling.
  // TickProducer overrides to configure FFmpegDecoder.  Other
  // implementations inherit the default no-op.
  virtual void SetAspectPolicy(runtime::AspectPolicy) {}
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_ITICK_PRODUCER_HPP_
