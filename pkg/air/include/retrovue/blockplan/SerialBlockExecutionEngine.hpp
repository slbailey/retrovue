// Repository: Retrovue-playout
// Component: Serial Block Execution Engine
// Purpose: Wraps the existing BlockPlanExecutionThread as an IPlayoutExecutionEngine
// Contract Reference: INV-SERIAL-BLOCK-EXECUTION, INV-ONE-ENCODER-PER-SESSION
// Copyright (c) 2025 RetroVue
//
// This is a mechanical extraction of PlayoutControlImpl::BlockPlanExecutionThread.
// No logic changes from the original implementation.

#ifndef RETROVUE_BLOCKPLAN_SERIAL_BLOCK_EXECUTION_ENGINE_HPP_
#define RETROVUE_BLOCKPLAN_SERIAL_BLOCK_EXECUTION_ENGINE_HPP_

#include <functional>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/IPlayoutExecutionEngine.hpp"
#include "retrovue/blockplan/SerialBlockMetrics.hpp"

namespace retrovue::blockplan {

// =============================================================================
// SerialBlockExecutionEngine
// Executes blocks sequentially from the session context's block queue.
// Owns the execution thread. Creates and owns the session-long encoder.
//
// INV-SERIAL-BLOCK-EXECUTION: Block N completes before Block N+1 begins.
// INV-ONE-ENCODER-PER-SESSION: Encoder opened once at Start(), closed at Stop().
// =============================================================================

class SerialBlockExecutionEngine : public IPlayoutExecutionEngine {
 public:
  // Callbacks for event emission (gRPC layer provides these)
  struct Callbacks {
    // Called when a block reaches its fence.
    // Parameters: block, final_ct_ms
    std::function<void(const FedBlock& block, int64_t final_ct_ms)> on_block_completed;

    // Called when the session ends (all blocks done, error, or stopped).
    // Parameters: reason
    std::function<void(const std::string& reason)> on_session_ended;
  };

  // Construct engine with session context and callbacks.
  // session_ctx must outlive this engine instance.
  SerialBlockExecutionEngine(BlockPlanSessionContext* session_ctx,
                             Callbacks callbacks);
  ~SerialBlockExecutionEngine() override;

  // IPlayoutExecutionEngine
  void Start() override;
  void Stop() override;

  // Thread-safe access to accumulated session metrics.
  // Returns a snapshot suitable for Prometheus text generation.
  SerialBlockMetrics SnapshotMetrics() const;

  // Generate Prometheus text exposition for serial block metrics.
  // Thread-safe: acquires internal lock.
  std::string GenerateMetricsText() const;

 private:
  // The execution thread body (extracted from BlockPlanExecutionThread)
  void Run();

  BlockPlanSessionContext* ctx_;
  Callbacks callbacks_;
  std::thread thread_;
  bool started_ = false;

  // Metrics (written by Run() thread, read by metrics HTTP thread)
  mutable std::mutex metrics_mutex_;
  SerialBlockMetrics metrics_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_SERIAL_BLOCK_EXECUTION_ENGINE_HPP_
