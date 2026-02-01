// Repository: Retrovue-playout
// Component: Producer Interface
// Purpose: Minimal interface for producers required by the contract.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PRODUCERS_IPRODUCER_H_
#define RETROVUE_PRODUCERS_IPRODUCER_H_

#include <cstdint>
#include <optional>
#include <string>

namespace retrovue::producers
{

  // Contract-level observability: as-run frame stats for AIR_AS_RUN_FRAME_RANGE probe.
  // Producers that track segment execution (e.g. FileProducer, ProgrammaticProducer)
  // may return this; others (e.g. BlackFrameProducer) return nullopt.
  struct AsRunFrameStats {
    std::string asset_path;
    int64_t start_frame{0};
    uint64_t frames_emitted{0};
  };

  // IProducer defines the minimal interface required by the contract.
  // All producers must implement this interface.
  //
  // Lifecycle: AIR owns when a producer is no longer allowed to emit.
  // RequestStop() is the cooperative signal; the producer decides how to wind down safely.
  class IProducer
  {
  public:
    virtual ~IProducer() = default;

    // Starts the producer.
    // Returns true if started successfully, false if already running or on error.
    virtual bool start() = 0;

    // Stops the producer.
    // Blocks until the producer thread exits.
    virtual void stop() = 0;

    // Returns true if the producer is currently running.
    virtual bool isRunning() const = 0;

    // Lifecycle: revoke the producer's right to publish frames. Cooperatively wind down.
    // Called when segment commits or switch completes; producer must not emit after this.
    virtual void RequestStop() = 0;

    // Returns true if the producer has stopped (no longer running / output revoked).
    virtual bool IsStopped() const = 0;

    // Contract-level observability: optional as-run stats for AIR_AS_RUN_FRAME_RANGE.
    // Default returns nullopt; content producers (FileProducer, ProgrammaticProducer) override.
    virtual std::optional<AsRunFrameStats> GetAsRunFrameStats() const { return std::nullopt; }
  };

} // namespace retrovue::producers

#endif // RETROVUE_PRODUCERS_IPRODUCER_H_







