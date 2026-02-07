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

#include <cstdint>
#include <optional>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"

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
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_ITICK_PRODUCER_HPP_
